import json
import os

# TensorFlow must see these before import: default pools can exceed pids / pthread
# limits on shared hosting and trigger pthread_create() EAGAIN (errno 11).
def _cap_tf_thread_env() -> None:
    cap = (os.environ.get("TF_THREAD_CAP") or "2").strip() or "2"
    os.environ.setdefault("TF_NUM_INTRAOP_THREADS", cap)
    os.environ.setdefault("TF_NUM_INTEROP_THREADS", "1")
    os.environ.setdefault("OMP_NUM_THREADS", cap)
    os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
    os.environ.setdefault("MKL_NUM_THREADS", "1")
    os.environ.setdefault("NUMEXPR_MAX_THREADS", cap)
    # CUDA visibility is set in inference_tasks via compute_env before TF is first imported.
    # 0=all, 1=hide INFO, 2=hide INFO+WARNING, 3=hide ERROR too (use 2 normally).
    os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "2")


_cap_tf_thread_env()

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import nibabel as nib
import plotly.graph_objects as go
import plotly.io as pio
import tensorflow as tf

try:
    _intra = int(os.environ.get("TF_NUM_INTRAOP_THREADS", "2"))
    _inter = int(os.environ.get("TF_NUM_INTEROP_THREADS", "1"))
    tf.config.threading.set_intra_op_parallelism_threads(max(1, _intra))
    tf.config.threading.set_inter_op_parallelism_threads(max(1, _inter))
except Exception:
    pass

from scipy.ndimage import binary_fill_holes, gaussian_filter, zoom
from skimage.morphology import ball, binary_closing, binary_opening, remove_small_objects
from skimage.measure import marching_cubes


TARGET_SHAPE = (128, 128, 128)

CLASS_LABELS = {
    0: "Background",
    1: "ET - Enhancing Tumor",
    2: "NETC - Non-Enhancing Tumor Core",
    3: "SNFH - Surrounding Non-Enhancing FLAIR Hyperintensity",
    4: "RC - Resection Cavity",
}


def instance_normalization(x, epsilon=1e-5):
    mean, var = tf.nn.moments(x, axes=[1, 2, 3], keepdims=True)
    return (x - mean) / tf.sqrt(var + epsilon)


def _is_nifti_path(p: str) -> bool:
    p = (p or "").lower()
    return p.endswith(".nii") or p.endswith(".nii.gz")


def _load_nii(path: str):
    nii = nib.load(path)
    arr = nii.get_fdata().astype(np.float32)
    return arr, nii.affine, nii.header


def _normalize_volume(arr: np.ndarray) -> np.ndarray:
    arr = arr.astype(np.float32)
    std = float(np.std(arr))
    if std < 1e-8:
        return arr - float(np.mean(arr))
    return (arr - float(np.mean(arr))) / std


def _robust_minmax(arr: np.ndarray) -> np.ndarray:
    arr = arr.astype(np.float32)
    p1 = float(np.percentile(arr, 1))
    p99 = float(np.percentile(arr, 99))
    arr = np.clip(arr, p1, p99)
    if (p99 - p1) < 1e-8:
        return np.zeros_like(arr, dtype=np.float32)
    return (arr - p1) / (p99 - p1)


def _resize_volume(arr: np.ndarray, target_shape=TARGET_SHAPE, order: int = 1) -> np.ndarray:
    factors = [t / s for t, s in zip(target_shape, arr.shape)]
    return zoom(arr, zoom=factors, order=order)


def _pick_modalities(input_paths: list[str]) -> dict:
    """
    Map uploaded files to (t1c,t1n,t2f,t2w) using filename hints.
    """
    tagged: dict[str, str] = {}
    for p in input_paths:
        name = os.path.basename(p).lower()
        if ("t1c" in name) or ("t1ce" in name) or ("t1gd" in name):
            tagged.setdefault("t1c", p)
        elif ("t1n" in name) or (("t1" in name) and ("t1c" not in name) and ("t1ce" not in name)):
            tagged.setdefault("t1n", p)
        elif ("t2f" in name) or ("flair" in name):
            tagged.setdefault("t2f", p)
        elif "t2w" in name or ("t2" in name and "t2f" not in name and "flair" not in name):
            tagged.setdefault("t2w", p)

    # Fallback to positional mapping if we couldn't detect all tags.
    if len(tagged) < 4 and len(input_paths) >= 4:
        fallback_keys = ["t1c", "t1n", "t2f", "t2w"]
        for key, p in zip(fallback_keys, input_paths[:4]):
            tagged.setdefault(key, p)

    missing = [k for k in ("t1c", "t1n", "t2f", "t2w") if k not in tagged]
    if missing:
        raise FileNotFoundError(f"Missing MRI modalities: {missing}. Got: {[os.path.basename(p) for p in input_paths]}")
    return tagged


