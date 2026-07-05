"""Tkinter UI for the offline human audit (v0).

Deliberately simple: one window, product-by-product navigation, per-product and
per-image review fields, autosave on navigation + explicit save/export buttons.
All persistence/export logic lives in storage.py/export.py (tested offline);
this module only wires widgets to that logic.
"""
from __future__ import annotations

import datetime
import os
import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog, ttk

from . import export, image_utils, models, storage

IMAGE_MAX_W, IMAGE_MAX_H = 460, 560

PRODUCT_FIELDS = [
    ("reviewed_product_type", "Tipo do produto", models.REVIEWED_PRODUCT_TYPES),
    ("reviewed_comprimento", "Comprimento", models.REVIEWED_COMPRIMENTO),
    ("reviewed_fit", "Fit (caimento)", models.REVIEWED_FIT),
    ("review_status", "Status da revisão", models.REVIEW_STATUSES),
]
IMAGE_FIELDS = [
    ("image_view_type", "Tipo de vista", models.IMAGE_VIEW_TYPES),
    ("image_quality", "Qualidade", models.IMAGE_QUALITIES),
    ("usable_for_comprimento", "Serve p/ comprimento?", models.YES_NO_UNKNOWN),
    ("usable_for_fit", "Serve p/ fit?", models.YES_NO_UNKNOWN),
    ("usable_for_future_attributes", "Serve p/ outros atributos?", models.YES_NO_UNKNOWN),
]


