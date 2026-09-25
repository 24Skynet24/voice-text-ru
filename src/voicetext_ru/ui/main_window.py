"""Главное окно: редактор документа и управление записью (ТЗ §30, §31).

Окно связывает документ, контроллер распознавания и автосохранение.
Вся работа с потоками остаётся в `RecognitionController`; здесь — только
реакция на сигналы и состояние интерфейса.
"""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QByteArray, QCoreApplication, QEventLoop, QTimer, QUrl
from PySide6.QtGui import QAction, QCloseEvent, QDesktopServices, QKeySequence
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from .. import APP_NAME, APP_VERSION
from ..audio.devices import list_input_devices
from ..controller import RecognitionController
from ..core.autosave import AutoSaveManager
from ..core.document import DocumentError, DocumentManager
from ..core.hotkey import GlobalHotkeyManager
from ..core.state import AppState
from ..paths import documents_dir, log_file
from ..settings import Settings
from .editor import DocumentEditor
from .level_meter import LevelMeter
from .settings_dialog import SettingsDialog
from .theme import apply_dim
from .transcript_inserter import TranscriptInserter

logger = logging.getLogger(__name__)

_FILE_FILTER = "Текстовые файлы (*.txt);;Все файлы (*.*)"
_SHUTDOWN_EVENT_PASSES = 3

_RECORD_IDLE_STYLE = """
QPushButton {
    padding: 8px 20px;
    font-weight: 600;
    border: 1px solid palette(mid);
    border-radius: 4px;
}
QPushButton:hover:enabled { border-color: palette(highlight); }
QPushButton:disabled { color: palette(mid); }
"""

_RECORD_ACTIVE_STYLE = """
QPushButton {
    padding: 8px 20px;
    font-weight: 600;
    color: white;
    background-color: #c0392b;
    border: 1px solid #a5342a;
    border-radius: 4px;
}
QPushButton:hover { background-color: #d04434; }
"""


