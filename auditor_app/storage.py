"""Package loading + progress persistence for the auditor app (GUI-free, testable).

A package directory looks like:
    <package>/package_manifest.json
    <package>/data/review_items.jsonl     (canonical item list)
    <package>/data/review_items.csv       (same rows, for humans/Excel)
    <package>/data/images/...             (copied images, relative paths)
    <package>/output/                     (progress + exported results live here)
"""
from __future__ import annotations

import datetime
import json
import os
from typing import Dict, List, Optional

from . import models

PROGRESS_FILENAME = "review_progress.json"


def _now_iso() -> str:
    return datetime.datetime.now().astimezone().isoformat(timespec="seconds")


class AuditorPackage:
    def __init__(self, package_dir: str):
        self.package_dir = os.path.abspath(package_dir)
        manifest_path = os.path.join(self.package_dir, "package_manifest.json")
        items_path = os.path.join(self.package_dir, "data", "review_items.jsonl")
        if not os.path.exists(items_path):
            raise FileNotFoundError(
                f"review_items.jsonl not found under {self.package_dir!r} — "
                "is this an auditor package directory?")
        self.manifest: dict = {}
        if os.path.exists(manifest_path):
            with open(manifest_path, encoding="utf-8") as fh:
                self.manifest = json.load(fh)
        with open(items_path, encoding="utf-8") as fh:
            self.items: List[dict] = [json.loads(line) for line in fh if line.strip()]
        self.manual_items_path = os.path.join(self.package_dir, "data",
                                              "manual_imports", "manual_items.jsonl")
        if os.path.exists(self.manual_items_path):
            with open(self.manual_items_path, encoding="utf-8") as fh:
                self.items.extend(json.loads(line) for line in fh if line.strip())
        self.output_dir = os.path.join(self.package_dir, "output")
        os.makedirs(self.output_dir, exist_ok=True)

    @property
    def batch_id(self) -> str:
        return self.manifest.get("review_batch_id") or os.path.basename(self.package_dir)

    def image_abs_path(self, relative: Optional[str]) -> Optional[str]:
        if not relative:
            return None
        return relative if os.path.isabs(relative) else os.path.join(self.package_dir, relative)

    def add_manual_item(self, source_image_paths: List[str], title: str = "") -> dict:
        """Auditor-added product: copies the chosen images into
        data/manual_imports/images/, creates a stable manual_<id> item, persists it
        to manual_items.jsonl and appends it to the in-memory item list."""
        import shutil
        import uuid
        images_dir = os.path.join(self.package_dir, "data", "manual_imports", "images")
        os.makedirs(images_dir, exist_ok=True)
        item_id = f"manual_{uuid.uuid4().hex[:10]}"
        image_paths, originals = [], []
        for index, source in enumerate(source_image_paths, start=1):
            if not os.path.exists(source):
                continue
            extension = os.path.splitext(source)[1].lower() or ".jpg"
            destination = os.path.join(images_dir, f"{item_id}_{index:02d}{extension}")
            shutil.copy2(source, destination)
            image_paths.append(os.path.relpath(destination, self.package_dir))
            originals.append(source)
        item = {
            "review_batch_id": self.batch_id,
            "record_origin": "manual_import",
            "manual_import": True,
            "manual_imported_at": _now_iso(),
            "original_import_paths": originals,
            "source_site": None, "source_url": None, "collection_or_source": None,
            "product_id": item_id, "canonical_slug": item_id,
            "product_title": title or "(item adicionado manualmente)",
            "product_url": None, "product_type": None, "duplicate_status": None,
            "matched_dataset_product_id": None, "matched_dataset_title": None,
            "matched_dataset_comprimento": None, "matched_dataset_fit": None,
            "price": None, "original_price": None, "discount_percentage": None,
            "suggested_comprimento": None, "suggested_comprimento_confidence": None,
            "suggested_fit": None, "suggested_fit_confidence": None,
            "suggested_needs_review": None, "suggested_joint_confidence": None,
            "suggestion_source": None,
            "image_paths": image_paths, "image_urls": [],
            "original_image_paths": originals,
        }
        os.makedirs(os.path.dirname(self.manual_items_path), exist_ok=True)
        with open(self.manual_items_path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(item, ensure_ascii=False) + "\n")
        self.items.append(item)
        return item


class ProgressStore:
    """review_progress.json: {'reviewer', 'current_index', 'reviews': {product_id: review}}.
    A review dict = models.empty_product_review() shape (images keyed by '1'/'2')."""

    def __init__(self, output_dir: str):
        self.path = os.path.join(output_dir, PROGRESS_FILENAME)

    def load(self) -> dict:
        if not os.path.exists(self.path):
            return {"reviewer": "", "current_index": 0, "reviews": {}}
        with open(self.path, encoding="utf-8") as fh:
            data = json.load(fh)
        data.setdefault("reviewer", "")
        data.setdefault("current_index", 0)
        data.setdefault("reviews", {})
        return data

    def save(self, data: dict) -> None:
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=1)
        os.replace(tmp, self.path)                          # atomic: never corrupt progress


def get_review(progress: dict, product_id: str) -> dict:
    """Return (creating if needed) the review dict for a product."""
    reviews: Dict[str, dict] = progress.setdefault("reviews", {})
    if product_id not in reviews:
        reviews[product_id] = models.empty_product_review()
    review = reviews[product_id]
    review.setdefault("images", {})
    return review


def item_status(review: Optional[dict]) -> str:
    """pendente | revisado | pular | dúvida | duplicado | imagens_ruins."""
    labels = {"reviewed": "revisado", "skip": "pular", "doubt": "dúvida",
              "duplicate": "duplicado", "bad_images": "imagens_ruins"}
    if not review:
        return "pendente"
    return labels.get(review.get("review_status") or "", "pendente")
