"""Image loading for the Tkinter UI (Pillow does the JPEG decoding/scaling)."""
from __future__ import annotations

import os
from typing import Optional, Tuple


def load_scaled_photo(path: Optional[str], max_width: int, max_height: int):
    """Return (PhotoImage_or_None, info_text). Never raises: a missing/corrupt image
    yields (None, reason) so the UI shows a placeholder instead of crashing."""
    if not path:
        return None, "sem imagem"
    if not os.path.exists(path):
        return None, f"imagem não encontrada:\n{os.path.basename(path)}"
    try:
        from PIL import Image, ImageTk
        with Image.open(path) as image:
            image = image.convert("RGB")
            image.thumbnail((max_width, max_height))
            return ImageTk.PhotoImage(image), f"{os.path.basename(path)}"
    except Exception as exc:                                # corrupt file etc.
        return None, f"falha ao abrir imagem: {type(exc).__name__}"