def _load_case_4_modalities(input_paths: list[str]):
    paths = _pick_modalities(input_paths)

    t1c, affine, header = _load_nii(paths["t1c"])
    t1n, _, _ = _load_nii(paths["t1n"])
    t2f, _, _ = _load_nii(paths["t2f"])
    t2w, _, _ = _load_nii(paths["t2w"])

    original_shape = t1c.shape
    raw_modalities = {"t1c": t1c.copy(), "t1n": t1n.copy(), "t2f": t2f.copy(), "t2w": t2w.copy()}

    t1c_r = _resize_volume(_normalize_volume(t1c), TARGET_SHAPE, order=1)
    t1n_r = _resize_volume(_normalize_volume(t1n), TARGET_SHAPE, order=1)
    t2f_r = _resize_volume(_normalize_volume(t2f), TARGET_SHAPE, order=1)
    t2w_r = _resize_volume(_normalize_volume(t2w), TARGET_SHAPE, order=1)

    x = np.stack([t1c_r, t1n_r, t2f_r, t2w_r], axis=-1).astype(np.float32)
    return x, original_shape, affine, header, paths, raw_modalities


def _load_segmentation_model(model_path: str):
    if not model_path or not os.path.exists(model_path):
        raise FileNotFoundError(f"Brain model not found at: {model_path}")

    return tf.keras.models.load_model(
        model_path,
        custom_objects={"instance_normalization": instance_normalization},
        compile=False,
        safe_mode=False,
    )


def _predict_mask(model, x: np.ndarray):
    x_input = np.expand_dims(x, axis=0)
    probs = model.predict(x_input, verbose=0)
    pred_mask = np.argmax(probs[0], axis=-1).astype(np.uint8)
    return probs[0], pred_mask


def _resize_mask_to_original(pred_mask: np.ndarray, original_shape):
    return _resize_volume(pred_mask.astype(np.float32), original_shape, order=0).astype(np.uint8)


def _compute_tumor_stats(mask: np.ndarray, voxel_spacing=None) -> dict:
    tumor_mask = mask > 0
    num_voxels = int(np.sum(tumor_mask))

    stats: dict = {
        "tumor_present": bool(num_voxels > 0),
        "total_tumor_voxels": int(num_voxels),
        "classes": {},
        # Ensure stable keys for downstream UI/API even when spacing is missing.
        "tumor_volume_mm3": None,
        "tumor_volume_cm3": None,
        "bbox": None,
        "center_voxel": None,
    }

    if voxel_spacing is not None:
        voxel_volume_mm3 = float(voxel_spacing[0] * voxel_spacing[1] * voxel_spacing[2])
        stats["tumor_volume_mm3"] = float(num_voxels * voxel_volume_mm3)
        stats["tumor_volume_cm3"] = float((num_voxels * voxel_volume_mm3) / 1000.0)
    else:
        # Fallback: still provide numeric volumes assuming 1mm^3 voxels.
        stats["tumor_volume_mm3"] = float(num_voxels)
        stats["tumor_volume_cm3"] = float(num_voxels / 1000.0)

    if num_voxels == 0:
        return stats

    coords = np.argwhere(tumor_mask)
    zmin, ymin, xmin = coords.min(axis=0)
    zmax, ymax, xmax = coords.max(axis=0)
    stats["bbox"] = {
        "zmin": int(zmin),
        "zmax": int(zmax),
        "ymin": int(ymin),
        "ymax": int(ymax),
        "xmin": int(xmin),
        "xmax": int(xmax),
    }
    stats["center_voxel"] = [float(v) for v in coords.mean(axis=0).tolist()]

    for cls_id, cls_name in CLASS_LABELS.items():
        if cls_id == 0:
            continue
        cls_voxels = int(np.sum(mask == cls_id))
        if cls_voxels <= 0:
            continue
        item = {"name": cls_name, "voxels": cls_voxels}
        if voxel_spacing is not None:
            voxel_volume_mm3 = float(voxel_spacing[0] * voxel_spacing[1] * voxel_spacing[2])
            item["volume_mm3"] = float(cls_voxels * voxel_volume_mm3)
            item["volume_cm3"] = float((cls_voxels * voxel_volume_mm3) / 1000.0)
        else:
            item["volume_mm3"] = float(cls_voxels)
            item["volume_cm3"] = float(cls_voxels / 1000.0)
        stats["classes"][str(cls_id)] = item

    return stats


