#!/usr/bin/env python3
"""
Installer Check & Remover
-------------------------
Finds leftover installer files (setup.exe, .msi, etc.) sitting in your Downloads,
Desktop and temp folders, then lets you remove them.

How it works:
  1. It checks in the terminal first and prints what it found.
  2. It opens a window with the list. Everything starts CHECKED.
  3. Click a row to uncheck it (or check it again).
  4. Hit "Remove". Files go to the Recycle Bin, so you can still get them back.
     If a file can't be removed, the window tells you why.

Pure standard library. No installs needed.

Usage:
  python installer_check_remover.py              # check in terminal + open the window
  python installer_check_remover.py --scan       # terminal list only, no window, deletes nothing
  python installer_check_remover.py --folder "D:\\Downloads"   # add another folder to check
"""

import argparse
import os
import re
import shutil
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

__version__ = "1.1.0"

# Always treated as installers
ALWAYS_EXT = {".msi", ".msix", ".msixbundle", ".appx", ".appxbundle", ".dmg", ".pkg", ".deb", ".rpm"}
# .exe is only an installer if the name looks like one (so we don't grab portable apps)
EXE_HINTS = re.compile(r"(setup|install|installer|update|updater|redist|webinstall|_x64|_x86|win64|win32)", re.I)


# ---------------------------------------------------------------------------
# Where to look
# ---------------------------------------------------------------------------

def default_folders(extra=None):
    home = Path.home()
    folders = {"Downloads": home / "Downloads", "Desktop": home / "Desktop",
               "Temp": Path(tempfile.gettempdir())}
    for i, f in enumerate(extra or [], 1):
        folders[f"Extra {i}"] = Path(f)
    return {name: p for name, p in folders.items() if p.is_dir()}


# ---------------------------------------------------------------------------
# "Is it already installed?" check (Windows only, otherwise says Unknown)
# ---------------------------------------------------------------------------

def installed_program_names():
    """Names of installed programs from the Windows uninstall registry keys."""
    if os.name != "nt":
        return None
    import winreg
    names = set()
    sub = r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"
    places = [
        (winreg.HKEY_LOCAL_MACHINE, winreg.KEY_WOW64_64KEY),
        (winreg.HKEY_LOCAL_MACHINE, winreg.KEY_WOW64_32KEY),
        (winreg.HKEY_CURRENT_USER, 0),
    ]
    for hive, flag in places:
        try:
            with winreg.OpenKey(hive, sub, 0, winreg.KEY_READ | flag) as key:
                for i in range(winreg.QueryInfoKey(key)[0]):
                    try:
                        with winreg.OpenKey(key, winreg.EnumKey(key, i)) as k:
                            names.add(winreg.QueryValueEx(k, "DisplayName")[0].lower())
                    except OSError:
                        continue
        except OSError:
            continue
    return names


_NOISE = re.compile(r"(setup|installer|install|update|updater|webinstall|redist|x64|x86|win64|win32|amd64|"
                    r"\d+(\.\d+)*|v\d+|[-_.()])", re.I)


def guess_status(filename, installed):
    """'Installed' if the program name shows up in the installed list, else 'Not found'."""
    if installed is None:
        return "Unknown"
    words = [w.lower() for w in _NOISE.sub(" ", Path(filename).stem).split() if len(w) >= 3]
    if not words:
        return "Not found"
    return "Installed" if any(words[0] in n for n in installed) else "Not found"


# ---------------------------------------------------------------------------
# Scanning
# ---------------------------------------------------------------------------

@dataclass
class Item:
    id: int
    name: str
    path: str
    size: int
    mtime: float
    folder: str
    status: str


def is_installer(path):
    ext = path.suffix.lower()
    if ext in ALWAYS_EXT:
        return True
    return ext == ".exe" and bool(EXE_HINTS.search(path.stem))


def scan(folders, min_age_hours=1.0):
    """Look only at the TOP LEVEL of each folder (no digging through subfolders)."""
    cutoff = time.time() - min_age_hours * 3600
    installed = installed_program_names()
    items = []
    for label, root in folders.items():
        try:
            entries = list(os.scandir(root))
        except OSError:
            continue
        for e in entries:
            try:
                if e.is_symlink() or not e.is_file(follow_symlinks=False):
                    continue
                p = Path(e.path)
                if not is_installer(p):
                    continue
                st = e.stat(follow_symlinks=False)
            except OSError:
                continue
            if st.st_mtime > cutoff:
                continue  # downloaded just now, might be about to run it
            items.append(Item(0, p.name, str(p), st.st_size, st.st_mtime, label, guess_status(p.name, installed)))
    items.sort(key=lambda i: i.size, reverse=True)
    for n, it in enumerate(items):
        it.id = n
    return items


# ---------------------------------------------------------------------------
# Removing (to the Recycle Bin when possible)
# ---------------------------------------------------------------------------

