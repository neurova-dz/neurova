"""Server-side PDF rendering for completed inference jobs.

Falls back to a print-friendly HTML response when ``weasyprint`` is unavailable
(common on Windows without the GTK toolchain).
"""

from __future__ import annotations

from io import BytesIO

from flask import Response, render_template


def render_job_pdf(job, result, clinical_summary, helper_block) -> Response:
    html = render_template(
        "results/pdf.html",
        job=job,
        result=result,
        clinical_summary=clinical_summary,
        helper_block=helper_block,
    )
    try:
        from weasyprint import HTML

        pdf_bytes = HTML(string=html).write_pdf()
        resp = Response(pdf_bytes, mimetype="application/pdf")
        resp.headers["Content-Disposition"] = (
            f'attachment; filename="neurova-report-{job.id}.pdf"'
        )
        return resp
    except Exception:
        # Graceful fallback: return print-ready HTML
        resp = Response(html, mimetype="text/html")
        resp.headers["Content-Disposition"] = (
            f'inline; filename="neurova-report-{job.id}.html"'
        )
        return resp
