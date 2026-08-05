"""
Intelligent material category resolution for StockPad.

Explicit categories stored on Material.category are honored when set and not
Uncategorized. Otherwise categories are inferred from material name keywords.
"""
from __future__ import annotations

from dataclasses import dataclass

CATEGORY_BUILDING = "Building Materials"
CATEGORY_STEEL = "Steel & Metal"
CATEGORY_PAINTS = "Paints & Coatings"
CATEGORY_FINISHING = "Finishing"
CATEGORY_PLUMBING = "Plumbing"
CATEGORY_ELECTRICAL = "Electrical"
CATEGORY_OTHERS = "Others"

UNCATEGORIZED_LABELS = frozenset(
    {
        "",
        "uncategorized",
        "general supplies",
        "general",
        "other",
        "others",
    }
)

ALL_MATERIAL_CATEGORIES: tuple[str, ...] = (
    CATEGORY_BUILDING,
    CATEGORY_STEEL,
    CATEGORY_PAINTS,
    CATEGORY_FINISHING,
    CATEGORY_PLUMBING,
    CATEGORY_ELECTRICAL,
    CATEGORY_OTHERS,
)

CATEGORY_NAME_TO_ID: dict[str, int] = {
    CATEGORY_BUILDING: 1,
    CATEGORY_STEEL: 2,
    CATEGORY_PAINTS: 3,
    CATEGORY_FINISHING: 4,
    CATEGORY_PLUMBING: 5,
    CATEGORY_ELECTRICAL: 6,
    CATEGORY_OTHERS: 7,
}


@dataclass(frozen=True)
class _KeywordRule:
    category: str
    keywords: tuple[str, ...]


# First match wins — more specific groups before broad ones (e.g. electrical before wire in metal).
_KEYWORD_RULES: tuple[_KeywordRule, ...] = (
    _KeywordRule(
        CATEGORY_BUILDING,
        ("cement", "sand", "brick", "concrete", "plaster", "gravel"),
    ),
    _KeywordRule(
        CATEGORY_PAINTS,
        ("paint", "primer", "varnish", "epoxy", "coating", "thinner"),
    ),
    _KeywordRule(
        CATEGORY_FINISHING,
        ("foam", "wood", "veneer", "laminate", "tile", "fabric", "leather"),
    ),
    _KeywordRule(
        CATEGORY_PLUMBING,
        ("pipe", "faucet", "valve", "pvc", "fitting", "tube"),
    ),
    _KeywordRule(
        CATEGORY_ELECTRICAL,
        ("cable", "switch", "breaker", "led", "socket", "copper"),
    ),
    _KeywordRule(
        CATEGORY_STEEL,
        ("iron", "steel", "rod", "bolt", "screw", "wire", "aluminum", "metal", "plate"),
    ),
)


def _normalize_text(value: str | None) -> str:
    return (value or "").strip()


def is_uncategorized_category(value: str | None) -> bool:
    normalized = _normalize_text(value).lower()
    return normalized in UNCATEGORIZED_LABELS


def infer_category_from_name(name: str | None) -> str:
    """Keyword-based fallback when no explicit category is assigned."""
    haystack = _normalize_text(name).lower()
    if not haystack:
        return CATEGORY_OTHERS

    for rule in _KEYWORD_RULES:
        for keyword in rule.keywords:
            if keyword in haystack:
                return rule.category

    return CATEGORY_OTHERS


def resolve_material_category_name(*, name: str | None, explicit_category: str | None = None) -> str:
    if not is_uncategorized_category(explicit_category):
        return _normalize_text(explicit_category)
    return infer_category_from_name(name)


def resolve_material_category_payload(*, name: str | None, explicit_category: str | None = None) -> dict:
    category_name = resolve_material_category_name(
        name=name,
        explicit_category=explicit_category,
    )
    return {
        "id": CATEGORY_NAME_TO_ID.get(category_name, CATEGORY_NAME_TO_ID[CATEGORY_OTHERS]),
        "name": category_name,
    }


def resolve_material_category_for_instance(material) -> tuple[dict, str]:
    explicit = getattr(material, "category", None)
    name = getattr(material, "name", None)
    payload = resolve_material_category_payload(name=name, explicit_category=explicit)
    return payload, payload["name"]
