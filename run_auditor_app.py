#!/usr/bin/env python3
"""Entrypoint for the Fashion Auditor desktop app (dev mode AND PyInstaller build).

Package-dir resolution order:
  1. --package-dir argument;
  2. frozen executable (PyInstaller): the folder the executable lives in — so the
     auditor just double-clicks FashionAuditor inside the package;
  3. current working directory, if it looks like a package.

Dev usage:
  python run_auditor_app.py --package-dir <auditor-package-folder>

Build (run on the TARGET OS — a Windows .exe must be built on Windows):
  pyinstaller --onefile --windowed --name FashionAuditor --paths . run_auditor_app.py
"""
from __future__ import annotations

import argparse
import os
import sys

if not getattr(sys, "frozen", False):                       # dev mode: repo imports
    ROOT = os.path.dirname(os.path.abspath(__file__))       # this repo's root
    if ROOT not in sys.path:
        sys.path.insert(0, ROOT)

from auditor_app.app import AuditorApp  # noqa: E402  (package lives at repo root)


def resolve_package_dir(cli_value: str = None) -> str:
    if cli_value:
        return cli_value
    if getattr(sys, "frozen", False):                       # double-clicked executable
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.getcwd()


def main() -> None:
    ap = argparse.ArgumentParser(description="Fashion Auditor — offline human review app.")
    ap.add_argument("--package-dir", default=None)
    args = ap.parse_args()
    package_dir = resolve_package_dir(args.package_dir)
    try:
        app = AuditorApp(package_dir)
    except FileNotFoundError as exc:
        message = (f"{exc}\n\nAbra o FashionAuditor de dentro da pasta do pacote "
                   "(a pasta que contém data/review_items.jsonl), ou use "
                   "--package-dir <pasta>.")
        try:                                                # friendly popup when possible
            import tkinter as tk
            from tkinter import messagebox
            root = tk.Tk(); root.withdraw()
            messagebox.showerror("Pacote não encontrado", message)
            root.destroy()
        except Exception:
            pass
        sys.exit(message)
    app.run()


if __name__ == "__main__":
    main()
