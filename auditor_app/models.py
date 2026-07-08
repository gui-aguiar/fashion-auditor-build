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


# ------------------------------------------------------------------ pt-BR labels
# The UI shows Portuguese labels; exports keep the CANONICAL values (stable for the
# pipeline) plus companion *_label columns with the Portuguese text.
LABELS_PT: Dict[str, Dict[str, str]] = {
    "reviewed_product_type": {"vestido": "Vestido", "macacao": "Macacão",
                              "outro": "Outro", "unknown": "Não sei"},
    "reviewed_comprimento": {"curto": "Curto", "midi": "Midi", "longo": "Longo",
                             "nao_avaliavel": "Não avaliável pela imagem",
                             "unknown": "Não sei"},
    "reviewed_fit": {"justo": "Justo", "amplo": "Amplo",
                     "nao_avaliavel": "Não avaliável pela imagem",
                     "unknown": "Não sei"},
    "review_status": {"reviewed": "Revisado", "skip": "Pular por enquanto",
                      "doubt": "Dúvida", "duplicate": "Duplicado",
                      "bad_images": "Imagens ruins/insuficientes"},
    "image_view_type": {"full_body": "Corpo inteiro", "cropped": "Cortada",
                        "detail": "Detalhe", "back": "Costas",
                        "flat_lay": "Produto sem modelo (flat lay)",
                        "unknown": "Não sei"},
    "image_quality": {"good": "Boa", "ok": "Ok", "bad": "Ruim",
                      "insufficient": "Insuficiente"},
    "usable_for_comprimento": {"yes": "Sim", "no": "Não", "unknown": "Não sei"},
    "usable_for_fit": {"yes": "Sim", "no": "Não", "unknown": "Não sei"},
    "usable_for_future_attributes": {"yes": "Sim", "no": "Não", "unknown": "Não sei"},
}


def to_label(field: str, value: Optional[str]) -> str:
    """Canonical value -> Portuguese UI label ('' stays '')."""
    if value in (None, ""):
        return ""
    return LABELS_PT.get(field, {}).get(value, str(value))


def from_label(field: str, label: Optional[str]) -> str:
    """Portuguese UI label -> canonical value ('' stays ''; unknown labels pass through)."""
    if label in (None, ""):
        return ""
    for canonical, portuguese in LABELS_PT.get(field, {}).items():
        if portuguese == label:
            return canonical
    return str(label)


def labels_for(field: str) -> list:
    return list(LABELS_PT.get(field, {}).values())


def initial_field_values(item: dict, review: dict) -> Dict[str, str]:
    """What the review combos should show when an item loads (CANONICAL values).

    Rule: a value the auditor already saved ALWAYS wins; otherwise the model
    suggestion (or the detected product_type) pre-fills the field, so the auditor
    only changes what they disagree with. review_status is never auto-suggested."""
    review = review or {}

    def saved_or(field: str, suggestion) -> str:
        saved = review.get(field) or ""
        if saved:
            return saved
        if suggestion and is_valid(field, str(suggestion)):
            return str(suggestion)
        return ""

    suggested_type = item.get("suggested_product_type") or (
        item.get("product_type")
        if item.get("product_type") in LABELS_PT["reviewed_product_type"] else None)
    return {
        "reviewed_product_type": saved_or("reviewed_product_type", suggested_type),
        "reviewed_comprimento": saved_or("reviewed_comprimento",
                                         item.get("suggested_comprimento")),
        "reviewed_fit": saved_or("reviewed_fit", item.get("suggested_fit")),
        "review_status": review.get("review_status") or "",
    }


HELP_TEXT_PT = """O QUE SIGNIFICA CADA OPÇÃO?

• "Outro" — você TEM certeza de que a peça não é vestido nem macacão
  (é outro tipo de roupa/produto).

• "Não sei" — você não conseguiu identificar com segurança.

• "Não avaliável pela imagem" — o atributo existe, mas a foto não permite
  julgar. Ex.: a imagem é cortada e não mostra a barra do vestido, então o
  comprimento não é avaliável.

• "Imagens ruins/insuficientes" (status) — problema geral do conjunto de fotos
  do produto (borradas, só detalhes, não dá para revisar nada).

• "Dúvida" (status) — você tem uma hipótese, mas não tem certeza.
  Escreva sua hipótese em "Observações da peça".

DICA: os campos já vêm preenchidos com a SUGESTÃO do modelo (quando existe).
Confira olhando a foto e corrija o que discordar — a palavra final é sua.

IMAGEM: por padrão a foto é ajustada para caber inteira na janela
("Ajustar à janela"). Use "Tamanho real" para ver em 100% com barras de
rolagem."""


def empty_image_review() -> dict:
    return {"image_view_type": "", "image_quality": "",
            "usable_for_comprimento": "", "usable_for_fit": "",
            "usable_for_future_attributes": "", "image_review_notes": ""}


def empty_product_review() -> dict:
    return {"reviewed_product_type": "", "reviewed_comprimento": "",
            "reviewed_fit": "", "review_status": "", "review_notes": "",
            "reviewed_at": "", "images": {}}