class MainWindow(QMainWindow):
    """Основное окно приложения."""

    def __init__(self, settings: Settings) -> None:
        super().__init__()
        self._settings = settings
        self._document = DocumentManager()
        self._closing = False

        self.setWindowTitle(APP_NAME)
        self.resize(980, 720)

        self._editor = DocumentEditor(self)
        self._inserter = TranscriptInserter(self._editor)
        self._controller = RecognitionController(settings, self)
        self._autosave = AutoSaveManager(
            self._document, self._editor.toPlainText, settings.autosave_interval_ms, self
        )
        self._hotkey = GlobalHotkeyManager(self)

        self._build_ui()
        self._build_menu()
        self._connect_signals()

        self._restore_geometry()
        self._apply_state(AppState.NO_DOCUMENT)
        self._autosave.start()

        if settings.preload_model:
            QTimer.singleShot(0, self._controller.preload_model)
        # Горячая клавиша регистрируется после появления окна: нужен его HWND.
        QTimer.singleShot(0, self._register_hotkey)

    # ---------------------------------------------------------------- #
    # Построение интерфейса
    # ---------------------------------------------------------------- #

    def _build_ui(self) -> None:
        central = QWidget(self)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self._build_control_panel(central))
        layout.addWidget(self._editor, stretch=1)
        self.setCentralWidget(central)

        self._state_label = QLabel(AppState.NO_DOCUMENT.label, self)
        self._engine_label = QLabel("Модель не загружена", self)
        self._saved_label = QLabel("", self)
        apply_dim(self._engine_label, self._saved_label)

        status = self.statusBar()
        status.addWidget(self._state_label, 1)
        status.addPermanentWidget(self._saved_label)
        status.addPermanentWidget(self._engine_label)

    def _build_control_panel(self, parent: QWidget) -> QWidget:
        panel = QFrame(parent)
        panel.setFrameShape(QFrame.Shape.NoFrame)
        panel.setAutoFillBackground(True)

        layout = QHBoxLayout(panel)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(12)

        self._new_button = QPushButton("Создать", panel)
        self._open_button = QPushButton("Открыть", panel)
        self._save_button = QPushButton("Сохранить", panel)
        for button in (self._new_button, self._open_button, self._save_button):
            button.setMinimumWidth(96)
            layout.addWidget(button)

        layout.addSpacing(8)

        self._record_button = QPushButton("● Запись", panel)
        self._record_button.setMinimumWidth(150)
        self._record_button.setStyleSheet(_RECORD_IDLE_STYLE)
        layout.addWidget(self._record_button)

        layout.addSpacing(16)
        layout.addWidget(QLabel("Микрофон:", panel))

        self._device_combo = QComboBox(panel)
        self._device_combo.setMinimumWidth(220)
        self._device_combo.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        self._reload_devices()
        layout.addWidget(self._device_combo)

        self._level_meter = LevelMeter(panel)
        self._level_meter.setMinimumWidth(160)
        layout.addWidget(self._level_meter, stretch=1)

        separator = QFrame(parent)
        separator.setFrameShape(QFrame.Shape.HLine)
        separator.setFrameShadow(QFrame.Shadow.Sunken)

        container = QWidget(parent)
        container_layout = QVBoxLayout(container)
        container_layout.setContentsMargins(0, 0, 0, 0)
        container_layout.setSpacing(0)
        container_layout.addWidget(panel)
        container_layout.addWidget(separator)
        return container

    def _build_menu(self) -> None:
        file_menu = self.menuBar().addMenu("&Файл")
        self._action_new = _action(self, "Создать…", QKeySequence.StandardKey.New, self._on_new)
        self._action_open = _action(self, "Открыть…", QKeySequence.StandardKey.Open, self._on_open)
        self._action_save = _action(self, "Сохранить", QKeySequence.StandardKey.Save, self._on_save)
        self._action_save_as = _action(
            self, "Сохранить как…", QKeySequence.StandardKey.SaveAs, self._on_save_as
        )
        action_exit = _action(self, "Выход", QKeySequence.StandardKey.Quit, self.close)
        file_menu.addActions([self._action_new, self._action_open])
        file_menu.addSeparator()
        file_menu.addActions([self._action_save, self._action_save_as])
        file_menu.addSeparator()
        file_menu.addAction(action_exit)

        edit_menu = self.menuBar().addMenu("&Правка")
        edit_menu.addAction(_action(self, "Отменить", QKeySequence.StandardKey.Undo, self._editor.undo))
        edit_menu.addAction(_action(self, "Повторить", QKeySequence.StandardKey.Redo, self._editor.redo))
        edit_menu.addSeparator()
        edit_menu.addAction(_action(self, "Вырезать", QKeySequence.StandardKey.Cut, self._editor.cut))
        edit_menu.addAction(_action(self, "Копировать", QKeySequence.StandardKey.Copy, self._editor.copy))
        edit_menu.addAction(_action(self, "Вставить", QKeySequence.StandardKey.Paste, self._editor.paste))
        edit_menu.addSeparator()
        edit_menu.addAction(
            _action(self, "Выделить всё", QKeySequence.StandardKey.SelectAll, self._editor.selectAll)
        )
        edit_menu.addAction(_action(self, "Копировать весь текст", None, self._on_copy_all))

        settings_menu = self.menuBar().addMenu("&Настройки")
        settings_menu.addAction(_action(self, "Параметры…", None, self._on_settings))

        help_menu = self.menuBar().addMenu("&Справка")
        help_menu.addAction(_action(self, "Открыть журнал работы", None, self._on_open_log))
        help_menu.addAction(_action(self, "О программе", None, self._on_about))

    def _connect_signals(self) -> None:
        self._new_button.clicked.connect(self._on_new)
        self._open_button.clicked.connect(self._on_open)
        self._save_button.clicked.connect(self._on_save)
        self._record_button.clicked.connect(self._on_toggle_record)
        self._device_combo.currentIndexChanged.connect(self._on_device_changed)

        self._editor.textChanged.connect(self._on_text_changed)

        self._controller.stateChanged.connect(self._apply_state)
        self._controller.partialReady.connect(self._on_partial)
        self._controller.textCommitted.connect(self._on_commit)
        self._controller.errorOccurred.connect(self._on_error)
        self._controller.warningRaised.connect(self._on_warning)
        self._controller.engineReady.connect(self._on_engine_ready)
        self._controller.levelChanged.connect(self._level_meter.set_level)
        self._controller.recordingFinished.connect(self._on_recording_finished)

        self._autosave.saved.connect(self._on_autosaved)
        self._autosave.failed.connect(self._on_error)

        self._hotkey.activated.connect(self._on_hotkey)

    # ---------------------------------------------------------------- #
    # Документ
    # ---------------------------------------------------------------- #

    def _on_new(self) -> None:
        """Создаёт документ: имя и расположение выбирает пользователь (ТЗ §4.1)."""
        if self._controller.is_recording or not self._confirm_discard():
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Создать документ", str(self._default_dir() / "документ.txt"), _FILE_FILTER
        )
        if not path:
            return
        try:
            self._document.create(_with_txt_suffix(Path(path)))
        except DocumentError as error:
            self._show_error(str(error))
            return

        self._editor.set_document_text("")
        self._after_document_opened()

    def _on_open(self) -> None:
        if self._controller.is_recording or not self._confirm_discard():
            return
        path, _ = QFileDialog.getOpenFileName(
            self, "Открыть документ", str(self._default_dir()), _FILE_FILTER
        )
        if not path:
            return
        try:
            text = self._document.open(Path(path))
        except DocumentError as error:
            self._show_error(str(error))
            return

        self._editor.set_document_text(text)
        self._after_document_opened()

    def _after_document_opened(self) -> None:
        assert self._document.path is not None
        self._settings.last_directory = str(self._document.path.parent)
        # Состояние хранит контроллер, а интерфейс обновляется по его сигналу.
        self._controller.set_state(AppState.READY)
        self._apply_state(self._controller.state)
        self._update_title()
        self._editor.setFocus()
        self._status(f"Документ открыт: {self._document.path.name}")

    def _on_save(self) -> bool:
        if not self._document.is_open:
            return self._on_save_as()
        try:
            self._document.save(self._editor.toPlainText())
        except DocumentError as error:
            self._show_error(str(error))
            return False
        self._on_autosaved()
        self._update_title()
        return True

    def _on_save_as(self) -> bool:
        suggested = self._document.path or (self._default_dir() / "документ.txt")
        path, _ = QFileDialog.getSaveFileName(
            self, "Сохранить документ", str(suggested), _FILE_FILTER
        )
        if not path:
            return False
        try:
            self._document.save_as(_with_txt_suffix(Path(path)), self._editor.toPlainText())
        except DocumentError as error:
            self._show_error(str(error))
            return False
        self._settings.last_directory = str(Path(path).parent)
        self._apply_state(self._controller.state)
        self._on_autosaved()
        self._update_title()
        return True

    def _on_copy_all(self) -> None:
        """Копирует весь текст — типичный финал сценария диктовки (ТЗ §26)."""
        cursor = self._editor.textCursor()
        self._editor.selectAll()
        self._editor.copy()
        self._editor.setTextCursor(cursor)
        self._status("Весь текст скопирован в буфер обмена")

    def _on_text_changed(self) -> None:
        if not self._document.is_open:
            return
        self._document.set_modified(True)
        self._autosave.mark_dirty()
        self._update_title()

    # ---------------------------------------------------------------- #
    # Запись
    # ---------------------------------------------------------------- #

    def _on_toggle_record(self) -> None:
        state = self._controller.state
        if state in (AppState.RECORDING, AppState.PROCESSING):
            self._controller.stop()
            return
        if state is AppState.LOADING_MODEL:
            return
        self._start_recording()

    def _start_recording(self) -> None:
        if not self._document.is_open:
            # Требование ТЗ §4: без документа запись невозможна.
            self._show_warning("Сначала создайте или откройте документ.")
            return
        self._inserter.begin()
        self._controller.start(context=self._inserter.context_text())

    def _on_hotkey(self) -> None:
        """Глобальное сочетание клавиш (ТЗ §7)."""
        logger.info("Сработала глобальная горячая клавиша")
        if not self._document.is_open:
            # Окно может быть неактивным, поэтому сначала показываем его.
            self._activate_window()
            self._show_warning("Сначала создайте или откройте документ.")
            return
        self._on_toggle_record()

    def _on_partial(self, text: str) -> None:
        self._inserter.set_partial(text)

    def _on_commit(self, text: str) -> None:
        self._inserter.commit(text)
        # Фиксация фразы — момент, когда есть что сохранять; интервал
        # выдерживает таймер автосохранения (ТЗ §14).
        self._autosave.mark_dirty()

    def _on_recording_finished(self) -> None:
        self._inserter.end()
        self._level_meter.set_active(False)
        self._level_meter.set_level(0.0)
        if self._document.is_open:
            self._autosave.save_now(force=True)  # запись остановлена — сохраняем сразу
        if not self._closing:
            self._status("Запись остановлена")

    # ---------------------------------------------------------------- #
    # Настройки и устройства
    # ---------------------------------------------------------------- #

    def _reload_devices(self) -> None:
        self._device_combo.blockSignals(True)
        try:
            self._device_combo.clear()
            self._device_combo.addItem("По умолчанию", None)
            for device in list_input_devices():
                self._device_combo.addItem(device.display_name, device.key)
            index = self._device_combo.findData(self._settings.microphone_key)
            self._device_combo.setCurrentIndex(max(0, index))
        finally:
            self._device_combo.blockSignals(False)

    def _on_device_changed(self) -> None:
        self._settings.microphone_key = self._device_combo.currentData()
        self._settings.save()
        if self._controller.is_recording:
            self._status("Новый микрофон будет использован при следующей записи")

    def _on_settings(self) -> None:
        dialog = SettingsDialog(self._settings, self)
        if dialog.exec() != SettingsDialog.DialogCode.Accepted:
            return

        new_settings = dialog.result_settings()
        hotkey_changed = (
            new_settings.hotkey != self._settings.hotkey
            or new_settings.hotkey_enabled != self._settings.hotkey_enabled
        )

        self._settings = new_settings
        self._settings.save()
        self._controller.apply_settings(new_settings)
        self._autosave.set_interval(new_settings.autosave_interval_ms)
        self._reload_devices()
        if hotkey_changed:
            self._register_hotkey()
        if self._controller.state is AppState.ERROR:
            self._apply_state(AppState.READY if self._document.is_open else AppState.NO_DOCUMENT)
        self._status("Настройки сохранены")

    def _register_hotkey(self) -> None:
        self._hotkey.unregister()
        if not self._settings.hotkey_enabled:
            return
        error = self._hotkey.register(int(self.winId()), self._settings.hotkey)
        if error:
            self._show_warning(error)
        else:
            self._status(f"Горячая клавиша: {self._hotkey.sequence}")

    # ---------------------------------------------------------------- #
    # Состояние интерфейса
    # ---------------------------------------------------------------- #

    def _apply_state(self, state: AppState) -> None:
        """Приводит интерфейс в соответствие состоянию приложения (ТЗ §31)."""
        if state is AppState.READY and not self._document.is_open:
            state = AppState.NO_DOCUMENT

        self._state_label.setText(state.label)
        recording = state is AppState.RECORDING
        processing = state is AppState.PROCESSING
        loading = state is AppState.LOADING_MODEL

        self._record_button.setEnabled(self._document.is_open and not loading)
        self._record_button.setText("■ Остановить" if recording or processing else "● Запись")
        self._record_button.setStyleSheet(
            _RECORD_ACTIVE_STYLE if recording else _RECORD_IDLE_STYLE
        )
        if processing:
            self._record_button.setText("Обработка…")
            self._record_button.setEnabled(False)

        # Менять документ во время записи нельзя: текст вставляется в него по курсору.
        for widget in (self._new_button, self._open_button, self._action_new, self._action_open):
            widget.setEnabled(not (recording or processing))
        self._device_combo.setEnabled(not (recording or processing))
        self._editor.setReadOnly(False)

        self._level_meter.set_active(recording)
        if loading:
            self._status("Загрузка модели распознавания, это может занять некоторое время…")

    def _on_engine_ready(self, info: object) -> None:
        self._engine_label.setText(getattr(info, "summary", "Модель загружена"))
        logger.info("Движок готов: %s", getattr(info, "summary", info))

    def _on_autosaved(self) -> None:
        self._document.set_modified(False)
        self._saved_label.setText(f"Сохранено в {datetime.now():%H:%M:%S}")
        self._update_title()

    def _update_title(self) -> None:
        if not self._document.is_open:
            self.setWindowTitle(APP_NAME)
            return
        self.setWindowTitle(f"{self._document.display_name} — {APP_NAME}")

    def _status(self, message: str, timeout_ms: int = 6000) -> None:
        self.statusBar().showMessage(message, timeout_ms)

    # ---------------------------------------------------------------- #
    # Сообщения
    # ---------------------------------------------------------------- #

    def _on_error(self, message: str) -> None:
        logger.error("Ошибка: %s", message)
        self._show_error(message)

    def _on_warning(self, message: str) -> None:
        """Предупреждение не прерывает работу — показываем его в строке состояния."""
        logger.warning("Предупреждение: %s", message)
        self._status(message, timeout_ms=10_000)

    def _show_error(self, message: str) -> None:
        QMessageBox.critical(self, APP_NAME, message)

    def _show_warning(self, message: str) -> None:
        QMessageBox.warning(self, APP_NAME, message)

    def _activate_window(self) -> None:
        self.showNormal()
        self.raise_()
        self.activateWindow()

    # ---------------------------------------------------------------- #
    # Завершение работы
    # ---------------------------------------------------------------- #

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802 — имя задано Qt
        """Безопасное закрытие, в том числе во время записи (ТЗ §33)."""
        self._closing = True

        if self._controller.state.is_busy:
            self._status("Завершение записи, сохранение текста…")
            QCoreApplication.processEvents(QEventLoop.ProcessEventsFlag.ExcludeUserInputEvents)

        # shutdown() блокирует до обработки остатка звука. Результаты приходят
        # очередями сигналов Qt, поэтому после него нужно дать им дойти
        # до документа — иначе последняя распознанная фраза потерялась бы.
        self._controller.shutdown()
        for _ in range(_SHUTDOWN_EVENT_PASSES):
            QCoreApplication.processEvents(QEventLoop.ProcessEventsFlag.ExcludeUserInputEvents)
        self._inserter.end()

        if not self._confirm_discard(on_close=True):
            self._closing = False
            event.ignore()
            return

        self._autosave.stop()
        self._hotkey.unregister()
        self._save_geometry()
        self._settings.save()
        logger.info("Приложение закрыто")
        event.accept()

    def _confirm_discard(self, *, on_close: bool = False) -> bool:
        """Предлагает сохранить изменения. False — действие нужно отменить (ТЗ §25)."""
        if not self._document.is_open or not self._document.is_modified:
            return True
        if self._autosave.save_now(force=True):
            return True

        answer = QMessageBox.question(
            self,
            APP_NAME,
            f"Документ «{self._document.display_name}» не сохранён.\n"
            "Сохранить изменения?" + ("\nИначе изменения будут потеряны." if on_close else ""),
            QMessageBox.StandardButton.Save
            | QMessageBox.StandardButton.Discard
            | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Save,
        )
        if answer == QMessageBox.StandardButton.Save:
            return self._on_save()
        return answer == QMessageBox.StandardButton.Discard

    # ---------------------------------------------------------------- #

    def _default_dir(self) -> Path:
        if self._settings.last_directory:
            candidate = Path(self._settings.last_directory)
            if candidate.is_dir():
                return candidate
        return documents_dir()

    def _restore_geometry(self) -> None:
        if not self._settings.window_geometry:
            return
        try:
            self.restoreGeometry(QByteArray.fromHex(self._settings.window_geometry.encode("ascii")))
        except Exception:
            logger.debug("Не удалось восстановить геометрию окна", exc_info=True)

    def _save_geometry(self) -> None:
        try:
            self._settings.window_geometry = bytes(self.saveGeometry().toHex()).decode("ascii")
        except Exception:
            logger.debug("Не удалось сохранить геометрию окна", exc_info=True)

    def _on_open_log(self) -> None:
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(log_file())))

    def _on_about(self) -> None:
        info = self._controller.engine_info
        QMessageBox.about(
            self,
            f"О программе {APP_NAME}",
            f"<b>{APP_NAME}</b> версия {APP_VERSION}<br><br>"
            "Текстовый редактор с распознаванием русской речи.<br>"
            "Распознавание выполняется полностью на этом компьютере: "
            "звук и текст никуда не передаются.<br><br>"
            f"Движок: {info.summary if info else 'не загружен'}<br>"
            f"Журнал работы: {log_file()}",
        )


def _action(
    parent: QWidget,
    title: str,
    shortcut: QKeySequence.StandardKey | None,
    slot: object,
) -> QAction:
    action = QAction(title, parent)
    if shortcut is not None:
        action.setShortcut(shortcut)
    action.triggered.connect(slot)  # type: ignore[arg-type]
    return action


def _with_txt_suffix(path: Path) -> Path:
    """Документ по умолчанию сохраняется как .txt (ТЗ §24)."""
    return path if path.suffix else path.with_suffix(".txt")
