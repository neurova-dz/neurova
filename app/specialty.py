"""Map doctor.specialty string to a constrained workflow for UI and defaults."""


def normalize_doctor_specialty(raw: str | None) -> str | None:
    if not raw:
        return None
    s = raw.strip().lower().replace(" ", "_").replace("-", "_")
    if s in ("diabetic_retinopathy", "retinopathy", "dr", "eye"):
        return "diabetic_retinopathy"
    if s in ("brain_tumor", "braintumor", "neuro_oncology", "neuro"):
        return "brain_tumor"
    if "retino" in s or "fundus" in s:
        return "diabetic_retinopathy"
    if "tumor" in s or "brain" in s or "mri" in s:
        return "brain_tumor"
    return None
