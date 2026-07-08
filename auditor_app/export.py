"""Export the audit results: reviewed_results.{csv,jsonl} (one row per product,
with aggregated image_01/image_02 columns) + reviewed_images.csv (one row per
image) + optional final snapshot and zip. GUI-free and covered by offline tests.

Writers are local (csv/json stdlib) so the auditor app has ZERO dependency on the
rest of the pipeline — required for PyInstaller onefile packaging.
"""
from __future__ import annotations

import csv
import datetime
import json
import os
import zipfile
from typing import Dict, List, Optional, Tuple

from . import models

_IMAGE_AGG_SUFFIXES = ["path", "view_type", "quality", "usable_for_comprimento",
                       "usable_for_fit", "usable_for_future_attributes", "notes"]

RESULT_FIELDS = (
    ["review_batch_id", "record_origin", "source_site", "source_url",
     "collection_or_source", "product_id", "canonical_slug", "product_title",
     "product_url", "product_type",
     "suggested_comprimento", "suggested_comprimento_confidence",
     "suggested_fit", "suggested_fit_confidence",
     "suggested_needs_review", "suggested_joint_confidence", "suggestion_source",
     "reviewed_product_type", "reviewed_comprimento", "reviewed_fit",
     "reviewed_product_type_label", "reviewed_comprimento_label",
     "reviewed_fit_label", "review_status_label",
     "comprimento_evaluable", "fit_evaluable",
     "review_status", "review_notes", "reviewed_by", "reviewed_at",
     "manual_import", "manual_imported_at", "original_import_paths",
     "price", "original_price", "discount_percentage",
     "image_count", "image_paths", "image_urls"]
    + [f"image_01_{s}" for s in _IMAGE_AGG_SUFFIXES]
    + [f"image_02_{s}" for s in _IMAGE_AGG_SUFFIXES]
)

# canonical values stay the pipeline contract; *_label columns carry the pt-BR text
IMAGE_FIELDS = ["review_batch_id", "record_origin", "product_id", "image_index",
                "image_path", "image_url", "original_import_path",
                "image_view_type", "image_quality",
                "usable_for_comprimento", "usable_for_fit",
                "usable_for_future_attributes",
                "image_view_type_label", "image_quality_label",
                "usable_for_comprimento_label", "usable_for_fit_label",
                "usable_for_future_attributes_label",
                "image_review_notes", "reviewed_at"]


def _write_csv(path: str, fieldnames: List[str], rows: List[dict]) -> str:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    return path


def _write_jsonl(path: str, rows: List[dict]) -> str:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    return path


def _result_row(item: dict, review: dict, batch_id: str, reviewer: str) -> dict:
    image_paths = item.get("image_paths") or []
    image_urls = item.get("image_urls") or []
    row = {
        "review_batch_id": batch_id,
        "record_origin": item.get("record_origin") or "review_queue",
        "source_site": item.get("source_site"),
        "source_url": item.get("source_url"),
        "collection_or_source": item.get("collection_or_source"),
        "product_id": item.get("product_id"),
        "canonical_slug": item.get("canonical_slug"),
        "product_title": item.get("product_title"),
        "product_url": item.get("product_url"),
        "product_type": item.get("product_type"),
        "suggested_comprimento": item.get("suggested_comprimento"),
        "suggested_comprimento_confidence": item.get("suggested_comprimento_confidence"),
        "suggested_fit": item.get("suggested_fit"),
        "suggested_fit_confidence": item.get("suggested_fit_confidence"),
        "suggested_needs_review": item.get("suggested_needs_review"),
        "suggested_joint_confidence": item.get("suggested_joint_confidence"),
        "suggestion_source": item.get("suggestion_source"),
        "reviewed_product_type": review.get("reviewed_product_type", ""),
        "price": item.get("price"),
        "original_price": item.get("original_price"),
        "discount_percentage": item.get("discount_percentage"),
        "image_count": len(image_paths),
        "image_paths": ";".join(image_paths),
        "image_urls": ";".join(image_urls),
        "reviewed_comprimento": review.get("reviewed_comprimento", ""),
        "reviewed_fit": review.get("reviewed_fit", ""),
        "reviewed_product_type_label": models.to_label(
            "reviewed_product_type", review.get("reviewed_product_type", "")),
        "reviewed_comprimento_label": models.to_label(
            "reviewed_comprimento", review.get("reviewed_comprimento", "")),
        "reviewed_fit_label": models.to_label("reviewed_fit", review.get("reviewed_fit", "")),
        "review_status_label": models.to_label("review_status",
                                               review.get("review_status", "")),
        "comprimento_evaluable": models.evaluable(review.get("reviewed_comprimento")),
        "fit_evaluable": models.evaluable(review.get("reviewed_fit")),
        "review_status": review.get("review_status", ""),
        "review_notes": review.get("review_notes", ""),
        "reviewed_by": reviewer,
        "reviewed_at": review.get("reviewed_at", ""),
        "manual_import": bool(item.get("manual_import")),
        "manual_imported_at": item.get("manual_imported_at") or "",
        "original_import_paths": ";".join(item.get("original_import_paths") or []),
    }
    for index in (1, 2):
        image_review = (review.get("images") or {}).get(str(index)) or models.empty_image_review()
        prefix = f"image_{index:02d}_"
        row[prefix + "path"] = image_paths[index - 1] if len(image_paths) >= index else ""
        row[prefix + "view_type"] = image_review.get("image_view_type", "")
        row[prefix + "quality"] = image_review.get("image_quality", "")
        row[prefix + "usable_for_comprimento"] = image_review.get("usable_for_comprimento", "")
        row[prefix + "usable_for_fit"] = image_review.get("usable_for_fit", "")
        row[prefix + "usable_for_future_attributes"] = \
            image_review.get("usable_for_future_attributes", "")
        row[prefix + "notes"] = image_review.get("image_review_notes", "")
    return row


