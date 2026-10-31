"""One-shot script to align legacy ``tumor_volume_*`` keys with the new
``lesion_volume_*`` naming used by ``clinical_report_service``.

Usage::

    python -m scripts.migrate_report_keys
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from app import create_app  # noqa: E402
from app.extensions import db  # noqa: E402
from app.models.medical import InferenceResult  # noqa: E402


KEY_RENAMES = {
    "tumor_volume_mm3": "lesion_volume_mm3",
    "tumor_volume_cm3": "lesion_volume_cc",
}


def _walk(obj):
    """Recursively rename keys in nested dicts/lists."""
    if isinstance(obj, dict):
        new = {}
        for k, v in obj.items():
            target_key = KEY_RENAMES.get(k, k)
            new[target_key] = _walk(v)
        return new
    if isinstance(obj, list):
        return [_walk(x) for x in obj]
    return obj


def main() -> int:
    app = create_app()
    with app.app_context():
        rows = InferenceResult.query.all()
        changed = 0
        for r in rows:
            payload = r.report_json
            if not isinstance(payload, dict):
                continue
            new_payload = _walk(payload)
            if new_payload != payload:
                r.report_json = new_payload
                changed += 1
        if changed:
            db.session.commit()
        print(f"Migrated {changed} inference_results rows.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
