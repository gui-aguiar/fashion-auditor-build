"""Build a self-contained auditor package (v0.1) from one of three sources.

Modes:
  candidates       review_candidates.csv (v010 queue)      -> record_origin=review_queue
  vestidos-crawled crawler products.jsonl, vestidos only   -> record_origin=crawled
  all-crawled      crawler products.jsonl, everything      -> record_origin=crawled
                   (macacões/unknown preserved for future categories)

Crawled modes copy the CRAWLER's downloaded images (local_image_paths) — never the
old official-dataset images. Optional local-model suggestions (frozen calibrated
extractor; no training/recalibration) can be attached to each item as suggested_*
fields — clearly separated from the human reviewed_* fields.

Package layout:
    <package>/FashionAuditor[.exe]        (added by the build step)
    <package>/package_manifest.json
    <package>/data/review_items.csv|jsonl
    <package>/data/images/...
    <package>/data/manual_imports/images/ (auditor-added images live here)
    <package>/output/
    <package>/README_AUDITOR.txt
"""
from __future__ import annotations

import csv
import datetime
import json
import os
import shutil
from typing import Callable, Dict, List, Optional

from . import models

MODES = ["candidates", "vestidos-crawled", "all-crawled"]
ITEM_LIST_FIELDS = ["image_paths", "image_urls", "original_image_paths"]
SUGGESTION_FIELDS = ["suggested_comprimento", "suggested_comprimento_confidence",
                     "suggested_fit", "suggested_fit_confidence",
                     "suggested_needs_review", "suggested_joint_confidence",
                     "suggestion_source"]

README_AUDITOR = """COMO USAR O FASHION AUDITOR (revisão de produtos)
==================================================

1. COMO ABRIR
   - Dê dois cliques no arquivo "FashionAuditor.exe" (Windows) ou "FashionAuditor" (Mac).
   - Windows pode mostrar um aviso azul do SmartScreen na primeira vez:
     clique em "Mais informações" e depois "Executar assim mesmo". É esperado,
     porque o aplicativo não tem assinatura digital paga.
   - O programa abre mostrando o primeiro produto do lote.
   - Escreva seu nome no campo "Seu nome" (canto superior).

2. COMO REVISAR UM PRODUTO
   - Os campos JÁ VÊM PREENCHIDOS com a sugestão do computador (quando existe).
     Seu trabalho é OLHAR A FOTO e corrigir o que estiver errado.
     Se concordar com tudo, confira e passe para o próximo.
   - Campos: Tipo do produto, Comprimento, Fit/Modelagem e Status da revisão.
   - "Observações da peça": escreva livremente qualquer coisa útil. Exemplos:
       "Imagem cortada, não dá para avaliar comprimento."
       "Parece midi, mas a foto não mostra a barra inteira."
       "Produto parece macacão, não vestido."
       "Imagem boa para tecido/estampa, mas ruim para comprimento."
   - Use "◀ imagem / imagem ▶" para ver as outras fotos do produto.
   - Use "◀ Anterior / Próximo ▶" para trocar de produto (o app salva sozinho).
   - O botão "❓ Ajuda" dentro do app repete estas explicações.

3. A FOTO NUNCA FICA CORTADA
   - Por padrão a foto é ajustada para caber INTEIRA na janela
     (modo "Ajustar à janela"). Pode redimensionar a janela à vontade.
   - Para ver detalhes, clique em "Tamanho real" e use as barras de rolagem.

4. O QUE SIGNIFICA CADA OPÇÃO (importante!)
   - "Outro": você TEM certeza de que não é vestido nem macacão (é outra peça).
   - "Não sei": você não conseguiu identificar com segurança.
   - "Não avaliável pela imagem": o atributo existe, mas a foto não permite
     julgar. Ex.: foto cortada não mostra a barra -> comprimento não avaliável.
     NUNCA chute: é melhor "Não avaliável" do que errar.
   - "Imagens ruins/insuficientes" (status): problema geral das fotos do produto.
   - "Dúvida" (status): você tem uma hipótese, mas sem certeza — escreva a
     hipótese em "Observações da peça".

5. COMO AVALIAR CADA IMAGEM
   - Na caixa "Avaliação DESTA imagem" (embaixo da foto):
     - "Tipo da imagem": Corpo inteiro, Cortada, Detalhe, Costas,
       Produto sem modelo (flat lay) ou Não sei.
     - "Serve p/ comprimento?": "Não" se a foto não mostra a barra.
     - "Serve p/ fit?": "Não" se não dá para ver o caimento.
     - "Serve p/ outros atributos?": "Sim" se mostra bem tecido, manga, decote
       etc. (mesmo cortada, pode servir para outras coisas no futuro).

6. ADICIONAR UMA PEÇA/IMAGEM NOVA
   - Botão "➕ Adicionar produto/imagem": escolha uma ou mais fotos do seu
     computador; o app copia para dentro do pacote e cria um item novo para
     você revisar como os demais.

7. COMO SALVAR
   - O app salva automaticamente quando você troca de produto e ao fechar.
   - O botão "💾 Salvar" força um salvamento a qualquer momento.
   - Pode fechar e abrir de novo: você continua de onde parou.

8. O QUE DEVOLVER NO FINAL
   - Quando terminar, clique em "📤 Exportar resultado final".
   - Envie de volta o arquivo:  output/reviewed_results_package.zip
   - (Se preferir, pode enviar output/reviewed_results.csv e
      output/reviewed_results.jsonl.)

Obrigado! 💜
"""


