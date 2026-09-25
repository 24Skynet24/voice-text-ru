"""Точка входа для PyInstaller.

`src/voicetext_ru/__main__.py` использует относительный импорт и работает при
запуске `python -m voicetext_ru`. PyInstaller же запускает стартовый файл как
самостоятельный скрипт, без пакета-родителя, и относительный импорт в нём
завершается ошибкой ещё до настройки журналирования. Поэтому у сборки свой
стартовый файл с абсолютным импортом.
"""

from __future__ import annotations

from voicetext_ru.app import main

if __name__ == "__main__":
    raise SystemExit(main())