def _recycle_windows(path):
    import ctypes
    from ctypes import wintypes

    class SHFILEOPSTRUCTW(ctypes.Structure):
        _pack_ = 1 if ctypes.sizeof(ctypes.c_void_p) == 4 else 8
        _fields_ = [("hwnd", wintypes.HWND), ("wFunc", wintypes.UINT),
                    ("pFrom", wintypes.LPCWSTR), ("pTo", wintypes.LPCWSTR),
                    ("fFlags", ctypes.c_ushort), ("fAnyOperationsAborted", wintypes.BOOL),
                    ("hNameMappings", ctypes.c_void_p), ("lpszProgressTitle", wintypes.LPCWSTR)]

    FO_DELETE, FOF_SILENT, FOF_NOCONFIRMATION, FOF_ALLOWUNDO, FOF_NOERRORUI = 3, 0x4, 0x10, 0x40, 0x400
    op = SHFILEOPSTRUCTW()
    op.wFunc = FO_DELETE
    op.pFrom = os.path.normpath(path) + "\0"  # Windows wants backslashes and a double null at the end
    op.fFlags = FOF_ALLOWUNDO | FOF_NOCONFIRMATION | FOF_SILENT | FOF_NOERRORUI
    result = ctypes.windll.shell32.SHFileOperationW(ctypes.byref(op))
    if result != 0 or op.fAnyOperationsAborted:
        reasons = {0x78: "access denied", 0x7C: "invalid path", 0x74: "can't recycle a drive root",
                   0x75: "cancelled", 0x79: "path too long", 0x402: "path not found",
                   0x10000: "unspecified error", 0x71: "same file", 0xB7: "already exists"}
        why = reasons.get(result, "unknown")
        if result == 0 and op.fAnyOperationsAborted:
            why = "Windows cancelled it (file may be in use, or too big for the Recycle Bin)"
        raise OSError(f"Recycle Bin refused: {why} (code {hex(result)})")


def _quarantine(path, trash_dir):
    """Non-Windows fallback: move into a folder instead of deleting."""
    trash_dir.mkdir(parents=True, exist_ok=True)
    dest = trash_dir / Path(path).name
    n = 1
    while dest.exists():
        dest = trash_dir / f"{Path(path).stem}_{n}{Path(path).suffix}"
        n += 1
    shutil.move(path, dest)


def remove_items(items, trash_dir=None, permanent=False):
    """
    Returns (removed_count, freed_bytes, failures[(name, reason, path)]).
    permanent=True skips the Recycle Bin and really deletes (used only when you ask for it).
    """
    trash_dir = trash_dir or (Path.home() / ".installer_remover_trash" / time.strftime("%Y%m%d-%H%M%S"))
    removed, freed, failed = 0, 0, []
    for it in items:
        try:
            if not os.path.isfile(it.path) or os.path.islink(it.path):
                failed.append((it.name, "file is gone or not a regular file", it.path))
                continue
            if permanent:
                os.chmod(it.path, 0o666)  # clears read-only
                os.remove(it.path)
            elif os.name == "nt":
                _recycle_windows(it.path)
            else:
                _quarantine(it.path, trash_dir)
            removed += 1
            freed += it.size
        except PermissionError as e:
            failed.append((it.name, f"in use or no permission ({e.strerror or e})", it.path))
        except OSError as e:
            failed.append((it.name, str(e), it.path))
    return removed, freed, failed


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def human_size(n):
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024


def age_text(mtime):
    days = (time.time() - mtime) / 86400
    return f"{days:.0f}d" if days >= 1 else f"{days * 24:.0f}h"


def print_report(items):
    if not items:
        print("No leftover installers found. All clean.")
        return
    print(f"\n{'Size':>10}  {'Age':>4}  {'Status':<10} {'Where':<10} File")
    print("-" * 72)
    for i in items:
        print(f"{human_size(i.size):>10}  {age_text(i.mtime):>4}  {i.status:<10} {i.folder:<10} {i.name}")
    print("-" * 72)
    print(f"{len(items)} installers, {human_size(sum(i.size for i in items))} total\n")


# ---------------------------------------------------------------------------
# The window
# ---------------------------------------------------------------------------

