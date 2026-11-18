# Widle

Windows desktop widget (Python 3.9 + Tkinter, stdlib only) showing monthly profit per business (stored in RM) with a total, and an RM/USD display toggle.

## Building and updating the exe

The exe is a frozen snapshot of the code at build time. Editing the `.py` files does not change an existing exe; you must rebuild.

To release a change:

1. Edit the code (`widle.py`, `tray.py`, ...).
2. Bump the version: change `__version__ = "X.Y.Z"` in `widle.py` (the only place the version lives).
   - Patch `1.2.0 -> 1.2.1`: bug fix or tiny tweak.
   - Minor `1.2.0 -> 1.3.0`: new feature.
   - Major `1.2.0 -> 2.0.0`: big or breaking change (e.g. data file format).
3. Close the running widget: right-click its tray icon -> **Exit**. (The X button only hides it to the tray. The build refuses to run while Widle is open, because Windows locks the exe.)
4. Build: `powershell -ExecutionPolicy Bypass -File .\build.ps1`
5. Start the new exe from the desktop shortcut, then hover the tray icon: the tooltip shows `Widle vX.Y.Z` so you can confirm the new version is the one running.

Quick copy-paste (PowerShell, after editing the code, bumping `__version__` and choosing **Exit** from the tray icon):

```powershell
cd C:\Users\AHUSSIN\Projects\widle
powershell -ExecutionPolicy Bypass -File .\build.ps1
```

When it finishes it prints `Built ...\dist\Widle-vX.Y.Z.exe`. If it prints an error instead, nothing was changed: either Widle is still running (Exit it first) or a test failed (the failing test is shown above the error).

What `build.ps1` does: reads the version from `widle.py`, runs the unit tests (a failing test stops the build), generates the icon and the Windows file-version info, runs PyInstaller (pinned in `requirements-build.txt`, installed only in `.venv-build`) and writes `dist\Widle-vX.Y.Z.exe`, then points the desktop shortcut `Widle.lnk` (if it exists) at the new exe.

Notes:
- Old versions stay in `dist\` so you can roll back; delete the ones you don't need (and the old unversioned `dist\Widle.exe`).
- Your data lives in `%APPDATA%\Widle\data.json`, outside the exe, so rebuilding or switching versions never loses it.
- Right-click the exe -> Properties -> Details shows the file and product version.
- Try a change without building: `python widle.py` (or `pythonw Widle.pyw`). Exit the exe first, otherwise the single-instance lock just brings the exe's window forward.
- The exe is unsigned, so some antivirus products may flag it as a false positive.

## Development

- Run (no console): `pythonw Widle.pyw` (or double-click `Widle.pyw`)
- Run (with console, for debugging): `python widle.py`
- Tests: `python -m unittest -v test_widle`
- Display size: `SCALE` in `widle.py` (currently 1.2) scales all fonts and spacing; the widget stays on top of other windows
- Amount colours: green above zero, white at exactly zero, red below zero
- Tray icon: `tray.py` (ctypes Shell_NotifyIcon, hidden window class `WidleTrayWindow`; icon pixels generated in code, also written to `build\widle.ico` for the exe). Widget X hides to tray; tray left-click shows; right-click menu Show/Hide/Exit. Tray callbacks only enqueue events; `Widget._poll` handles them on the Tk side
- Single instance: a named mutex (`Local\WidleDesktopWidget`); a second launch posts `WM_SHOW` to the existing tray window and exits
- Check running: `Get-Process Widle*` (the exe; onefile shows 2 processes) or `pythonw.exe` with `Widle.pyw` in its command line
- Data file: `%APPDATA%\Widle\data.json` (`businesses` list, `profits` as `{"YYYY-MM": {business: "RM amount"}}`, cached rate, display currency, window position)
- Exchange rate: Frankfurter API (ECB rates, no key), `https://api.frankfurter.app/latest?from=MYR&to=USD`, refreshed on start, every 6h, and via the refresh button
- Note: `curl` fails on this machine (schannel exit 35); test HTTP with Python `urllib` instead
