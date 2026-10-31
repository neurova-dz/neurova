"""Security primitives: role decorators, tenancy guards."""

from app.security.decorators import role_required, same_clinic_required


__all__ = ["role_required", "same_clinic_required"]
