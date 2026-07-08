"""Offline tests for the FashionAuditor build (no GUI, no network).

Run:  python -m unittest discover tests -v
"""
from __future__ import annotations

import csv
import json
import os
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from auditor_app import export, image_utils, models, storage  # noqa: E402

ITEM = {
    "review_batch_id": "b1", "record_origin": "crawled",
    "source_site": "lancaperfume", "source_url": "https://s/colecao",
    "collection_or_source": "productClusterIds:3122",
    "product_id": "vestido-x-502ve1", "canonical_slug": "vestido-x-502ve1",
    "product_title": "Vestido X", "product_url": "https://s/vestido-x-502ve1/p",
    "product_type": "vestido",
    "suggested_comprimento": "longo", "suggested_comprimento_confidence": 0.91,
    "suggested_fit": "justo", "suggested_fit_confidence": 0.77,
    "suggested_needs_review": False, "suggested_joint_confidence": 0.7,
    "suggestion_source": "local_vestidos_v0_calibrated",
    "price": 100.0, "original_price": 200.0, "discount_percentage": 50.0,
    "image_paths": ["data/images/x_01.jpg", "data/images/x_02.jpg"],
    "image_urls": ["https://cdn/1.jpg", "https://cdn/2.jpg"],
    "original_image_paths": ["a/x_01.jpg", "a/x_02.jpg"],
    "manual_import": False, "manual_imported_at": None, "original_import_paths": [],
}


class TestSuggestionDefaults(unittest.TestCase):
    def test_new_item_prefilled_from_suggestion(self):
        initial = models.initial_field_values(ITEM, models.empty_product_review())
        self.assertEqual(initial["reviewed_comprimento"], "longo")
        self.assertEqual(initial["reviewed_fit"], "justo")
        self.assertEqual(initial["reviewed_product_type"], "vestido")  # from product_type
        self.assertEqual(initial["review_status"], "")                 # never suggested

    def test_saved_review_is_never_overwritten(self):
        review = dict(models.empty_product_review(),
                      reviewed_comprimento="curto", reviewed_fit="nao_avaliavel",
                      reviewed_product_type="outro", review_status="doubt")
        initial = models.initial_field_values(ITEM, review)
        self.assertEqual(initial["reviewed_comprimento"], "curto")     # saved wins
        self.assertEqual(initial["reviewed_fit"], "nao_avaliavel")
        self.assertEqual(initial["reviewed_product_type"], "outro")
        self.assertEqual(initial["review_status"], "doubt")

    def test_invalid_suggestion_is_ignored(self):
        weird = dict(ITEM, suggested_comprimento="gigante")
        initial = models.initial_field_values(weird, models.empty_product_review())
        self.assertEqual(initial["reviewed_comprimento"], "")

    def test_no_suggestion_stays_blank(self):
        bare = dict(ITEM, suggested_comprimento=None, suggested_fit=None,
                    product_type="unknown")
        initial = models.initial_field_values(bare, models.empty_product_review())
        self.assertEqual(initial["reviewed_comprimento"], "")
        self.assertEqual(initial["reviewed_product_type"], "unknown")  # valid enum value


class TestLabels(unittest.TestCase):
    def test_roundtrip_for_every_enum_value(self):
        for field, mapping in models.LABELS_PT.items():
            for canonical, portuguese in mapping.items():
                self.assertEqual(models.to_label(field, canonical), portuguese)
                self.assertEqual(models.from_label(field, portuguese), canonical)
        self.assertEqual(models.to_label("reviewed_fit", ""), "")
        self.assertEqual(models.from_label("reviewed_fit", ""), "")

    def test_expected_portuguese_labels(self):
        self.assertEqual(models.to_label("reviewed_comprimento", "nao_avaliavel"),
                         "Não avaliável pela imagem")
        self.assertEqual(models.to_label("reviewed_product_type", "unknown"), "Não sei")
        self.assertEqual(models.to_label("review_status", "bad_images"),
                         "Imagens ruins/insuficientes")
        self.assertEqual(models.to_label("image_view_type", "flat_lay"),
                         "Produto sem modelo (flat lay)")
        self.assertEqual(models.from_label("usable_for_fit", "Sim"), "yes")

    def test_every_enum_value_has_a_label(self):
        for field, allowed in models.ENUMS.items():
            for value in allowed:
                self.assertIn(value, models.LABELS_PT[field],
                              f"{field}:{value} sem label pt")


