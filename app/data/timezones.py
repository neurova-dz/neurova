"""IANA time zone identifiers (tz database) for clinic settings."""

from __future__ import annotations

from zoneinfo import available_timezones

# Algeria — canonical Zone ID in the IANA Time Zone Database.
DEFAULT_CLINIC_TIMEZONE = "Africa/Algiers"

_IANA: frozenset[str] = available_timezones()
IANA_TIMEZONES_SORTED: tuple[str, ...] = tuple(sorted(_IANA))


def timezone_choices(*, current: str | None) -> list[str]:
    """Sorted IANA zones, including ``current`` if it is set but not in the registry."""
    cur = (current or "").strip()
    if not cur or cur in _IANA:
        return list(IANA_TIMEZONES_SORTED)
    return sorted(_IANA | {cur})


def is_valid_timezone(name: str) -> bool:
    return name.strip() in _IANA
