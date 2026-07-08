"""Tkinter UI for the offline human audit (v0.2).

Design notes:
  * The image area is a Canvas that re-fits the photo whenever the window resizes —
    the image is NEVER silently cropped. Default mode "Ajustar à janela" scales it
    (aspect preserved) to fit; "Tamanho real" shows it 1:1 with scrollbars.
  * Review combos show PORTUGUESE labels; canonical values are converted at the
    edges (models.to_label / from_label) so the export stays pipeline-stable.
  * When an item loads, review fields are PRE-FILLED with the model suggestion
    (models.initial_field_values) unless the auditor already saved a value. An
    item only auto-becomes "Revisado" if the auditor actually interacted with it
    — untouched pre-fills never create phantom reviews.
All persistence/export logic lives in storage.py/export.py (tested offline).
"""
from __future__ import annotations

import datetime
import os
import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog, ttk

from . import export, image_utils, models, storage

PRODUCT_FIELDS = [
    ("reviewed_product_type", "Tipo do produto"),
    ("reviewed_comprimento", "Comprimento"),
    ("reviewed_fit", "Fit / Modelagem"),
    ("review_status", "Status da revisão"),
]
IMAGE_FIELDS = [
    ("image_view_type", "Tipo da imagem"),
    ("image_quality", "Qualidade da imagem"),
    ("usable_for_comprimento", "Serve p/ comprimento?"),
    ("usable_for_fit", "Serve p/ fit?"),
    ("usable_for_future_attributes", "Serve p/ outros atributos?"),
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
        self._pil_image = None                               # original, for re-fits
        self._resize_job = None
        self._touched = False                                # auditor interacted?

        self.root = tk.Tk()
        self.root.title(f"Fashion Auditor — lote {self.package.batch_id}")
        self.root.geometry("1120x780")
        self.root.minsize(760, 560)
        self.image_mode = tk.StringVar(value="fit")          # fit | real
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
        ttk.Button(top, text="❓ Ajuda (significados)",
                   command=self._show_help).pack(side="left", padx=10)
        self.progress_label = ttk.Label(top, text="", font=("", 13, "bold"))
        self.progress_label.pack(side="right")

        body = ttk.Frame(self.root, padding=6)
        body.pack(fill="both", expand=True)

        # ---- left: responsive image area + per-image review ----------------------
        left = ttk.Frame(body)
        left.pack(side="left", fill="both", expand=True, padx=(0, 8))

        image_area = ttk.Frame(left)
        image_area.pack(fill="both", expand=True)
        self.canvas = tk.Canvas(image_area, background="#f2f2f2",
                                highlightthickness=1, highlightbackground="#cccccc")
        self.scroll_y = ttk.Scrollbar(image_area, orient="vertical",
                                      command=self.canvas.yview)
        self.scroll_x = ttk.Scrollbar(image_area, orient="horizontal",
                                      command=self.canvas.xview)
        self.canvas.configure(yscrollcommand=self.scroll_y.set,
                              xscrollcommand=self.scroll_x.set)
        self.canvas.grid(row=0, column=0, sticky="nsew")
        self.scroll_y.grid(row=0, column=1, sticky="ns")
        self.scroll_x.grid(row=1, column=0, sticky="ew")
        image_area.rowconfigure(0, weight=1)
        image_area.columnconfigure(0, weight=1)
        self.canvas.bind("<Configure>", self._on_canvas_resize)

        image_nav = ttk.Frame(left)
        image_nav.pack(fill="x", pady=3)
        ttk.Button(image_nav, text="◀ imagem",
                   command=lambda: self._switch_image(-1)).pack(side="left")
        self.image_info = ttk.Label(image_nav, text="")
        self.image_info.pack(side="left", expand=True)
        ttk.Radiobutton(image_nav, text="Ajustar à janela", value="fit",
                        variable=self.image_mode,
                        command=self._render_image_canvas).pack(side="right")
        ttk.Radiobutton(image_nav, text="Tamanho real", value="real",
                        variable=self.image_mode,
                        command=self._render_image_canvas).pack(side="right", padx=4)
        ttk.Button(image_nav, text="imagem ▶",
                   command=lambda: self._switch_image(1)).pack(side="right", padx=(0, 10))

        image_form = ttk.LabelFrame(left, text="Avaliação DESTA imagem", padding=6)
        image_form.pack(fill="x")
        self.image_vars = {}
        for row, (field, label) in enumerate(IMAGE_FIELDS):
            ttk.Label(image_form, text=label).grid(row=row, column=0, sticky="w")
            self.image_vars[field] = self._make_combo(image_form, field, row, width=26)
        ttk.Label(image_form, text="Observações da imagem").grid(
            row=len(IMAGE_FIELDS), column=0, sticky="w")
        self.image_notes_var = tk.StringVar()
        notes_entry = ttk.Entry(image_form, textvariable=self.image_notes_var, width=34)
        notes_entry.grid(row=len(IMAGE_FIELDS), column=1, sticky="we", padx=4)
        notes_entry.bind("<KeyRelease>", self._mark_touched)

        # ---- right: product info + suggestion + review ---------------------------
        right = ttk.Frame(body, width=440)
        right.pack(side="right", fill="y")
        info = ttk.LabelFrame(right, text="Produto", padding=6)
        info.pack(fill="x")
        self.info_text = tk.Text(info, height=9, width=54, wrap="word", state="disabled",
                                 relief="flat", background=self.root.cget("background"))
        self.info_text.pack(fill="x")

        suggestion = ttk.LabelFrame(right, text="🤖 Sugestão do modelo (você decide!)",
                                    padding=6)
        suggestion.pack(fill="x", pady=(6, 0))
        self.suggestion_label = ttk.Label(suggestion, text="", justify="left")
        self.suggestion_label.pack(anchor="w")
        self.use_suggestion_btn = ttk.Button(suggestion, text="⬇ Reaplicar sugestão",
                                             command=self._apply_suggestion)
        self.use_suggestion_btn.pack(anchor="e")

        form = ttk.LabelFrame(right, text="Revisão do produto (sua avaliação)", padding=6)
        form.pack(fill="x", pady=6)
        self.product_vars = {}
        for row, (field, label) in enumerate(PRODUCT_FIELDS):
            ttk.Label(form, text=label).grid(row=row, column=0, sticky="w")
            self.product_vars[field] = self._make_combo(form, field, row, width=26)
        ttk.Label(form, text="Observações da peça\n(escreva livremente)").grid(
            row=len(PRODUCT_FIELDS), column=0, sticky="nw")
        self.notes_text = tk.Text(form, height=4, width=36)
        self.notes_text.grid(row=len(PRODUCT_FIELDS), column=1, sticky="we", padx=4, pady=2)
        self.notes_text.bind("<KeyRelease>", self._mark_touched)
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

    def _make_combo(self, parent, field: str, row: int, width: int) -> tk.StringVar:
        """Readonly combobox showing the pt-BR labels for a canonical enum field."""
        var = tk.StringVar()
        combo = ttk.Combobox(parent, textvariable=var, state="readonly",
                             values=[""] + models.labels_for(field), width=width)
        combo.grid(row=row, column=1, sticky="w", padx=4, pady=2)
        combo.bind("<<ComboboxSelected>>", self._mark_touched)
        return var

    def _mark_touched(self, _event=None) -> None:
        self._touched = True

    def _show_help(self) -> None:
        messagebox.showinfo("Ajuda — o que significa cada opção", models.HELP_TEXT_PT,
                            parent=self.root)

    # ------------------------------------------------------------------ item I/O
    def _current_item(self) -> dict:
        return self.package.items[self.index]

    def _load_current_item(self) -> None:
        item = self._current_item()
        review = storage.get_review(self.progress, item["product_id"])
        self.image_index = 0
        self._touched = False
        # saved values win; otherwise the model suggestion pre-fills the combos
        initial = models.initial_field_values(item, review)
        for field, var in self.product_vars.items():
            var.set(models.to_label(field, initial.get(field, "")))
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
            f"Tipo detectado: {models.to_label('reviewed_product_type', item.get('product_type')) or '-'}",
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
            text = (f"comprimento: {models.to_label('reviewed_comprimento', item.get('suggested_comprimento'))} "
                    f"(confiança {item.get('suggested_comprimento_confidence')})\n"
                    f"fit: {models.to_label('reviewed_fit', item.get('suggested_fit'))} "
                    f"(confiança {item.get('suggested_fit_confidence')})\n"
                    f"o modelo pediu conferência humana: {needs_txt}\n"
                    f"(os campos ao lado já vêm preenchidos com isso — corrija se discordar)")
            self.suggestion_label.configure(text=text)
            self.use_suggestion_btn.state(["!disabled"])
        else:
            self.suggestion_label.configure(text="(sem sugestão do modelo para este item)")
            self.use_suggestion_btn.state(["disabled"])

    def _apply_suggestion(self) -> None:
        item = self._current_item()
        if item.get("suggested_comprimento"):
            self.product_vars["reviewed_comprimento"].set(
                models.to_label("reviewed_comprimento", item["suggested_comprimento"]))
        if item.get("suggested_fit"):
            self.product_vars["reviewed_fit"].set(
                models.to_label("reviewed_fit", item["suggested_fit"]))
        if item.get("product_type") in ("vestido", "macacao"):
            self.product_vars["reviewed_product_type"].set(
                models.to_label("reviewed_product_type", item["product_type"]))
        self._touched = True                                 # deliberate action
        self.status_label.configure(
            text="Status: sugestão reaplicada — confira e ajuste se necessário")

    def _render_progress(self) -> None:
        done = sum(1 for r in self.progress.get("reviews", {}).values()
                   if r.get("review_status"))
        self.progress_label.configure(
            text=f"{self.index + 1} / {len(self.package.items)}   (revisados: {done})")

    # ------------------------------------------------------------------ images
    def _image_paths(self) -> list:
        return self._current_item().get("image_paths") or []

    def _render_image(self) -> None:
        """Load the current image (original size) then draw it for the current mode."""
        paths = self._image_paths()
        rel = paths[self.image_index] if paths else None
        self._pil_image, self._image_note = image_utils.load_pil(
            self.package.image_abs_path(rel))
        self._current_rel_image = rel
        self._render_image_canvas()
        review = storage.get_review(self.progress, self._current_item()["product_id"])
        image_review = review["images"].get(str(self.image_index + 1)) or models.empty_image_review()
        for field, var in self.image_vars.items():
            var.set(models.to_label(field, image_review.get(field, "")))
        self.image_notes_var.set(image_review.get("image_review_notes", ""))

    def _render_image_canvas(self) -> None:
        """Draw the already-loaded image according to mode + current canvas size."""
        self.canvas.delete("all")
        paths = self._image_paths()
        total = max(1, len(paths))
        position = f"Imagem {self.image_index + 1}/{total}"
        canvas_w = max(self.canvas.winfo_width(), 60)
        canvas_h = max(self.canvas.winfo_height(), 60)

        if self._pil_image is None:
            self.canvas.create_text(canvas_w // 2, canvas_h // 2,
                                    text=self._image_note, justify="center")
            self.canvas.configure(scrollregion=(0, 0, canvas_w, canvas_h))
            self.image_info.configure(text=f"{position} — {self._image_note}")
            return

        if self.image_mode.get() == "fit":
            width, height, scale = image_utils.scale_to_fit(
                self._pil_image.width, self._pil_image.height,
                canvas_w - 8, canvas_h - 8)
            self._photo = image_utils.pil_to_photo(self._pil_image, width, height)
            self.canvas.create_image(canvas_w // 2, canvas_h // 2,
                                     image=self._photo, anchor="center")
            self.canvas.configure(scrollregion=(0, 0, canvas_w, canvas_h))
            mode_txt = f"ajustada à janela ({scale:.0%}) — inteira, sem corte"
        else:                                                # real size + scrollbars
            self._photo = image_utils.pil_to_photo(
                self._pil_image, self._pil_image.width, self._pil_image.height)
            self.canvas.create_image(0, 0, image=self._photo, anchor="nw")
            self.canvas.configure(scrollregion=(0, 0, self._pil_image.width,
                                                self._pil_image.height))
            mode_txt = "tamanho real (use as barras de rolagem)"
        name = os.path.basename(self._current_rel_image or "-")
        self.image_info.configure(text=f"{position} — {name} — {mode_txt}")

    def _on_canvas_resize(self, _event) -> None:
        """Re-fit the image when the window/canvas is resized (debounced)."""
        if self._resize_job is not None:
            self.root.after_cancel(self._resize_job)
        self._resize_job = self.root.after(120, self._render_image_canvas)

    def _collect_image_form(self) -> None:
        review = storage.get_review(self.progress, self._current_item()["product_id"])
        image_review = {field: models.from_label(field, var.get())
                        for field, var in self.image_vars.items()}
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
            review[field] = models.from_label(field, var.get())
        review["review_notes"] = self.notes_text.get("1.0", "end").strip()
        # Auto-"Revisado" ONLY when the auditor actually interacted with this item —
        # untouched model pre-fills must not become phantom human reviews.
        if self._touched and not review["review_status"] and (
                review["reviewed_comprimento"] or review["reviewed_fit"]
                or review["reviewed_product_type"]):
            review["review_status"] = "reviewed"
        if self._touched or review["review_status"]:
            review["reviewed_at"] = datetime.datetime.now().astimezone().isoformat(
                timespec="seconds")

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