def run_gui(folders, age):
    import tkinter as tk
    from tkinter import messagebox, ttk

    root = tk.Tk()
    root.title(f"Installer Check & Remover v{__version__}")
    root.geometry("960x560")

    items = []        # current scan results
    checked = {}      # row id -> True/False
    reasons = {}      # file path -> why it couldn't be removed

    top = ttk.Frame(root, padding=8)
    top.pack(fill="x")
    ttk.Label(top, text="Leftover installers. Everything starts checked. Click a row to uncheck it.").pack(side="left")
    rescan_btn = ttk.Button(top, text="Rescan")
    rescan_btn.pack(side="right")

    cols = ("sel", "file", "size", "age", "where", "status", "result")
    tree = ttk.Treeview(root, columns=cols, show="headings", selectmode="browse")
    for col, text, width in (("sel", "", 36), ("file", "File", 330), ("size", "Size", 80), ("age", "Age", 50),
                             ("where", "Where", 80), ("status", "Status", 80), ("result", "Result", 260)):
        tree.heading(col, text=text)
        tree.column(col, width=width, anchor="w", stretch=(col in ("file", "result")))
    tree.tag_configure("bad", foreground="#c0392b")
    tree.pack(fill="both", expand=True, padx=8)

    bottom = ttk.Frame(root, padding=8)
    bottom.pack(fill="x")
    status = tk.StringVar(value="")
    ttk.Label(bottom, textvariable=status).pack(side="left")
    remove_btn = ttk.Button(bottom, text="Remove")
    remove_btn.pack(side="right")
    ttk.Button(bottom, text="Select none", command=lambda: set_all(False)).pack(side="right", padx=6)
    ttk.Button(bottom, text="Select all", command=lambda: set_all(True)).pack(side="right")

    def selected():
        return [items[int(r)] for r, v in checked.items() if v]

    def refresh_status():
        sel = selected()
        status.set(f"{len(sel)} of {len(items)} selected ({human_size(sum(i.size for i in sel))})")
        remove_btn.state(["!disabled"] if sel else ["disabled"])

    def set_row(row, value):
        checked[row] = value
        tree.set(row, "sel", "[x]" if value else "[ ]")

    def set_all(value):
        for row in tree.get_children():
            set_row(row, value)
        refresh_status()

    def on_click(event):
        row = tree.identify_row(event.y)
        if row:
            set_row(row, not checked[row])
            refresh_status()

    tree.bind("<Button-1>", on_click)

    def do_scan():
        nonlocal items
        status.set("Scanning...")
        root.update_idletasks()
        items = scan(folders, age)
        tree.delete(*tree.get_children())
        checked.clear()
        for idx, it in enumerate(items):
            why = reasons.get(it.path, "")
            tree.insert("", "end", iid=str(idx), tags=("bad",) if why else (),
                        values=("[x]", it.name, human_size(it.size), age_text(it.mtime), it.folder, it.status, why))
            checked[str(idx)] = True
        if not items:
            status.set("No leftover installers found. All clean.")
            remove_btn.state(["disabled"])
        else:
            refresh_status()

    def note_failures(failed):
        reasons.clear()
        for _name, why, path in failed:
            reasons[path] = why

    def do_remove():
        sel = selected()
        if not sel:
            return
        total = human_size(sum(i.size for i in sel))
        if not messagebox.askyesno("Are you sure?", f"Remove {len(sel)} installers ({total})?\nThey'll go to the Recycle Bin."):
            return
        removed, freed, failed = remove_items(sel)
        note_failures(failed)
        msg = f"Removed {removed} files, freed {human_size(freed)}."
        if not failed:
            messagebox.showinfo("Done", msg)
        else:
            lines = "\n".join(f"- {n}: {w}" for n, w, _ in failed[:8])
            more = f"\n...and {len(failed) - 8} more" if len(failed) > 8 else ""
            ask = (f"{msg}\n\n{len(failed)} couldn't be removed:\n{lines}{more}\n\n"
                   "Delete those PERMANENTLY instead? (skips the Recycle Bin, can't be undone)")
            if messagebox.askyesno("Some files didn't go", ask, icon="warning"):
                paths = {p for _, _, p in failed}
                r2, f2, failed2 = remove_items([i for i in sel if i.path in paths], permanent=True)
                note_failures(failed2)
                extra = f"\n{len(failed2)} still couldn't be removed (see the Result column)." if failed2 else ""
                messagebox.showinfo("Done", f"Permanently deleted {r2} files, freed {human_size(f2)}.{extra}")
        do_scan()

    rescan_btn.config(command=lambda: (reasons.clear(), do_scan()))
    remove_btn.config(command=do_remove)
    do_scan()
    root.mainloop()


# ---------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(description="Find and remove leftover installer files.")
    ap.add_argument("--scan", action="store_true", help="terminal list only, nothing deleted, no window")
    ap.add_argument("--age", type=float, default=1.0, help="skip files newer than this many hours (default 1)")
    ap.add_argument("--folder", action="append", help="extra folder to check (can repeat)")
    ap.add_argument("--version", action="version", version=__version__)
    args = ap.parse_args()

    folders = default_folders(args.folder)
    print(f"Checking: {', '.join(f'{n} ({p})' for n, p in folders.items())}")
    print_report(scan(folders, args.age))

    if not args.scan:
        run_gui(folders, args.age)


if __name__ == "__main__":
    main()
