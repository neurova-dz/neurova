"""Compatibility shim — logic lives in ``clinical_advisory_service``.

Older code imported ``helper_for_job`` from this module. The implementation was
moved so MariaDB never sees PostgreSQL-only ``NULLS LAST`` in generated SQL.
Importing this module always delegates to ``clinical_advisory_service``.
"""

from __future__ import annotations

from app.services.clinical_advisory_service import (
    DEFAULT_THRESHOLDS,
    helper_for_brain,
    helper_for_job,
    helper_for_retina,
)

__all__ = [
    "DEFAULT_THRESHOLDS",
    "helper_for_brain",
    "helper_for_job",
    "helper_for_retina",
]