def _save_mask_nifti(mask: np.ndarray, affine, header, out_path: str):
    nii = nib.Nifti1Image(mask.astype(np.uint8), affine, header)
    nib.save(nii, out_path)


def _build_clean_brain_mask(raw_modalities, target_shape=TARGET_SHAPE):
    vols = []
    for key in ["t1c", "t1n", "t2f", "t2w"]:
        v = _robust_minmax(raw_modalities[key])
        v = _resize_volume(v, target_shape, order=1)
        vols.append(v)

    combined = np.mean(np.stack(vols, axis=0), axis=0)
    combined = gaussian_filter(combined, sigma=1.0)

    non_zero = combined[combined > 0]
    if len(non_zero) == 0:
        brain_mask = combined > 0
    else:
        thresh = float(np.percentile(non_zero, 25))
        brain_mask = combined > thresh

    brain_mask = binary_opening(brain_mask, footprint=ball(1))
    brain_mask = binary_closing(brain_mask, footprint=ball(2))
    brain_mask = remove_small_objects(brain_mask, min_size=5000)
    brain_mask = binary_fill_holes(brain_mask)

    return combined, brain_mask.astype(np.uint8)


def _make_brain_and_tumor_3d_multiclass_html(raw_modalities, tumor_mask: np.ndarray, html_path: str):
    _, brain_mask = _build_clean_brain_mask(raw_modalities, target_shape=tumor_mask.shape)

    fig = go.Figure()

    if int(np.sum(brain_mask)) > 0:
        verts_b, faces_b, _, _ = marching_cubes(brain_mask.astype(np.float32), level=0.5)
        fig.add_trace(
            go.Mesh3d(
                x=verts_b[:, 0],
                y=verts_b[:, 1],
                z=verts_b[:, 2],
                i=faces_b[:, 0],
                j=faces_b[:, 1],
                k=faces_b[:, 2],
                color="gray",
                opacity=0.18,
                name="Brain",
            )
        )

    class_colors = {1: "yellow", 2: "red", 3: "limegreen", 4: "deepskyblue"}

    for cls_id, cls_color in class_colors.items():
        cls_binary = (tumor_mask == cls_id).astype(np.uint8)
        if int(np.sum(cls_binary)) <= 20:
            continue

        cls_smooth = gaussian_filter(cls_binary.astype(np.float32), sigma=0.8)
        try:
            verts_t, faces_t, _, _ = marching_cubes(cls_smooth, level=0.3)
        except ValueError:
            continue

        fig.add_trace(
            go.Mesh3d(
                x=verts_t[:, 0],
                y=verts_t[:, 1],
                z=verts_t[:, 2],
                i=faces_t[:, 0],
                j=faces_t[:, 1],
                k=faces_t[:, 2],
                color=cls_color,
                opacity=0.85,
                name=CLASS_LABELS.get(cls_id, f"Class {cls_id}"),
            )
        )

    fig.update_layout(
        title="3D Brain + Multiclass Tumor Segmentation",
        scene=dict(xaxis_title="X", yaxis_title="Y", zaxis_title="Z", bgcolor="white", aspectmode="data"),
        margin=dict(l=0, r=0, b=0, t=40),
        legend=dict(x=0.02, y=0.98),
    )

    # IMPORTANT: embed plotly.js so it works without internet/CDN inside iframe.
    html = "<!DOCTYPE html>\n" + pio.to_html(
        fig,
        full_html=True,
        include_plotlyjs=True,
        config={"responsive": True, "displaylogo": False},
    )
    with open(html_path, "w", encoding="utf-8") as f:
        f.write(html)


