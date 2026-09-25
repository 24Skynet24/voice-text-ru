"""Точка входа приложения."""

from __future__ import annotations

import ctypes
import logging
import sys

from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication, QMessageBox

from . import APP_ID, APP_NAME, APP_VERSION
from .logging_setup import install_excepthook, setup_logging
from .paths import resource_path
from .settings import Settings

logger = logging.getLogger(__name__)


def _set_windows_app_id() -> None:
    """Собственный идентификатор приложения — отдельная иконка на панели задач."""
    if sys.platform != "win32":
        return
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(f"Anonymous.{APP_ID}")
    except Exception:
        logger.debug("Не удалось задать AppUserModelID", exc_info=True)


def _run_selftest(audio_path: str | None) -> int:
    """Проверяет установку без запуска интерфейса.

    Нужна, чтобы отличить неполадки сборки (не загрузились нативные библиотеки)
    от проблем с микрофоном или моделью. В собранном приложении консоли нет,
    поэтому отчёт пишется в файл и в журнал работы.
    """
    from .asr.engine import FasterWhisperEngine, cuda_device_count, default_cpu_threads
    from .audio.devices import list_input_devices
    from .paths import app_data_dir, is_frozen
    from .settings import Settings

    lines: list[str] = [
        f"{APP_NAME} {APP_VERSION}",
        f"Режим: {'собранное приложение' if is_frozen() else 'исходный код'}",
        f"Python: {sys.version.split()[0]}",
    ]

    try:
        devices = list_input_devices()
        lines.append(f"Устройств ввода найдено: {len(devices)}")
        lines += [f"  · {device.display_name} ({device.host_api})" for device in devices]
    except Exception as error:
        lines.append(f"ОШИБКА при поиске устройств: {error}")

    lines.append(f"Видеокарт NVIDIA: {cuda_device_count()}")
    lines.append(f"Потоков ЦП для распознавания: {default_cpu_threads()}")

    settings = Settings.load()
    try:
        engine = FasterWhisperEngine(
            settings.model_id, device_preference=settings.compute_device, language=settings.language
        )
    except Exception as error:
        lines.append(f"ОШИБКА загрузки модели: {error}")
    else:
        lines.append(f"Модель загружена: {engine.info.summary}")
        if audio_path:
            try:
                import wave

                import numpy as np

                with wave.open(audio_path, "rb") as source:
                    raw = source.readframes(source.getnframes())
                    rate = source.getframerate()
                audio = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
                lines.append(f"Файл: {audio_path} ({audio.size / rate:.1f} с, {rate} Гц)")
                segments = engine.transcribe(audio, fast=False)
                text = " ".join(segment.text.strip() for segment in segments)
                lines.append(f"Распознано: {text or '(ничего)'}")
            except Exception as error:
                lines.append(f"ОШИБКА распознавания: {error}")
        engine.close()

    report = "\n".join(lines)
    logger.info("Проверка установки:\n%s", report)
    destination = app_data_dir() / "selftest.txt"
    try:
        destination.write_text(report, encoding="utf-8")
    except OSError:
        logger.exception("Не удалось записать отчёт проверки")
    if sys.stdout is not None:
        print(report)
    return 0 if "ОШИБКА" not in report else 1


def main() -> int:
    """Запускает приложение и возвращает код завершения."""
    setup_logging(verbose="--verbose" in sys.argv)
    install_excepthook()

    if "--selftest" in sys.argv:
        index = sys.argv.index("--selftest")
        audio = sys.argv[index + 1] if len(sys.argv) > index + 1 else None
        return _run_selftest(audio if audio and not audio.startswith("--") else None)

    _set_windows_app_id()

    QApplication.setAttribute(Qt.ApplicationAttribute.AA_DontUseNativeMenuBar, False)
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationVersion(APP_VERSION)
    app.setOrganizationName(APP_ID)
    # Запись не должна прерываться, когда пользователь закрывает диалоги (ТЗ §6).
    app.setQuitOnLastWindowClosed(True)

    icon_path = resource_path("resources/app.ico")
    if icon_path.is_file():
        app.setWindowIcon(QIcon(str(icon_path)))
    else:
        logger.warning("Файл иконки не найден: %s", icon_path)

    settings = Settings.load()

    try:
        from .ui.main_window import MainWindow

        window = MainWindow(settings)
    except Exception as error:
        logger.exception("Не удалось создать главное окно")
        QMessageBox.critical(
            None,
            APP_NAME,
            f"Не удалось запустить приложение:\n{error}\n\n"
            "Подробности записаны в журнал работы.",
        )
        return 1

    window.show()
    exit_code = app.exec()
    logger.info("Завершение работы с кодом %d", exit_code)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
