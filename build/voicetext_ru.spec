# -*- mode: python ; coding: utf-8 -*-
"""Сборка Windows-приложения (ТЗ §2, §39).

Собирается каталог с `Voice Text RU.exe`, внутри которого уже есть интерпретатор
Python и все библиотеки. Конечному пользователю ничего доустанавливать не нужно.

Запуск:  pyinstaller build/voicetext_ru.spec --noconfirm --clean
"""

import os
from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_submodules

PROJECT_ROOT = Path(SPECPATH).resolve().parent
ICON_PATH = PROJECT_ROOT / "src" / "voicetext_ru" / "resources" / "app.ico"

binaries = []
datas = []
hiddenimports = []

# Иконка нужна и в ресурсах exe (Проводник, Alt+Tab), и рядом с приложением,
# чтобы код мог найти её через resource_path() и выставить как QWindow/QApplication icon.
if ICON_PATH.is_file():
    datas.append((str(ICON_PATH), "resources"))

# Нативные библиотеки времени выполнения: движок вывода, аудио, декодеры.
# collect_all забирает и DLL, и файлы данных (например, модель Silero VAD).
for package in ("ctranslate2", "faster_whisper", "onnxruntime", "av", "sounddevice", "tokenizers"):
    package_datas, package_binaries, package_hidden = collect_all(package)
    datas += package_datas
    binaries += package_binaries
    hiddenimports += package_hidden

hiddenimports += collect_submodules("huggingface_hub")
# Модули интерфейса импортируются внутри функций (чтобы ускорить старт),
# поэтому перечисляем пакет целиком.
hiddenimports += collect_submodules("voicetext_ru")

# Qt-модули, которые приложению не нужны: без их отсечения сборка вырастает
# на сотни мегабайт (браузерный движок, 3D, мультимедиа, отладка QML).
excludes = [
    "PySide6.QtWebEngineCore",
    "PySide6.QtWebEngineWidgets",
    "PySide6.QtWebEngineQuick",
    "PySide6.QtQuick",
    "PySide6.QtQuick3D",
    "PySide6.QtQml",
    "PySide6.Qt3DCore",
    "PySide6.Qt3DRender",
    "PySide6.QtCharts",
    "PySide6.QtDataVisualization",
    "PySide6.QtMultimedia",
    "PySide6.QtMultimediaWidgets",
    "PySide6.QtBluetooth",
    "PySide6.QtPositioning",
    "PySide6.QtSql",
    "PySide6.QtTest",
    "PySide6.QtDesigner",
    "PySide6.QtHelp",
    "PySide6.QtPdf",
    "PySide6.QtPdfWidgets",
    # Тяжёлые научные пакеты, которые иногда подтягиваются транзитивно.
    "torch",
    "tensorflow",
    "matplotlib",
    "scipy",
    "pandas",
    "IPython",
    "tkinter",
    "pytest",
]

a = Analysis(
    [str(PROJECT_ROOT / "build" / "entrypoint.py")],
    pathex=[str(PROJECT_ROOT / "src")],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Voice Text RU",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,  # UPX ломает подписанные DLL и вызывает ложные срабатывания антивирусов
    # Обычная сборка — оконная, без консоли. Для диагностики проблем самой
    # сборки её можно собрать с консолью: set VOICETEXT_BUILD_CONSOLE=1
    console=bool(os.environ.get("VOICETEXT_BUILD_CONSOLE")),
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(ICON_PATH) if ICON_PATH.is_file() else None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="VoiceTextRU",
)