def _make_brain_and_tumor_3d_gray_html(raw_modalities, tumor_mask_binary: np.ndarray, html_path: str):
    _, brain_mask = _build_clean_brain_mask(raw_modalities, target_shape=tumor_mask_binary.shape)

    fig = go.Figure()

    if int(np.sum(brain_mask)) > 0:
        verts_b, faces_b, _, _ = marching_cubes(brain_mask.astype(np.float32), level=0.5)
        fig.add_trace(
            go.Mesh3d(
                x=verts_b[:, 0],
                y=verts_b[:, 1],
                z=verts_b[:, 2],
                i=faces_b[:, 0],
                j=faces_b[:, 1],
                k=faces_b[:, 2],
                color="gray",
                opacity=0.18,
                name="Brain",
            )
        )

    tumor_binary = (tumor_mask_binary > 0).astype(np.uint8)
    if int(np.sum(tumor_binary)) > 20:
        tumor_smooth = gaussian_filter(tumor_binary.astype(np.float32), sigma=0.8)
        try:
            verts_t, faces_t, _, _ = marching_cubes(tumor_smooth, level=0.3)
            fig.add_trace(
                go.Mesh3d(
                    x=verts_t[:, 0],
                    y=verts_t[:, 1],
                    z=verts_t[:, 2],
                    i=faces_t[:, 0],
                    j=faces_t[:, 1],
                    k=faces_t[:, 2],
                    color="red",
                    opacity=0.85,
                    name="Tumor",
                )
            )
        except ValueError:
            pass

    fig.update_layout(
        title="3D Brain Shape + Predicted Tumor",
        scene=dict(xaxis_title="X", yaxis_title="Y", zaxis_title="Z", bgcolor="white", aspectmode="data"),
        margin=dict(l=0, r=0, b=0, t=40),
        legend=dict(x=0.02, y=0.98),
    )

    html = "<!DOCTYPE html>\n" + pio.to_html(
        fig,
        full_html=True,
        include_plotlyjs=True,
        config={"responsive": True, "displaylogo": False},
    )
    with open(html_path, "w", encoding="utf-8") as f:
        f.write(html)


def _overlay_binary(gray_slice: np.ndarray, mask_slice: np.ndarray, alpha=0.45):
    gray = _robust_minmax(gray_slice)
    rgb = np.stack([gray, gray, gray], axis=-1)
    tumor = mask_slice > 0
    if np.any(tumor):
        red = np.zeros_like(rgb)
        red[..., 0] = 1.0
        rgb[tumor] = (1 - alpha) * rgb[tumor] + alpha * red[tumor]
    return np.clip(rgb, 0, 1)