class AuditorApp:
    def __init__(self, package_dir: str):
        self.package = storage.AuditorPackage(package_dir)
        self.store = storage.ProgressStore(self.package.output_dir)
        self.progress = self.store.load()
        self.index = min(self.progress.get("current_index", 0),
                         max(0, len(self.package.items) - 1))
        self.image_index = 0                                 # 0-based, per product
        self._photo = None                                   # keep a reference (Tk GC)

        self.root = tk.Tk()
        self.root.title(f"Fashion Auditor — lote {self.package.batch_id}")
        self.root.geometry("1080x760")
        self._build_widgets()
        self._load_current_item()

    # ------------------------------------------------------------------ widgets
    def _build_widgets(self) -> None:
        top = ttk.Frame(self.root, padding=6)
        top.pack(fill="x")
        ttk.Label(top, text=f"Lote: {self.package.batch_id}").pack(side="left")
        ttk.Label(top, text="   Seu nome: ").pack(side="left")
        self.reviewer_var = tk.StringVar(value=self.progress.get("reviewer", ""))
        ttk.Entry(top, textvariable=self.reviewer_var, width=22).pack(side="left")
        self.progress_label = ttk.Label(top, text="", font=("", 13, "bold"))
        self.progress_label.pack(side="right")

        body = ttk.Frame(self.root, padding=6)
        body.pack(fill="both", expand=True)

        # left: image + per-image review
        left = ttk.Frame(body)
        left.pack(side="left", fill="both", expand=True, padx=(0, 8))
        self.image_label = tk.Label(left, relief="groove", width=58, height=24,
                                    anchor="center", justify="center")
        self.image_label.pack(fill="both", expand=True)
        image_nav = ttk.Frame(left)
        image_nav.pack(fill="x", pady=3)
        ttk.Button(image_nav, text="◀ imagem", command=lambda: self._switch_image(-1)).pack(side="left")
        self.image_info = ttk.Label(image_nav, text="")
        self.image_info.pack(side="left", expand=True)
        ttk.Button(image_nav, text="imagem ▶", command=lambda: self._switch_image(1)).pack(side="right")

        image_form = ttk.LabelFrame(left, text="Avaliação DESTA imagem", padding=6)
        image_form.pack(fill="x")
        self.image_vars = {}
        for row, (field, label, values) in enumerate(IMAGE_FIELDS):
            ttk.Label(image_form, text=label).grid(row=row, column=0, sticky="w")
            var = tk.StringVar()
            combo = ttk.Combobox(image_form, textvariable=var, state="readonly",
                                 values=[""] + values, width=18)
            combo.grid(row=row, column=1, sticky="w", padx=4, pady=1)
            self.image_vars[field] = var
        ttk.Label(image_form, text="Notas da imagem").grid(row=len(IMAGE_FIELDS), column=0, sticky="w")
        self.image_notes_var = tk.StringVar()
        ttk.Entry(image_form, textvariable=self.image_notes_var, width=32).grid(
            row=len(IMAGE_FIELDS), column=1, sticky="we", padx=4)

        # right: product info + per-product review
        right = ttk.Frame(body, width=430)
        right.pack(side="right", fill="y")
        info = ttk.LabelFrame(right, text="Produto", padding=6)
        info.pack(fill="x")
        self.info_text = tk.Text(info, height=9, width=52, wrap="word", state="disabled",
                                 relief="flat", background=self.root.cget("background"))
        self.info_text.pack(fill="x")

        suggestion = ttk.LabelFrame(right, text="🤖 Sugestão do modelo (você decide!)",
                                    padding=6)
        suggestion.pack(fill="x", pady=(6, 0))
        self.suggestion_label = ttk.Label(suggestion, text="", justify="left")
        self.suggestion_label.pack(anchor="w")
        self.use_suggestion_btn = ttk.Button(suggestion, text="⬇ Usar sugestão",
                                             command=self._apply_suggestion)
        self.use_suggestion_btn.pack(anchor="e")

        form = ttk.LabelFrame(right, text="Revisão do produto (sua avaliação)", padding=6)
        form.pack(fill="x", pady=6)
        self.product_vars = {}
        for row, (field, label, values) in enumerate(PRODUCT_FIELDS):
            ttk.Label(form, text=label).grid(row=row, column=0, sticky="w")
            var = tk.StringVar()
            combo = ttk.Combobox(form, textvariable=var, state="readonly",
                                 values=[""] + values, width=20)
            combo.grid(row=row, column=1, sticky="w", padx=4, pady=2)
            self.product_vars[field] = var
        ttk.Label(form, text="Notas do produto\n(observações livres)").grid(
            row=len(PRODUCT_FIELDS), column=0, sticky="nw")
        self.notes_text = tk.Text(form, height=4, width=34)
        self.notes_text.grid(row=len(PRODUCT_FIELDS), column=1, sticky="we", padx=4, pady=2)
        self.status_label = ttk.Label(right, text="", font=("", 12))
        self.status_label.pack(anchor="w", pady=2)

        nav = ttk.Frame(self.root, padding=6)
        nav.pack(fill="x")
        ttk.Button(nav, text="◀ Anterior", command=lambda: self._navigate(-1)).pack(side="left")
        ttk.Label(nav, text=" Ir para nº ").pack(side="left")
        self.goto_var = tk.StringVar()
        goto = ttk.Entry(nav, textvariable=self.goto_var, width=5)
        goto.pack(side="left")
        goto.bind("<Return>", lambda _e: self._goto())
        ttk.Button(nav, text="Ir", command=self._goto).pack(side="left", padx=(2, 12))
        ttk.Button(nav, text="💾 Salvar", command=self._save).pack(side="left")
        ttk.Button(nav, text="➕ Adicionar produto/imagem",
                   command=self._add_manual_item).pack(side="left", padx=8)
        ttk.Button(nav, text="📤 Exportar resultado final",
                   command=self._export_final).pack(side="left", padx=8)
        ttk.Button(nav, text="Próximo ▶", command=lambda: self._navigate(1)).pack(side="right")
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    # ------------------------------------------------------------------ item I/O
    def _current_item(self) -> dict:
        return self.package.items[self.index]

    def _load_current_item(self) -> None:
        item = self._current_item()
        review = storage.get_review(self.progress, item["product_id"])
        self.image_index = 0
        for field, var in self.product_vars.items():
            var.set(review.get(field, ""))
        self.notes_text.delete("1.0", "end")
        self.notes_text.insert("1.0", review.get("review_notes", ""))
        self._render_info(item, review)
        self._render_image()
        self._render_progress()

    def _render_info(self, item: dict, review: dict) -> None:
        origin_labels = {"crawled": "coleta nova (crawler)", "review_queue": "fila de revisão",
                         "manual_import": "adicionado manualmente"}
        origin = item.get("record_origin") or "review_queue"
        lines = [
            item.get("product_title") or "(sem título)",
            f"Origem do registro: {origin_labels.get(origin, origin)}",
            f"URL: {item.get('product_url') or '-'}",
            f"Preço: R${item.get('price')}  (de R${item.get('original_price')}, "
            f"-{item.get('discount_percentage')}%)",
            f"Categoria: {item.get('category') or item.get('collection_or_source') or '-'}",
            f"Tipo detectado: {item.get('product_type') or '-'}",
            f"Dedupe: {item.get('duplicate_status') or '-'}",
        ]
        if item.get("matched_dataset_title"):
            lines.append(f"Parecido com (dataset): {item['matched_dataset_title']} "
                         f"[{item.get('matched_dataset_comprimento')}/{item.get('matched_dataset_fit')}]")
        self.info_text.configure(state="normal")
        self.info_text.delete("1.0", "end")
        self.info_text.insert("1.0", "\n".join(lines))
        self.info_text.configure(state="disabled")
        self._render_suggestion(item)
        self.status_label.configure(text=f"Status: {storage.item_status(review)}")

    def _render_suggestion(self, item: dict) -> None:
        if item.get("suggested_comprimento") or item.get("suggested_fit"):
            needs = item.get("suggested_needs_review")
            needs_txt = "sim" if needs else ("não" if needs is not None else "-")
            text = (f"comprimento: {item.get('suggested_comprimento')} "
                    f"(confiança {item.get('suggested_comprimento_confidence')})\n"
                    f"fit: {item.get('suggested_fit')} "
                    f"(confiança {item.get('suggested_fit_confidence')})\n"
                    f"precisa revisão humana: {needs_txt}   "
                    f"[{item.get('suggestion_source') or 'modelo local'}]")
            self.suggestion_label.configure(text=text)
            self.use_suggestion_btn.state(["!disabled"])
        else:
            self.suggestion_label.configure(text="(sem sugestão do modelo para este item)")
            self.use_suggestion_btn.state(["disabled"])

    def _apply_suggestion(self) -> None:
        item = self._current_item()
        if item.get("suggested_comprimento"):
            self.product_vars["reviewed_comprimento"].set(item["suggested_comprimento"])
        if item.get("suggested_fit"):
            self.product_vars["reviewed_fit"].set(item["suggested_fit"])
        if item.get("product_type") in ("vestido", "macacao"):
            self.product_vars["reviewed_product_type"].set(item["product_type"])
        self.status_label.configure(
            text="Status: sugestão aplicada — confira e ajuste se necessário")

    def _render_progress(self) -> None:
        done = sum(1 for r in self.progress.get("reviews", {}).values()
                   if r.get("review_status"))
        self.progress_label.configure(
            text=f"{self.index + 1} / {len(self.package.items)}   (revisados: {done})")

    # ------------------------------------------------------------------ images
    def _image_paths(self) -> list:
        return self._current_item().get("image_paths") or []

    def _render_image(self) -> None:
        paths = self._image_paths()
        rel = paths[self.image_index] if paths else None
        photo, info = image_utils.load_scaled_photo(
            self.package.image_abs_path(rel), IMAGE_MAX_W, IMAGE_MAX_H)
        self._photo = photo
        if photo is not None:
            self.image_label.configure(image=photo, text="")
        else:
            self.image_label.configure(image="", text=info)
        total = max(1, len(paths))
        self.image_info.configure(
            text=f"imagem {self.image_index + 1}/{total} — {os.path.basename(rel) if rel else '-'}")
        review = storage.get_review(self.progress, self._current_item()["product_id"])
        image_review = review["images"].get(str(self.image_index + 1)) or models.empty_image_review()
        for field, var in self.image_vars.items():
            var.set(image_review.get(field, ""))
        self.image_notes_var.set(image_review.get("image_review_notes", ""))

    def _collect_image_form(self) -> None:
        review = storage.get_review(self.progress, self._current_item()["product_id"])
        image_review = {field: var.get() for field, var in self.image_vars.items()}
        image_review["image_review_notes"] = self.image_notes_var.get()
        if any(image_review.values()):
            review["images"][str(self.image_index + 1)] = image_review

    def _switch_image(self, step: int) -> None:
        paths = self._image_paths()
        if not paths:
            return
        self._collect_image_form()
        self.image_index = (self.image_index + step) % len(paths)
        self._render_image()

    # ------------------------------------------------------------------ actions
    def _collect_product_form(self) -> None:
        item = self._current_item()
        review = storage.get_review(self.progress, item["product_id"])
        self._collect_image_form()
        for field, var in self.product_vars.items():
            review[field] = var.get()
        review["review_notes"] = self.notes_text.get("1.0", "end").strip()
        # labels filled but status untouched -> count as reviewed
        if not review["review_status"] and (review["reviewed_comprimento"]
                                            or review["reviewed_fit"]
                                            or review["reviewed_product_type"]):
            review["review_status"] = "reviewed"
        if any(review[f] for f, _, _ in PRODUCT_FIELDS) or review["review_notes"]:
            review["reviewed_at"] = datetime.datetime.now().astimezone().isoformat(timespec="seconds")

    def _save(self, quiet: bool = False) -> None:
        self._collect_product_form()
        self.progress["reviewer"] = self.reviewer_var.get().strip()
        self.progress["current_index"] = self.index
        self.store.save(self.progress)
        export.export_results(self.package.items, self.progress,
                              self.package.output_dir, self.package.batch_id)
        self._render_info(self._current_item(),
                          storage.get_review(self.progress, self._current_item()["product_id"]))
        self._render_progress()
        if not quiet:
            self.status_label.configure(text="Status: salvo ✓")

    def _navigate(self, step: int) -> None:
        self._save(quiet=True)
        self.index = max(0, min(len(self.package.items) - 1, self.index + step))
        self.progress["current_index"] = self.index
        self._load_current_item()

    def _goto(self) -> None:
        try:
            target = int(self.goto_var.get())
        except ValueError:
            return
        self._save(quiet=True)
        self.index = max(0, min(len(self.package.items) - 1, target - 1))
        self._load_current_item()

    def _add_manual_item(self) -> None:
        paths = filedialog.askopenfilenames(
            title="Escolha a(s) imagem(ns) da peça",
            filetypes=[("Imagens", "*.jpg *.jpeg *.png *.webp"), ("Todos", "*.*")])
        if not paths:
            return
        title = simpledialog.askstring("Nova peça", "Título/nome da peça (opcional):",
                                       parent=self.root) or ""
        self._save(quiet=True)                              # persist current item first
        item = self.package.add_manual_item(list(paths), title=title)
        self.index = len(self.package.items) - 1
        self.progress["current_index"] = self.index
        self._load_current_item()
        self._save(quiet=True)                              # include it in the exports now
        self.status_label.configure(
            text=f"Status: peça adicionada ({len(item['image_paths'])} imagem(ns)) — revise os campos")

    def _export_final(self) -> None:
        self._save(quiet=True)
        paths = export.export_final(self.package.items, self.progress,
                                    self.package.output_dir, self.package.batch_id)
        messagebox.showinfo(
            "Exportado!",
            "Arquivos finais gerados na pasta output/:\n\n"
            f"- {os.path.basename(paths['final_csv'])}\n"
            f"- {os.path.basename(paths['final_jsonl'])}\n"
            f"- {os.path.basename(paths['zip'])}\n\n"
            "Envie de volta o arquivo reviewed_results_package.zip.")

    def _on_close(self) -> None:
        self._save(quiet=True)
        self.root.destroy()

    def run(self) -> None:
        self.root.mainloop()
