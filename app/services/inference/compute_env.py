"""
Resolve whether inference runs on CPU or CUDA *before* loading model-specific modules.

Brain path imports TensorFlow here first so we can set CUDA visibility and persist
`InferenceJob.compute_device` before `brain_tumor_service` applies thread caps.
"""

from __future__ import annotations

import os


def resolve_compute_device_label(model_type: str | object) -> str:
    mt = getattr(model_type, "value", model_type)
    mt = str(mt)

    if mt == "diabetic_retinopathy":
        try:
            import torch

            return "cuda" if torch.cuda.is_available() else "cpu"
        except Exception:
            return "cpu"

    if mt == "brain_3d":
        # Skip broken host CUDA probes unless operator explicitly allows TF GPU.
        if os.environ.get("NEUROVA_ALLOW_TF_GPU", "").strip() != "1":
            os.environ.setdefault("CUDA_VISIBLE_DEVICES", "-1")
        try:
            import tensorflow as tf

            gpus = tf.config.list_physical_devices("GPU")
            return "cuda" if gpus else "cpu"
        except Exception:
            return "cpu"

    return "cpu"