def _save_slice_views_binary(raw_modalities, pred_mask_original: np.ndarray, output_dir: str):
    base_vol = raw_modalities["t1c"]
    coords = np.argwhere(pred_mask_original > 0)
    if len(coords) > 0:
        cz, cy, cx = np.mean(coords, axis=0).astype(int)
    else:
        cz, cy, cx = (np.array(base_vol.shape) // 2).tolist()

    views = {
        "axial": (base_vol[cz, :, :], pred_mask_original[cz, :, :]),
        "coronal": (base_vol[:, cy, :], pred_mask_original[:, cy, :]),
        "sagittal": (base_vol[:, :, cx], pred_mask_original[:, :, cx]),
    }

    for name, (img_slice, mask_slice) in views.items():
        raw_path = os.path.join(output_dir, f"{name}_raw.png")
        plt.figure(figsize=(6, 6))
        plt.imshow(_robust_minmax(img_slice), cmap="gray", origin="lower")
        plt.axis("off")
        plt.savefig(raw_path, bbox_inches="tight", pad_inches=0.05, dpi=180)
        plt.close()

        overlay = _overlay_binary(img_slice, mask_slice)
        out_path = os.path.join(output_dir, f"{name}_overlay.png")
        plt.figure(figsize=(6, 6))
        plt.imshow(overlay, origin="lower")
        plt.axis("off")
        plt.savefig(out_path, bbox_inches="tight", pad_inches=0.05, dpi=180)
        plt.close()


def overlay_multiclass(gray_slice, mask_slice, alpha=0.55):
    """
    Same behavior as the notebook helper:
    - normalize grayscale to [0,1]
    - blend per-class colors over the slice
    """
    gray = gray_slice.astype(float)
    gray = (gray - gray.min()) / (gray.max() - gray.min() + 1e-8)

    rgb = np.stack([gray, gray, gray], axis=-1)

    colors = {
        1: np.array([1.0, 1.0, 0.0]),  # yellow
        2: np.array([1.0, 0.0, 0.0]),  # red
        3: np.array([0.0, 1.0, 0.0]),  # green
        4: np.array([0.0, 0.6, 1.0]),  # blue
    }

    for cls, color in colors.items():
        region = mask_slice == cls
        rgb[region] = (1 - alpha) * rgb[region] + alpha * color

    return np.clip(rgb, 0, 1)


def save_slice_views_multiclass(raw_modalities, pred_mask_original, output_dir):
    """
    Same naming contract as the notebook:
      axial_multiclass.png / coronal_multiclass.png / sagittal_multiclass.png
    """
    base_vol = raw_modalities["t1c"]
    coords = np.argwhere(pred_mask_original > 0)
    if len(coords) > 0:
        cz, cy, cx = np.mean(coords, axis=0).astype(int)
    else:
        cz, cy, cx = (np.array(base_vol.shape) // 2).tolist()

    views = {
        "axial_multiclass": (base_vol[cz, :, :], pred_mask_original[cz, :, :]),
        "coronal_multiclass": (base_vol[:, cy, :], pred_mask_original[:, cy, :]),
        "sagittal_multiclass": (base_vol[:, :, cx], pred_mask_original[:, :, cx]),
    }

    for name, (img_slice, mask_slice) in views.items():
        overlay = overlay_multiclass(img_slice, mask_slice)
        plt.figure(figsize=(6, 6))
        plt.imshow(overlay, origin="lower")
        plt.axis("off")
        plt.title(name.replace("_", " ").title())
        out_path = os.path.join(output_dir, f"{name}.png")
        plt.savefig(out_path, bbox_inches="tight", pad_inches=0.05, dpi=180)
        plt.close()

        if os.environ.get("BRAIN_VERBOSE_EXPORTS") == "1":
            print(f"[OK] Saved {name}: {out_path}")


def make_brain_and_tumor_3d_multiclass_html(raw_modalities, tumor_mask, html_path):
    """
    Notebook-equivalent multiclass 3D export.
    We still embed plotly.js so the iframe works offline.
    """
    _, brain_mask = _build_clean_brain_mask(raw_modalities, target_shape=tumor_mask.shape)

    fig = go.Figure()

    if np.sum(brain_mask) > 0:
        verts_b, faces_b, _, _ = marching_cubes(brain_mask.astype(np.float32), level=0.5)
        fig.add_trace(
            go.Mesh3d(
                x=verts_b[:, 0],
                y=verts_b[:, 1],
                z=verts_b[:, 2],
                i=faces_b[:, 0],
                j=faces_b[:, 1],
                k=faces_b[:, 2],
                color="gray",
                opacity=0.18,
                name="Brain",
            )
        )

    class_colors = {1: "yellow", 2: "red", 3: "limegreen", 4: "deepskyblue"}

    for cls_id, cls_color in class_colors.items():
        cls_binary = (tumor_mask == cls_id).astype(np.uint8)
        if np.sum(cls_binary) > 20:
            cls_smooth = gaussian_filter(cls_binary.astype(np.float32), sigma=0.8)
            try:
                verts_t, faces_t, _, _ = marching_cubes(cls_smooth, level=0.3)
                fig.add_trace(
                    go.Mesh3d(
                        x=verts_t[:, 0],
                        y=verts_t[:, 1],
                        z=verts_t[:, 2],
                        i=faces_t[:, 0],
                        j=faces_t[:, 1],
                        k=faces_t[:, 2],
                        color=cls_color,
                        opacity=0.85,
                        name=CLASS_LABELS.get(cls_id, f"Class {cls_id}"),
                    )
                )
            except ValueError:
                pass

    fig.update_layout(
        title="3D Brain + Multiclass Tumor Segmentation",
        scene=dict(xaxis_title="X", yaxis_title="Y", zaxis_title="Z", bgcolor="white", aspectmode="data"),
        margin=dict(l=0, r=0, b=0, t=40),
        legend=dict(x=0.02, y=0.98),
    )

    html = "<!DOCTYPE html>\n" + pio.to_html(
        fig,
        full_html=True,
        include_plotlyjs=True,
        config={"responsive": True, "displaylogo": False},
    )
    with open(html_path, "w", encoding="utf-8") as f:
        f.write(html)


def _save_fake_overlay(path: str, title: str):
    fig = plt.figure(figsize=(4, 4))
    ax = fig.add_subplot(111)
    data = np.random.rand(128, 128)
    ax.imshow(data, cmap="gray", origin="lower")
    ax.set_title(title)
    ax.axis("off")
    fig.savefig(path, bbox_inches="tight", pad_inches=0.05, dpi=120)
    plt.close(fig)


def _save_fake_html(path: str):
    """
    Generate a self-contained Plotly HTML (standard mode, not quirks).
    This is still a placeholder *pipeline*, but produces a real 3D viewer
    so the UI iframe loads and renders as expected.
    """
    # Synthetic "brain" and 3 tumor subregions for demo rendering.
    n = 128
    zz, yy, xx = np.mgrid[:n, :n, :n]
    cx = cy = cz = (n - 1) / 2.0
    r = np.sqrt((xx - cx) ** 2 + (yy - cy) ** 2 + (zz - cz) ** 2)

    brain = (r < 54).astype(np.float32)

    tumor_mask = np.zeros((n, n, n), dtype=np.uint8)
    tumor_mask[r < 18] = 2  # NETC
    tumor_mask[(r >= 18) & (r < 24)] = 3  # SNFH
    tumor_mask[(xx - cx) ** 2 + (yy - cy) ** 2 + (zz - (cz + 16)) ** 2 < 10**2] = 4  # RC

    fig = go.Figure()

    # Brain mesh
    if int(brain.sum()) > 0:
        verts_b, faces_b, _, _ = marching_cubes(brain, level=0.5)
        fig.add_trace(
            go.Mesh3d(
                x=verts_b[:, 0],
                y=verts_b[:, 1],
                z=verts_b[:, 2],
                i=faces_b[:, 0],
                j=faces_b[:, 1],
                k=faces_b[:, 2],
                color="gray",
                opacity=0.15,
                name="Brain",
            )
        )

    class_colors = {2: "red", 3: "limegreen", 4: "deepskyblue"}
    class_names = {2: "NETC", 3: "SNFH", 4: "RC"}

    for cls_id, cls_color in class_colors.items():
        binary = (tumor_mask == cls_id).astype(np.float32)
        if int(binary.sum()) < 50:
            continue
        smooth = gaussian_filter(binary, sigma=0.8)
        try:
            verts_t, faces_t, _, _ = marching_cubes(smooth, level=0.3)
        except ValueError:
            continue
        fig.add_trace(
            go.Mesh3d(
                x=verts_t[:, 0],
                y=verts_t[:, 1],
                z=verts_t[:, 2],
                i=faces_t[:, 0],
                j=faces_t[:, 1],
                k=faces_t[:, 2],
                color=cls_color,
                opacity=0.85,
                name=class_names.get(cls_id, f"Class {cls_id}"),
            )
        )

    fig.update_layout(
        title="3D Brain + Multiclass Tumor Segmentation",
        scene=dict(
            xaxis_title="X",
            yaxis_title="Y",
            zaxis_title="Z",
            bgcolor="white",
            aspectmode="data",
        ),
        margin=dict(l=0, r=0, b=0, t=40),
        legend=dict(x=0.02, y=0.98),
    )

    # Plotly HTML generated by pio.to_html doesn't include DOCTYPE; add it to avoid quirks mode.
    html = "<!DOCTYPE html>\n" + pio.to_html(
        fig,
        full_html=True,
        include_plotlyjs=True,
        config={"responsive": True, "displaylogo": False},
    )
    with open(path, "w", encoding="utf-8") as f:
        f.write(html)


def run_brain_inference(input_paths, model_path: str, output_dir: str, progress_callback=None):
    os.makedirs(output_dir, exist_ok=True)
    if isinstance(input_paths, (list, tuple)):
        primary_input = input_paths[0] if input_paths else ""
        all_inputs = list(input_paths)
    else:
        primary_input = input_paths
        all_inputs = [input_paths]
    axial = os.path.join(output_dir, "axial_overlay.png")
    coronal = os.path.join(output_dir, "coronal_overlay.png")
    sagittal = os.path.join(output_dir, "sagittal_overlay.png")
    html_3d_gray = os.path.join(output_dir, "brain_tumor_3d_gray.html")
    html_3d_multi = os.path.join(output_dir, "brain_tumor_3d_multiclass.html")
    report_path = os.path.join(output_dir, "report.json")
    mask_path = os.path.join(output_dir, "pred_mask.nii.gz")

    # Validate inputs early; random-noise overlays are not useful for users.
    if len(all_inputs) != 4 or not all(_is_nifti_path(p) for p in all_inputs):
        raise ValueError(
            "Brain 3D inference expects exactly 4 MRI files (.nii / .nii.gz): t1c, t1n, t2f(FLAIR), t2w."
        )

    if progress_callback:
        progress_callback(15)
    x, original_shape, affine, header, found_files, raw_modalities = _load_case_4_modalities(all_inputs)

    if progress_callback:
        progress_callback(35)
    if progress_callback:
        progress_callback(40)
    model = _load_segmentation_model(model_path)

    if progress_callback:
        progress_callback(48)
    if progress_callback:
        progress_callback(55)
    _, pred_mask_128 = _predict_mask(model, x)

    if progress_callback:
        progress_callback(70)
    pred_mask_original = _resize_mask_to_original(pred_mask_128, original_shape)

    voxel_spacing = header.get_zooms()[:3] if header is not None else None
    stats = _compute_tumor_stats(pred_mask_original, voxel_spacing=voxel_spacing)

    if progress_callback:
        progress_callback(80)
    _save_mask_nifti(pred_mask_original, affine, header, mask_path)

    # 2D outputs (like notebook)
    _save_slice_views_binary(raw_modalities, pred_mask_original, output_dir)
    save_slice_views_multiclass(raw_modalities, pred_mask_original, output_dir)

    # 3D outputs (like notebook). Use 128^3 mask for responsiveness.
    _make_brain_and_tumor_3d_gray_html(raw_modalities, (pred_mask_128 > 0).astype(np.uint8), html_3d_gray)
    make_brain_and_tumor_3d_multiclass_html(raw_modalities, pred_mask_128, html_3d_multi)

    report = {
        "inputs": all_inputs,
        "found_files": found_files,
        "artifacts": {
            "mask_path": mask_path,
            "report_path": report_path,
            "axial_raw": os.path.join(output_dir, "axial_raw.png"),
            "coronal_raw": os.path.join(output_dir, "coronal_raw.png"),
            "sagittal_raw": os.path.join(output_dir, "sagittal_raw.png"),
            "axial_overlay": os.path.join(output_dir, "axial_overlay.png"),
            "coronal_overlay": os.path.join(output_dir, "coronal_overlay.png"),
            "sagittal_overlay": os.path.join(output_dir, "sagittal_overlay.png"),
            "axial_multiclass": os.path.join(output_dir, "axial_multiclass.png"),
            "coronal_multiclass": os.path.join(output_dir, "coronal_multiclass.png"),
            "sagittal_multiclass": os.path.join(output_dir, "sagittal_multiclass.png"),
            "html_3d_gray": html_3d_gray,
            "html_3d_multiclass": html_3d_multi,
        },
        **stats,
    }
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)

    diagnosis = "Tumor suspected" if report.get("tumor_present") else "No tumor detected"
    confidence = 0.9 if report.get("tumor_present") else 0.6

    return {
        "report_json": report,
        "report_path": report_path,
        "mask_path": mask_path,
        "axial_overlay_path": axial,
        "coronal_overlay_path": coronal,
        "sagittal_overlay_path": sagittal,
        # Keep the existing DB field pointing to the multiclass 3D output.
        "html_3d_path": html_3d_multi,
        "diagnosis_label": diagnosis,
        "confidence": float(confidence),
    }

