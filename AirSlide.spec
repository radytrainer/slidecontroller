# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller build definition for AirSlide.

Two forms (environment variable AIRSLIDE_BUILD):

* "folder" (default) - dist\\AirSlide\\AirSlide.exe plus its files. This is what the
  installer (installer\\AirSlide.iss) installs. Antivirus programs trust it much
  more than a single file, which unpacks itself to a temporary folder on every start.
* "onefile"          - one portable dist\\AirSlide.exe.

Build with:   powershell -ExecutionPolicy Bypass -File build.ps1            (installer)
              powershell -ExecutionPolicy Bypass -File build.ps1 -SingleFile
"""

import os
import re
from pathlib import Path

from PyInstaller.utils.hooks import collect_dynamic_libs, collect_submodules
from PyInstaller.utils.win32.versioninfo import (
    FixedFileInfo,
    StringFileInfo,
    StringStruct,
    StringTable,
    VarFileInfo,
    VarStruct,
    VSVersionInfo,
)

ROOT = Path(SPECPATH)
VERSION = re.search(r'APP_VERSION = "([\d.]+)"', (ROOT / "config.py").read_text(encoding="utf-8")).group(1)
VERSION_TUPLE = tuple(int(p) for p in (VERSION.split(".") + ["0"] * 4)[:4])

# The MediaPipe hand and pose models are bundled, so the .exe works offline.
datas = [
    (str(ROOT / "assets" / "models" / "hand_landmarker.task"), "assets/models"),
    (str(ROOT / "assets" / "models" / "pose_landmarker_lite.task"), "assets/models"),
]

# MediaPipe's native library (mediapipe/tasks/c/libmediapipe.dll) is loaded via
# importlib.resources, so it must keep its package path inside the bundle.
binaries = collect_dynamic_libs("mediapipe")

hiddenimports = (
    collect_submodules("mediapipe.tasks.python")
    + ["mediapipe.tasks.c", "win32timezone",
       "PySide6.QtMultimedia"]           # imported lazily by src/subtitles/microphone.py
)

excludes = [
    "tkinter", "_tkinter",          # not used (Qt GUI)
    "pytest", "ruff", "PyInstaller",
    "IPython", "jupyter", "notebook",
    "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.Qt3DCore",
    # QtMultimedia is NOT excluded: the subtitles read the microphone with it.
    "PySide6.QtQuick", "PySide6.QtQml", "PySide6.QtCharts",
    "PySide6.QtDataVisualization", "PySide6.QtPdf", "PySide6.QtBluetooth",
]

a = Analysis(
    [str(ROOT / "main.py")],
    pathex=[str(ROOT)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=excludes,
    noarchive=False,
)
pyz = PYZ(a.pure)

version_info = VSVersionInfo(
    ffi=FixedFileInfo(filevers=VERSION_TUPLE, prodvers=VERSION_TUPLE),
    kids=[
        StringFileInfo([StringTable("040904B0", [
            StringStruct("ProductName", "AirSlide"),
            StringStruct("FileDescription", "AirSlide - Present Without Touching"),
            StringStruct("FileVersion", VERSION),
            StringStruct("ProductVersion", VERSION),
            StringStruct("OriginalFilename", "AirSlide.exe"),
            StringStruct("InternalName", "AirSlide"),
        ])]),
        VarFileInfo([VarStruct("Translation", [0x0409, 1200])]),
    ],
)

icon = ROOT / "assets" / "airslide.ico"
ONE_FILE = os.environ.get("AIRSLIDE_BUILD", "folder").lower() == "onefile"

common = dict(
    name="AirSlide",
    console=False,               # windowed app; --check etc. attach to the calling terminal
    icon=str(icon) if icon.exists() else None,
    version=version_info,
    upx=False,                   # UPX-compressed DLLs often trigger antivirus false positives
)

if ONE_FILE:
    exe = EXE(pyz, a.scripts, a.binaries, a.datas, [], runtime_tmpdir=None, **common)
else:
    exe = EXE(pyz, a.scripts, [], exclude_binaries=True, **common)
    coll = COLLECT(exe, a.binaries, a.datas, name="AirSlide", upx=False)
