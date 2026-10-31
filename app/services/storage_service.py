import os
import uuid
from pathlib import Path

from flask import current_app
from werkzeug.utils import secure_filename


ALLOWED_EXTENSIONS = {
    ".nii",
    ".nii.gz",
    ".png",
    ".jpg",
    ".jpeg",
    ".bmp",
    ".tif",
    ".tiff",
}


def is_allowed_file(filename: str) -> bool:
    name = filename.lower()
    if name.endswith(".nii.gz"):
        return True
    return Path(name).suffix in ALLOWED_EXTENSIONS


def save_upload(file_storage, subfolder: str = "") -> str:
    filename = secure_filename(file_storage.filename or "")
    if not filename:
        raise ValueError("Invalid file name.")
    if not is_allowed_file(filename):
        raise ValueError("Unsupported file type.")

    output_dir = Path(current_app.config["UPLOAD_FOLDER"]) / subfolder
    output_dir.mkdir(parents=True, exist_ok=True)

    unique_name = f"{uuid.uuid4().hex}_{filename}"
    output_path = output_dir / unique_name
    file_storage.save(str(output_path))
    return str(output_path)


def create_result_dir(job_id: int) -> str:
    result_dir = Path(current_app.config["RESULTS_FOLDER"]) / f"job_{job_id}"
    result_dir.mkdir(parents=True, exist_ok=True)
    return str(result_dir)


def to_public_path(abs_path: str) -> str:
    results_folder = os.path.abspath(current_app.config["RESULTS_FOLDER"])
    abs_norm = os.path.abspath(abs_path)
    rel = os.path.relpath(abs_norm, results_folder)
    return f"/results/files/{rel.replace(os.sep, '/')}"

