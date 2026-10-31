import os

import albumentations as A
import cv2
import numpy as np
import pandas as pd
import timm
import torch
import torch.nn as nn
import torch.nn.functional as F


IMG_SIZE = 384
NUM_CLASSES = 5
MODEL_NAME = "tf_efficientnetv2_s.in21k_ft_in1k"
DEVICE = torch.device("cuda" if torch.cuda.is_available() else "cpu")

CLASS_NAMES = {
    0: "No DR",
    1: "Mild DR",
    2: "Moderate DR",
    3: "Severe DR",
    4: "Proliferative DR",
}

DEFAULT_THRESHOLDS = np.array([0.5, 1.5, 2.5, 3.5], dtype=np.float32)

VALID_TRANSFORMS = A.Compose(
    [
        A.Resize(IMG_SIZE, IMG_SIZE),
        A.Normalize(mean=(0.485, 0.456, 0.406), std=(0.229, 0.224, 0.225)),
    ]
)


class DRModel(nn.Module):
    def __init__(self, model_name=MODEL_NAME, num_classes=NUM_CLASSES):
        super().__init__()
        self.backbone = timm.create_model(
            model_name,
            pretrained=False,
            num_classes=0,
            global_pool="avg",
        )
        in_features = self.backbone.num_features
        self.head = nn.Sequential(
            nn.Dropout(0.35),
            nn.Linear(in_features, 512),
            nn.SiLU(),
            nn.Dropout(0.30),
            nn.Linear(512, num_classes),
        )

    def forward(self, x):
        x = self.backbone(x)
        x = self.head(x)
        return x


def _crop_image_from_gray(img: np.ndarray, tol: int = 7) -> np.ndarray:
    gray = cv2.cvtColor(img, cv2.COLOR_RGB2GRAY)
    mask = gray > tol
    if mask.sum() == 0:
        return img
    return img[np.ix_(mask.any(1), mask.any(0))]


def _read_image(path: str) -> np.ndarray:
    img = cv2.imread(path)
    if img is None:
        raise ValueError(f"Image not found: {path}")
    img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
    img = _crop_image_from_gray(img)
    return img


def _sanitize_state_dict(state_dict: dict) -> dict:
    cleaned = {}
    for k, v in state_dict.items():
        cleaned[k.replace("_orig_mod.", "")] = v
    return cleaned


def _load_model(model_path: str) -> DRModel:
    if not model_path or not os.path.exists(model_path):
        raise FileNotFoundError(f"Retina model not found at: {model_path}")

    checkpoint = torch.load(model_path, map_location=DEVICE)
    if isinstance(checkpoint, dict) and "model_state_dict" in checkpoint:
        state_dict = checkpoint["model_state_dict"]
    elif isinstance(checkpoint, dict):
        state_dict = checkpoint
    else:
        raise ValueError("Unsupported retina checkpoint format.")

    model = DRModel().to(DEVICE)
    model.load_state_dict(_sanitize_state_dict(state_dict), strict=True)
    model.eval()
    return model


def _load_thresholds(thresholds_path: str) -> np.ndarray:
    if not thresholds_path or not os.path.exists(thresholds_path):
        return DEFAULT_THRESHOLDS

    df = pd.read_csv(thresholds_path)
    if "threshold" in df.columns:
        values = df["threshold"].to_numpy(dtype=np.float32)
    else:
        # Fallback: first column if file has no explicit header.
        values = df.iloc[:, 0].to_numpy(dtype=np.float32)

    if values.shape[0] != (NUM_CLASSES - 1):
        raise ValueError(
            f"Invalid thresholds count in {thresholds_path}. "
            f"Expected {NUM_CLASSES - 1}, got {values.shape[0]}."
        )
    return values


@torch.no_grad()
def run_retina_inference(
    image_path: str, model_path: str, thresholds_path: str, progress_callback=None
):
    if progress_callback:
        progress_callback(35)

    model = _load_model(model_path)
    thresholds = _load_thresholds(thresholds_path)

    if progress_callback:
        progress_callback(55)

    img = _read_image(image_path)
    img = VALID_TRANSFORMS(image=img)["image"]
    tensor = torch.tensor(img, dtype=torch.float32).permute(2, 0, 1).unsqueeze(0).to(DEVICE)

    if DEVICE.type == "cuda":
        with torch.autocast(device_type="cuda", dtype=torch.bfloat16):
            output = model(tensor)
    else:
        output = model(tensor)

    probs = F.softmax(output.float(), dim=1).detach().cpu().numpy()[0]

    continuous_score = float(np.sum(probs * np.arange(NUM_CLASSES, dtype=np.float32)))
    class_id = int(np.clip(np.digitize(continuous_score, thresholds), 0, NUM_CLASSES - 1))

    probabilities = {CLASS_NAMES[i]: float(probs[i]) for i in range(NUM_CLASSES)}
    diagnosis = CLASS_NAMES[class_id]
    confidence = float(probs[class_id])

    if progress_callback:
        progress_callback(85)

    return {
        "model_type": "diabetic_retinopathy",
        "source_path": image_path,
        "model_path": model_path,
        "thresholds_path": thresholds_path,
        "class_id": class_id,
        "diagnosis": diagnosis,
        "confidence": confidence,
        "continuous_score": continuous_score,
        "thresholds": thresholds.tolist(),
        "probabilities": probabilities,
    }