def _split_list(value: Optional[str]) -> List[str]:
    return [part for part in (value or "").split(";") if part]


def _base_item(batch_id: str, record_origin: str) -> dict:
    return {"review_batch_id": batch_id, "record_origin": record_origin,
            "manual_import": False, "manual_imported_at": None,
            "original_import_paths": [],
            **{field: None for field in SUGGESTION_FIELDS},
            "image_paths": [], "image_urls": [], "original_image_paths": []}


def _candidate_to_item(row: Dict, batch_id: str, collection: str) -> dict:
    item = _base_item(batch_id, "review_queue")
    item.update({
        "source_site": row.get("source_site"),
        "source_url": row.get("source_url"),
        "collection_or_source": row.get("collection_or_source") or collection,
        "product_id": row.get("product_id"),
        "canonical_slug": row.get("canonical_slug"),
        "product_title": row.get("product_title"),
        "product_url": row.get("product_url"),
        "product_type": row.get("product_type"),
        "duplicate_status": row.get("duplicate_status"),
        "matched_dataset_product_id": row.get("matched_dataset_product_id"),
        "matched_dataset_title": row.get("matched_dataset_title"),
        "matched_dataset_comprimento": row.get("matched_dataset_comprimento"),
        "matched_dataset_fit": row.get("matched_dataset_fit"),
        "price": row.get("price"),
        "original_price": row.get("original_price"),
        "discount_percentage": row.get("discount_percentage"),
        "image_urls": [u for u in (row.get("image_01_url"), row.get("image_02_url")) if u],
    })
    item["_source_images"] = [p for p in (row.get("image_01_path"),
                                          row.get("image_02_path")) if p]
    return item


def _crawled_to_item(record: Dict, batch_id: str) -> dict:
    item = _base_item(batch_id, "crawled")
    item.update({
        "source_site": record.get("source_site"),
        "source_url": record.get("source_url"),
        "collection_or_source": record.get("collection_or_source"),
        "product_id": record.get("product_id"),
        "canonical_slug": record.get("product_id"),      # crawler ids ARE the slug
        "product_title": record.get("product_title"),
        "product_url": record.get("product_url"),
        "product_type": record.get("product_type"),
        "duplicate_status": None,
        "matched_dataset_product_id": None, "matched_dataset_title": None,
        "matched_dataset_comprimento": None, "matched_dataset_fit": None,
        "price": record.get("price"),
        "original_price": record.get("original_price"),
        "discount_percentage": record.get("discount_percentage"),
        "image_urls": list(record.get("image_urls") or [])[:2],
    })
    item["_source_images"] = list(record.get("local_image_paths") or [])
    return item


