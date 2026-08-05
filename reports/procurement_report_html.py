"""
HTML fragments for Procurement & Planning report export (category badges + table).
"""
from __future__ import annotations

from html import escape

from inventory.material_categories import ALL_MATERIAL_CATEGORIES

_CATEGORY_SLUGS = {name: name.upper().replace(" ", "-").replace("&", "AND") for name in ALL_MATERIAL_CATEGORIES}


def _svg_for_category(category_name: str) -> str:
    """Minimal outline icons (12×12) for PDF/print HTML."""
    slug = _CATEGORY_SLUGS.get(category_name, "OTHERS")
    icons = {
        "BUILDING-MATERIALS": (
            '<path d="M2 10V4l5-3 5 3v6"/>'
            '<path d="M4.5 10V7h3v3"/>'
            '<path d="M9.5 10V7h3v3"/>'
        ),
        "STEEL-AND-METAL": (
            '<path d="M14 2.5l-2 2"/>'
            '<path d="M8.5 6.5L11 4"/>'
            '<path d="M2 12l7-7 3 3-7 7H2z"/>'
        ),
        "PAINTS-AND-COATINGS": (
            '<path d="M3 4h8l-1 8H4L3 4z"/>'
            '<path d="M11 4h1.5a1.5 1.5 0 0 1 0 3H11"/>'
            '<path d="M6 8v4"/>'
        ),
        "FINISHING": (
            '<path d="M2 10l4-6 3 4 3-5 4 7"/>'
            '<path d="M2 10h10"/>'
        ),
        "PLUMBING": (
            '<path d="M7 2v2"/>'
            '<path d="M7 4a3 3 0 0 0-3 3v1a3 3 0 0 0 6 0V7a3 3 0 0 0-3-3z"/>'
            '<path d="M7 11v1"/>'
        ),
        "ELECTRICAL": (
            '<path d="M8 2L4 8h3l-1 4 5-6H8l1-4z"/>'
        ),
        "OTHERS": (
            '<path d="M2 4h8v6H2z"/>'
            '<path d="M4 4V3a1 1 0 0 1 1-1h2a1 1 0 0 1 1 1v1"/>'
        ),
    }
    paths = icons.get(slug, icons["OTHERS"])
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" '
        f'viewBox="0 0 14 14" fill="none" stroke="currentColor" '
        f'stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round" '
        f'aria-hidden="true">{paths}</svg>'
    )


def render_category_badge_html(category_name: str) -> str:
    label = escape(category_name or "Others")
    icon = _svg_for_category(category_name or "Others")
    return (
        f'<span class="category-badge">{icon}'
        f'<span>{label}</span></span>'
    )


PROCUREMENT_REPORT_STYLES = """
.category-badge {
  background-color: #1e232d;
  border: 1px solid #2e3644;
  color: #e2e8f0;
  border-radius: 6px;
  font-size: 10px;
  font-weight: 600;
  padding: 2px 8px;
  text-transform: uppercase;
  display: inline-flex;
  align-items: center;
  gap: 4px;
}
.pp-report-table { width: 100%; border-collapse: collapse; font-size: 11px; }
.pp-report-table th, .pp-report-table td {
  border: 1px solid #2e3644;
  padding: 6px 8px;
  text-align: left;
  color: #e2e8f0;
}
.pp-report-table th { background: #18181b; color: #f97316; text-transform: uppercase; font-size: 10px; }
.pp-report-table tbody tr { background: #27272a; }
.pp-report-table tbody tr:nth-child(even) { background: #1f1f23; }
"""
