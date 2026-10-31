"""Role-aware sidebar navigation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import List


@dataclass
class NavItem:
    label: str
    endpoint: str | None
    href: str | None = None
    icon: str = "dot"
    active_endpoints: tuple[str, ...] = ()
    section: str = "main"


_DOCTOR_NAV = [
    NavItem("Dashboard", "doctor.dashboard", icon="home", active_endpoints=("doctor.dashboard",)),
    NavItem("My patients", "doctor.patients", icon="users",
            active_endpoints=(
                "doctor.patients",
                "doctor.patient_new",
                "doctor.patient_detail",
                "patients.patient_new",
                "patients.list_patients",
                "patients.view_patient",
            )),
    NavItem("Worklist", "doctor.worklist", icon="queue", active_endpoints=("doctor.worklist",)),
    NavItem("Notifications", "notifications.inbox", icon="bell",
            active_endpoints=("notifications.inbox",)),
    NavItem("Resources", "site.resources", icon="book",
            active_endpoints=("site.resources",)),
    NavItem("Profile", "doctor.profile", icon="user",
            active_endpoints=("doctor.profile",)),
    NavItem("Settings", "doctor.settings", icon="cog",
            active_endpoints=("doctor.settings",)),
]


_CLINIC_ADMIN_NAV = [
    NavItem("Overview", "clinic.overview", icon="home",
            active_endpoints=("clinic.overview",)),
    NavItem("Doctors", "clinic.doctors_list", icon="users",
            active_endpoints=("clinic.doctors_list", "clinic.doctor_detail",
                              "clinic.doctor_new")),
    NavItem("Patients", "clinic.patients_list", icon="folder",
            active_endpoints=("clinic.patients_list", "clinic.patient_detail",
                              "clinic.patient_new")),
    NavItem("Cases", "clinic.cases_board", icon="queue",
            active_endpoints=("clinic.cases_board",)),
    NavItem("Settings", "clinic.settings", icon="cog",
            active_endpoints=("clinic.settings",)),
]


_SUPERADMIN_NAV = [
    NavItem("Overview", "admin.overview", icon="home",
            active_endpoints=("admin.overview",)),
    NavItem("Clinics", "admin.clinics_list", icon="building",
            active_endpoints=("admin.clinics_list", "admin.clinic_detail",
                              "admin.clinic_new")),
    NavItem("Doctors", "admin.doctors_list", icon="users",
            active_endpoints=("admin.doctors_list",)),
    NavItem("Analyses", "admin.jobs_list", icon="queue",
            active_endpoints=("admin.jobs_list",)),
    NavItem("Audit", "admin.audit", icon="activity",
            active_endpoints=("admin.audit",)),
    NavItem("System", "admin.system", icon="cog",
            active_endpoints=("admin.system",)),
]


def nav_items_for(user) -> List[NavItem]:
    if user is None or not getattr(user, "is_authenticated", False):
        return []
    if getattr(user, "is_superadmin", False):
        return list(_SUPERADMIN_NAV)
    if getattr(user, "is_clinic_admin", False):
        return list(_CLINIC_ADMIN_NAV)
    return list(_DOCTOR_NAV)


def role_label(user) -> str:
    if not user or not getattr(user, "is_authenticated", False):
        return ""
    if getattr(user, "is_superadmin", False):
        return "Superadmin"
    if getattr(user, "is_clinic_admin", False):
        return "Clinic admin"
    return "Doctor"