class TestExportKeepsCanonicalPlusLabels(unittest.TestCase):
    def test_result_and_image_rows(self):
        with tempfile.TemporaryDirectory() as tmp:
            progress = {"reviewer": "Rosita", "current_index": 0, "reviews": {}}
            review = storage.get_review(progress, ITEM["product_id"])
            review.update({"reviewed_product_type": "vestido",
                           "reviewed_comprimento": "longo", "reviewed_fit": "nao_avaliavel",
                           "review_status": "reviewed",
                           "review_notes": "foto boa, barra visível", "reviewed_at": "t"})
            review["images"]["1"] = dict(models.empty_image_review(),
                                         image_view_type="full_body",
                                         usable_for_comprimento="yes")
            paths = export.export_results([ITEM], progress, tmp, "b1")
            with open(paths["results_csv"], encoding="utf-8", newline="") as fh:
                row = next(csv.DictReader(fh))
            self.assertEqual(row["reviewed_comprimento"], "longo")          # canonical
            self.assertEqual(row["reviewed_comprimento_label"], "Longo")    # pt label
            self.assertEqual(row["reviewed_fit"], "nao_avaliavel")
            self.assertEqual(row["reviewed_fit_label"], "Não avaliável pela imagem")
            self.assertEqual(row["review_status_label"], "Revisado")
            self.assertEqual(row["review_notes"], "foto boa, barra visível")
            self.assertEqual(row["fit_evaluable"], "no")
            with open(paths["images_csv"], encoding="utf-8", newline="") as fh:
                image_row = next(csv.DictReader(fh))
            self.assertEqual(image_row["image_view_type"], "full_body")     # canonical
            self.assertEqual(image_row["image_view_type_label"], "Corpo inteiro")
            self.assertEqual(image_row["usable_for_comprimento_label"], "Sim")


class TestImageScaling(unittest.TestCase):
    def test_scale_to_fit_preserves_aspect_ratio(self):
        width, height, scale = image_utils.scale_to_fit(1000, 1428, 460, 560)
        self.assertAlmostEqual(width / height, 1000 / 1428, places=2)
        self.assertLessEqual(width, 460)
        self.assertLessEqual(height, 560)
        self.assertAlmostEqual(scale, 560 / 1428, places=3)

    def test_small_images_are_not_upscaled(self):
        width, height, scale = image_utils.scale_to_fit(200, 100, 800, 800)
        self.assertEqual((width, height, scale), (200, 100, 1.0))

    def test_degenerate_sizes_do_not_crash(self):
        self.assertEqual(image_utils.scale_to_fit(0, 0, 100, 100)[2], 1.0)
        self.assertEqual(image_utils.scale_to_fit(100, 100, 0, 100)[2], 1.0)

    def test_missing_image_returns_placeholder(self):
        pil_image, info = image_utils.load_pil("/nope/x.jpg")
        self.assertIsNone(pil_image)
        self.assertIn("não encontrada", info)
        pil_image, info = image_utils.load_pil(None)
        self.assertIsNone(pil_image)


class TestPackageDiscovery(unittest.TestCase):
    def test_app_storage_finds_review_items_inside_package(self):
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = os.path.join(tmp, "data")
            os.makedirs(data_dir)
            with open(os.path.join(data_dir, "review_items.jsonl"), "w",
                      encoding="utf-8") as fh:
                fh.write(json.dumps(ITEM, ensure_ascii=False) + "\n")
            package = storage.AuditorPackage(tmp)
            self.assertEqual(len(package.items), 1)
            self.assertEqual(package.items[0]["product_id"], ITEM["product_id"])
            self.assertTrue(package.image_abs_path("data/images/x_01.jpg")
                            .startswith(tmp))
        with self.assertRaises(FileNotFoundError):          # not a package dir
            storage.AuditorPackage("/tmp/definitely_not_a_package_xyz")


if __name__ == "__main__":
    unittest.main()
