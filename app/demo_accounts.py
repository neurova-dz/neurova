"""Seeded demo logins; must match ``h2a3b4c5d6e7_seed_superadmin_clinic_admin``."""

from __future__ import annotations

# tuple[dict, ...] for stable ordering on the login page
DEMO_LOGIN_ACCOUNTS: tuple[dict[str, str], ...] = (
    {
        "key": "superadmin",
        "label": "Superadmin",
        "email": "superadmin@neurova.dev",
        "password": "Superadmin123!",
    },
    {
        "key": "clinic_admin",
        "label": "Clinic admin",
        "email": "admin@neurova.dev",
        "password": "Admin123!",
    },
    {
        "key": "doctor",
        "label": "Doctor",
        "email": "doctor@neurova.dev",
        "password": "Doctor123!",
    },
)
