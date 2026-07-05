"""Schemas and enums for the offline human-audit app (v0).

The vocabulary is deliberately future-proof (batches, collections, per-image
usability flags) even though the v0 UI is minimal — see the project README.
"""
from __future__ import annotations

from typing import Dict, List, Optional

SCHEMA_VERSION = 1

REVIEWED_PRODUCT_TYPES = ["vestido", "macacao", "outro", "unknown"]
REVIEWED_COMPRIMENTO = ["curto", "midi", "longo", "nao_avaliavel", "unknown"]
REVIEWED_FIT = ["justo", "amplo", "nao_avaliavel", "unknown"]
REVIEW_STATUSES = ["reviewed", "skip", "doubt", "duplicate", "bad_images"]

IMAGE_VIEW_TYPES = ["full_body", "cropped", "detail", "back", "flat_lay", "unknown"]
IMAGE_QUALITIES = ["good", "ok", "bad", "insufficient"]
YES_NO_UNKNOWN = ["yes", "no", "unknown"]

ENUMS: Dict[str, List[str]] = {
    "reviewed_product_type": REVIEWED_PRODUCT_TYPES,
    "reviewed_comprimento": REVIEWED_COMPRIMENTO,
    "reviewed_fit": REVIEWED_FIT,
    "review_status": REVIEW_STATUSES,
    "image_view_type": IMAGE_VIEW_TYPES,
    "image_quality": IMAGE_QUALITIES,
    "usable_for_comprimento": YES_NO_UNKNOWN,
    "usable_for_fit": YES_NO_UNKNOWN,
    "usable_for_future_attributes": YES_NO_UNKNOWN,
}


def is_valid(field: str, value: Optional[str]) -> bool:
    """'' (still pending) is always acceptable; otherwise the value must belong
    to the field's vocabulary. Unknown fields are free-text (notes etc.)."""
    if value in (None, ""):
        return True
    allowed = ENUMS.get(field)
    return True if allowed is None else value in allowed


def evaluable(reviewed_value: Optional[str]) -> str:
    """Derive comprimento_evaluable / fit_evaluable from the reviewed label:
    a real label -> yes; explicit 'nao_avaliavel' -> no; anything else -> unknown."""
    if reviewed_value in ("curto", "midi", "longo", "justo", "amplo"):
        return "yes"
    if reviewed_value == "nao_avaliavel":
        return "no"
    return "unknown"


def empty_image_review() -> dict:
    return {"image_view_type": "", "image_quality": "",
            "usable_for_comprimento": "", "usable_for_fit": "",
            "usable_for_future_attributes": "", "image_review_notes": ""}


def empty_product_review() -> dict:
    return {"reviewed_product_type": "", "reviewed_comprimento": "",
            "reviewed_fit": "", "review_status": "", "review_notes": "",
            "reviewed_at": "", "images": {}}