def _image_rows(item: dict, review: dict, batch_id: str) -> List[dict]:
    rows = []
    image_paths = item.get("image_paths") or []
    image_urls = item.get("image_urls") or []
    originals = item.get("original_import_paths") or item.get("original_image_paths") or []
    for index, path in enumerate(image_paths, start=1):
        image_review = (review.get("images") or {}).get(str(index)) or models.empty_image_review()
        rows.append({
            "review_batch_id": batch_id,
            "record_origin": item.get("record_origin") or "review_queue",
            "product_id": item.get("product_id"),
            "image_index": index,
            "image_path": path,
            "image_url": image_urls[index - 1] if len(image_urls) >= index else "",
            "original_import_path": originals[index - 1] if len(originals) >= index else "",
            "image_view_type": image_review.get("image_view_type", ""),
            "image_quality": image_review.get("image_quality", ""),
            "usable_for_comprimento": image_review.get("usable_for_comprimento", ""),
            "usable_for_fit": image_review.get("usable_for_fit", ""),
            "usable_for_future_attributes": image_review.get("usable_for_future_attributes", ""),
            "image_view_type_label": models.to_label(
                "image_view_type", image_review.get("image_view_type", "")),
            "image_quality_label": models.to_label(
                "image_quality", image_review.get("image_quality", "")),
            "usable_for_comprimento_label": models.to_label(
                "usable_for_comprimento", image_review.get("usable_for_comprimento", "")),
            "usable_for_fit_label": models.to_label(
                "usable_for_fit", image_review.get("usable_for_fit", "")),
            "usable_for_future_attributes_label": models.to_label(
                "usable_for_future_attributes",
                image_review.get("usable_for_future_attributes", "")),
            "image_review_notes": image_review.get("image_review_notes", ""),
            "reviewed_at": review.get("reviewed_at", ""),
        })
    return rows


def export_results(items: List[dict], progress: dict, output_dir: str,
                   batch_id: str) -> Dict[str, str]:
    """Rewrite reviewed_results.{csv,jsonl} + reviewed_images.csv from the current
    progress (cheap at this scale; called on every save)."""
    reviewer = progress.get("reviewer", "")
    reviews = progress.get("reviews", {})
    result_rows, image_rows = [], []
    for item in items:
        review = reviews.get(item.get("product_id")) or models.empty_product_review()
        result_rows.append(_result_row(item, review, batch_id, reviewer))
        image_rows.extend(_image_rows(item, review, batch_id))
    return {
        "results_csv": _write_csv(os.path.join(output_dir, "reviewed_results.csv"),
                                  RESULT_FIELDS, result_rows),
        "results_jsonl": _write_jsonl(os.path.join(output_dir, "reviewed_results.jsonl"),
                                      result_rows),
        "images_csv": _write_csv(os.path.join(output_dir, "reviewed_images.csv"),
                                 IMAGE_FIELDS, image_rows),
    }


def export_final(items: List[dict], progress: dict, output_dir: str,
                 batch_id: str) -> Dict[str, str]:
    """Final snapshot: *_final.{csv,jsonl} + a single zip the auditor sends back."""
    paths = export_results(items, progress, output_dir, batch_id)
    stamp = datetime.datetime.now().astimezone().isoformat(timespec="seconds")
    final_csv = os.path.join(output_dir, "reviewed_results_final.csv")
    final_jsonl = os.path.join(output_dir, "reviewed_results_final.jsonl")
    with open(paths["results_csv"], encoding="utf-8") as src, \
            open(final_csv, "w", encoding="utf-8") as dst:
        dst.write(src.read())
    with open(paths["results_jsonl"], encoding="utf-8") as src, \
            open(final_jsonl, "w", encoding="utf-8") as dst:
        dst.write(src.read())
    zip_path = os.path.join(output_dir, "reviewed_results_package.zip")
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for name in ("reviewed_results_final.csv", "reviewed_results_final.jsonl",
                     "reviewed_results.csv", "reviewed_results.jsonl",
                     "reviewed_images.csv", "review_progress.json"):
            full = os.path.join(output_dir, name)
            if os.path.exists(full):
                zf.write(full, arcname=name)
        zf.writestr("EXPORT_INFO.txt",
                    f"batch: {batch_id}\nexported_at: {stamp}\n"
                    f"reviewer: {progress.get('reviewer', '')}\n")
    return {**paths, "final_csv": final_csv, "final_jsonl": final_jsonl,
            "zip": zip_path}