def _load_items(input_path: str, mode: str, batch_id: str, collection: str) -> List[dict]:
    if mode == "candidates":
        with open(input_path, encoding="utf-8", newline="") as fh:
            return [_candidate_to_item(row, batch_id, collection)
                    for row in csv.DictReader(fh)]
    with open(input_path, encoding="utf-8") as fh:
        records = [json.loads(line) for line in fh if line.strip()]
    if mode == "vestidos-crawled":
        records = [r for r in records if r.get("product_type") == "vestido"]
    return [_crawled_to_item(record, batch_id) for record in records]


def local_suggestion_fn(project_root: str) -> Callable:
    """Suggestion provider backed by the FROZEN calibrated local extractor.

    Raises SystemExit with an actionable message when models/dependencies are not
    available locally — never fails silently (the review zip does not ship them)."""
    try:
        from src.local_model import review_rules
        from src.local_model.inference import DressAttributeExtractor, ExtractorUnavailable
    except ImportError as exc:
        raise SystemExit(
            "--with-local-suggestions needs the local ML stack (torch/open_clip/"
            f"scikit-learn), which is not importable here: {exc}\n"
            "  Install the deps (see requirements.txt) or build without the flag.")
    try:
        extractor = DressAttributeExtractor(
            os.path.join(project_root, "data", "local_model", "vestidos", "models"),
            device="auto", calibrated=True)
    except ExtractorUnavailable as exc:
        raise SystemExit(
            f"--with-local-suggestions: local models unavailable — {exc}\n"
            "  Run Etapas 3+5 first, or build the package without the flag.")

    meta_path = os.path.join(project_root, "data", "local_model", "vestidos",
                             "models", "calibration_metadata.json")
    thresholds = {"min_confidence": review_rules.DEFAULT_MIN_CONFIDENCE,
                  "min_margin": review_rules.DEFAULT_MIN_MARGIN}
    if os.path.exists(meta_path):
        with open(meta_path, encoding="utf-8") as fh:
            thresholds.update(json.load(fh).get("production_thresholds", {}) or {})
    source = f"local_{extractor.model_version}"

    def suggest(entries: List[dict]) -> Dict[str, dict]:
        """entries: [{'product_id', 'image_path' (abs)}] -> product_id -> suggestion."""
        records = [{"image_path": entry["image_path"]} for entry in entries]
        results = extractor.predict_batch(records, thresholds["min_confidence"],
                                          thresholds["min_margin"])
        suggestions = {}
        for entry, result in zip(entries, results):
            if result.get("error") or not result.get("attributes"):
                continue
            conf = result["confidence"]
            suggestions[entry["product_id"]] = {
                "suggested_comprimento": result["attributes"]["comprimento"],
                "suggested_comprimento_confidence": conf["comprimento"],
                "suggested_fit": result["attributes"]["fit"],
                "suggested_fit_confidence": conf["fit"],
                "suggested_needs_review": result["review"]["needs_review"],
                "suggested_joint_confidence": round(conf["comprimento"] * conf["fit"], 4),
                "suggestion_source": source,
            }
        return suggestions

    suggest.source = source
    return suggest


