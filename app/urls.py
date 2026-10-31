"""Central URL helpers for templates and redirects.

Templates should use :func:`nv_site` for named app nav targets (pipeline, activity, resources).
Optional ``url_for`` fallbacks keep links working if the URL map is stale (e.g. dev server without reload).
"""

from __future__ import annotations

from urllib.parse import urlencode

from flask import Flask, request, url_for
from werkzeug.routing.exceptions import BuildError

# Logical nav keys → (Flask endpoint, path under SCRIPT_NAME root)
SITE_NAV: dict[str, tuple[str, str]] = {
    "pipeline": ("site.pipeline", "/pipeline"),
    "activity": ("site.activity", "/activity"),
    "resources": ("site.resources", "/resources"),
}


def build_nv_site_url(page: str, **kwargs) -> str:
    pair = SITE_NAV.get(page)
    if not pair:
        return "#"
    endpoint, fallback = pair
    try:
        return url_for(endpoint, **kwargs)
    except BuildError:
        try:
            root = (request.script_root or "").rstrip("/")
        except RuntimeError:
            root = ""
        path = (root + fallback).replace("//", "/") if root else fallback
        if kwargs:
            return f"{path}?{urlencode(kwargs)}"
        return path


def register_url_helpers(app: Flask) -> None:
    """Bind ``nv_site`` on the app Jinja environment (``add_template_global``, not only ``@template_global``)."""
    app.add_template_global(build_nv_site_url, "nv_site")
