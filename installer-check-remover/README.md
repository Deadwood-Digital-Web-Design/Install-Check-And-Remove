# Installer Check & Remover

Finds leftover installer files (setup.exe, .msi, etc.) and lets you remove them from a simple window.

No installs. Pure Python standard library.

## How it works

1. It checks in the terminal first and prints what it found.
2. It opens a window with the list. Everything starts checked.
3. Click a row to uncheck it (click again to check it).
4. Hit **Remove**. Files go to the Recycle Bin, so you can get them back.

If a file can't be removed, the window shows the reason in the Result column and offers to delete it permanently instead (it asks first, and permanent can't be undone).

## What it looks at

Top level of your Downloads, Desktop and Temp folders (no digging through subfolders). Add more with `--folder`.

It picks up `.msi`, `.msix`, `.appx`, `.dmg`, `.pkg`, `.deb`, `.rpm`, and `.exe` files whose names look like installers (setup, install, update, x64, etc.). Portable `.exe` apps are left alone.

On Windows each file gets a status: **Installed** (the program shows up in your installed programs list) or **Not found** (it doesn't). It's a guess based on the file name, so check before removing anything you still need.

## Safety

- Files newer than 1 hour are skipped (you might be about to run them). Change with `--age`.
- Removed files go to the Recycle Bin on Windows. On other systems they move to `~/.installer_remover_trash`.
- Only the files listed in the window can be removed, and it always asks "Are you sure?" first.

## Run it

**Windows:** double-click `Run Installer Check & Remover.bat`

**Terminal:**

```
python installer_check_remover.py              # check in terminal + open the window
python installer_check_remover.py --scan       # terminal list only, deletes nothing
python installer_check_remover.py --folder "D:\Downloads"
```

Needs Python 3.8 or newer. The window uses tkinter, which ships with Python on Windows and macOS.

## Tests

```
python -m unittest -v
```

## License

MIT