def build_package(input_path: str, output_dir: str, *, mode: str = "candidates",
                  copy_images: bool = True, batch_id: Optional[str] = None,
                  project_root: Optional[str] = None, force: bool = False,
                  suggestion_fn: Optional[Callable] = None) -> dict:
    """Create the auditor package. Returns the manifest dict. Refuses to clobber
    existing audit progress unless force=True."""
    if mode not in MODES:
        raise ValueError(f"unknown mode {mode!r}; expected one of {MODES}")
    output_dir = os.path.abspath(output_dir)
    project_root = os.path.abspath(project_root or os.getcwd())
    batch_id = batch_id or os.path.basename(output_dir.rstrip("/"))
    collection = os.path.basename(os.path.dirname(os.path.abspath(input_path))) or batch_id

    progress_file = os.path.join(output_dir, "output", "review_progress.json")
    if os.path.exists(progress_file) and not force:
        raise SystemExit(f"ABORT: {progress_file} exists — the auditor may have started "
                         "reviewing. Use --force only to intentionally rebuild.")

    items = _load_items(input_path, mode, batch_id, collection)

    data_dir = os.path.join(output_dir, "data")
    images_dir = os.path.join(data_dir, "images")
    os.makedirs(images_dir, exist_ok=True)
    os.makedirs(os.path.join(data_dir, "manual_imports", "images"), exist_ok=True)
    os.makedirs(os.path.join(output_dir, "output"), exist_ok=True)

    images_copied, images_missing = 0, 0
    for item in items:
        for source_rel in item.pop("_source_images", []):
            source_abs = source_rel if os.path.isabs(source_rel) else \
                os.path.join(project_root, source_rel)
            if not os.path.exists(source_abs):
                images_missing += 1
                continue
            destination = os.path.join(images_dir, os.path.basename(source_abs))
            if copy_images and not os.path.exists(destination):
                shutil.copy2(source_abs, destination)
                images_copied += 1
            item["image_paths"].append(os.path.join("data", "images",
                                                    os.path.basename(source_abs)))
            item["original_image_paths"].append(source_rel)

    suggestion_source, suggested_count = None, 0
    if suggestion_fn is not None:
        # the local extractor is a VESTIDO model — suggesting labels for macacões/
        # unknown would mislead the auditor, so only vestidos get suggestions
        entries = [{"product_id": item["product_id"],
                    "image_path": os.path.join(output_dir, item["image_paths"][0])}
                   for item in items
                   if item["image_paths"] and item.get("product_type") == "vestido"]
        suggestions = suggestion_fn(entries)
        for item in items:
            suggestion = suggestions.get(item["product_id"])
            if suggestion:
                item.update(suggestion)
                suggested_count += 1
        suggestion_source = getattr(suggestion_fn, "source", None) or next(
            (s.get("suggestion_source") for s in suggestions.values()), None)

    with open(os.path.join(data_dir, "review_items.jsonl"), "w", encoding="utf-8") as fh:
        for item in items:
            fh.write(json.dumps(item, ensure_ascii=False) + "\n")
    csv_fields = list(items[0].keys()) if items else []
    with open(os.path.join(data_dir, "review_items.csv"), "w", encoding="utf-8",
              newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=csv_fields)
        writer.writeheader()
        for item in items:
            flat = dict(item)
            for field in ITEM_LIST_FIELDS:
                flat[field] = ";".join(item.get(field) or [])
            writer.writerow(flat)

    with open(os.path.join(output_dir, "README_AUDITOR.txt"), "w", encoding="utf-8") as fh:
        fh.write(README_AUDITOR)

    manifest = {
        "review_batch_id": batch_id,
        "schema_version": models.SCHEMA_VERSION,
        "mode": mode,
        "created_at": datetime.datetime.now().astimezone().isoformat(timespec="seconds"),
        "source_input": os.path.relpath(os.path.abspath(input_path), project_root),
        "collection_or_source": collection,
        "n_items": len(items),
        "images_copied": images_copied,
        "images_missing": images_missing,
        "copy_images": copy_images,
        "with_suggestions": suggestion_fn is not None,
        "suggestion_source": suggestion_source,
        "items_with_suggestions": suggested_count,
    }
    with open(os.path.join(output_dir, "package_manifest.json"), "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, ensure_ascii=False, indent=1)
    return manifest
