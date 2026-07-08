"""Image loading/scaling for the Tkinter UI (Pillow does the decoding).

scale_to_fit is a pure function (offline-testable): it computes the largest size
that fits inside a box while PRESERVING the aspect ratio — the image is never
cropped, only scaled down (or shown 1:1 with scrollbars in "real size" mode).
"""
from __future__ import annotations

import os
from typing import Optional, Tuple


def scale_to_fit(width: int, height: int, max_width: int,
                 max_height: int) -> Tuple[int, int, float]:
    """Return (new_width, new_height, scale) fitting (width, height) inside the box.
    Aspect ratio is preserved; images smaller than the box are NOT upscaled."""
    if width <= 0 or height <= 0 or max_width <= 0 or max_height <= 0:
        return max(1, width), max(1, height), 1.0
    scale = min(max_width / width, max_height / height, 1.0)
    return max(1, round(width * scale)), max(1, round(height * scale)), scale


def load_pil(path: Optional[str]):
    """Return (PIL.Image_or_None, info_text). Never raises: a missing/corrupt image
    yields (None, reason) so the UI shows a placeholder instead of crashing."""
    if not path:
        return None, "sem imagem"
    if not os.path.exists(path):
        return None, f"imagem não encontrada:\n{os.path.basename(path)}"
    try:
        from PIL import Image
        with Image.open(path) as image:
            return image.convert("RGB"), os.path.basename(path)
    except Exception as exc:                                # corrupt file etc.
        return None, f"falha ao abrir imagem: {type(exc).__name__}"


def pil_to_photo(pil_image, width: int, height: int):
    """Resize a PIL image and wrap it as a Tk PhotoImage (GUI-side only)."""
    from PIL import Image, ImageTk
    resized = pil_image.resize((max(1, width), max(1, height)), Image.LANCZOS)
    return ImageTk.PhotoImage(resized)


def load_scaled_photo(path: Optional[str], max_width: int, max_height: int):
    """Backwards-compatible helper: load + fit + PhotoImage in one call."""
    pil_image, info = load_pil(path)
    if pil_image is None:
        return None, info
    width, height, _ = scale_to_fit(pil_image.width, pil_image.height,
                                    max_width, max_height)
    return pil_to_photo(pil_image, width, height), info
