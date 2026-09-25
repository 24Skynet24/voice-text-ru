"""Диалог настроек (ТЗ §17, §19, §38).

Диалог возвращает новый объект `Settings`; применяет изменения вызывающая
сторона. Это позволяет отменить изменения без побочных эффектов.
"""

from __future__ import annotations

import logging
from dataclasses import replace

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGroupBox,
    QLabel,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from ..asr.catalog import DRAFT_DISABLED, DRAFT_MODELS, MODELS, get_draft_model, get_model
from ..asr.engine import cuda_device_count, default_cpu_threads
from ..audio.devices import list_input_devices
from ..settings import Settings
from .hotkey_edit import HotkeyEdit
from .theme import apply_dim

logger = logging.getLogger(__name__)

_DEVICE_CHOICES = (
    ("auto", "Автоматически"),
    ("cpu", "Процессор"),
    ("cuda", "Видеокарта NVIDIA (CUDA)"),
)


class SettingsDialog(QDialog):
    """Параметры микрофона, модели распознавания и горячей клавиши."""

    def __init__(self, settings: Settings, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Настройки")
        self.setMinimumWidth(560)
        self._settings = settings

        layout = QVBoxLayout(self)
        layout.addWidget(self._build_audio_group())
        layout.addWidget(self._build_model_group())
        layout.addWidget(self._build_recognition_group())
        layout.addWidget(self._build_hotkey_group())
        layout.addStretch(1)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel, self
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Сохранить")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("Отмена")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    # ---------------------------------------------------------------- #
    # Группы настроек
    # ---------------------------------------------------------------- #

    def _build_audio_group(self) -> QGroupBox:
        group = QGroupBox("Микрофон", self)
        form = QFormLayout(group)

        self._device_combo = QComboBox(group)
        self._refresh_devices()

        refresh_button = QPushButton("Обновить список", group)
        refresh_button.clicked.connect(self._refresh_devices)

        form.addRow("Устройство ввода:", self._device_combo)
        form.addRow("", refresh_button)
        return group

    def _build_model_group(self) -> QGroupBox:
        group = QGroupBox("Модель распознавания", self)
        form = QFormLayout(group)

        self._model_combo = QComboBox(group)
        for descriptor in MODELS:
            self._model_combo.addItem(descriptor.display_name, descriptor.model_id)
        index = self._model_combo.findData(self._settings.model_id)
        self._model_combo.setCurrentIndex(max(0, index))
        self._model_combo.currentIndexChanged.connect(self._update_model_description)

        self._model_description = QLabel(group)
        self._model_description.setWordWrap(True)
        self._model_description.setTextFormat(Qt.TextFormat.PlainText)
        apply_dim(self._model_description)

        self._device_choice = QComboBox(group)
        for value, title in _DEVICE_CHOICES:
            self._device_choice.addItem(title, value)
        self._device_choice.setCurrentIndex(
            max(0, self._device_choice.findData(self._settings.compute_device))
        )

        self._draft_combo = QComboBox(group)
        self._draft_combo.addItem("Не использовать", DRAFT_DISABLED)
        for descriptor in DRAFT_MODELS:
            self._draft_combo.addItem(descriptor.display_name, descriptor.model_id)
        self._draft_combo.setCurrentIndex(
            max(0, self._draft_combo.findData(self._settings.draft_model_id))
        )
        self._draft_combo.currentIndexChanged.connect(self._update_draft_description)

        self._draft_description = QLabel(group)
        self._draft_description.setWordWrap(True)
        self._draft_description.setTextFormat(Qt.TextFormat.PlainText)
        apply_dim(self._draft_description)

        form.addRow("Модель:", self._model_combo)
        form.addRow("", self._model_description)
        form.addRow("Быстрая модель:", self._draft_combo)
        form.addRow("", self._draft_description)
        backend_hint = QLabel(_backend_hint(), group)
        backend_hint.setWordWrap(True)
        apply_dim(backend_hint)

        form.addRow("Вычисления:", self._device_choice)
        form.addRow("", backend_hint)

        self._preload_check = QCheckBox("Загружать модель при запуске приложения", group)
        self._preload_check.setToolTip(
            "Первая запись начнётся без паузы, но запуск приложения займёт больше времени."
        )
        self._preload_check.setChecked(self._settings.preload_model)
        form.addRow("", self._preload_check)

        self._update_model_description()
        self._update_draft_description()
        return group

    def _build_recognition_group(self) -> QGroupBox:
        group = QGroupBox("Распознавание и сохранение", self)
        form = QFormLayout(group)

        self._partial_check = QCheckBox("Показывать уточняемый текст серым курсивом", group)
        self._partial_check.setToolTip(
            "Текст появляется почти сразу и уточняется по мере распознавания фразы.\n"
            "Если отключить, текст будет появляться только после пауз в речи."
        )
        self._partial_check.setChecked(self._settings.show_partial_text)

        self._silence_spin = QSpinBox(group)
        self._silence_spin.setRange(300, 3000)
        self._silence_spin.setSingleStep(50)
        self._silence_spin.setSuffix(" мс")
        self._silence_spin.setValue(self._settings.commit_silence_ms)
        self._silence_spin.setToolTip(
            "Пауза в речи, после которой фраза считается законченной и текст фиксируется.\n"
            "Меньше — текст фиксируется быстрее; больше — модель получает больше контекста."
        )

        self._autosave_spin = QSpinBox(group)
        self._autosave_spin.setRange(500, 30_000)
        self._autosave_spin.setSingleStep(500)
        self._autosave_spin.setSuffix(" мс")
        self._autosave_spin.setValue(self._settings.autosave_interval_ms)
        self._autosave_spin.setToolTip("Как часто документ записывается на диск во время записи.")

        form.addRow("", self._partial_check)
        form.addRow("Пауза для фиксации фразы:", self._silence_spin)
        form.addRow("Интервал автосохранения:", self._autosave_spin)
        return group

    def _build_hotkey_group(self) -> QGroupBox:
        group = QGroupBox("Глобальная горячая клавиша", self)
        form = QFormLayout(group)

        self._hotkey_check = QCheckBox("Включить глобальное сочетание клавиш", group)
        self._hotkey_check.setChecked(self._settings.hotkey_enabled)

        self._hotkey_edit = HotkeyEdit(self._settings.hotkey, group)
        self._hotkey_edit.setEnabled(self._settings.hotkey_enabled)
        self._hotkey_check.toggled.connect(self._hotkey_edit.setEnabled)

        hint = QLabel(
            "Сочетание начинает и останавливает запись, даже когда окно программы неактивно.\n"
            "Запись не начнётся, пока не создан или не открыт документ.",
            group,
        )
        hint.setWordWrap(True)
        apply_dim(hint)

        form.addRow("", self._hotkey_check)
        form.addRow("Сочетание:", self._hotkey_edit)
        form.addRow("", hint)
        return group

    # ---------------------------------------------------------------- #

    def _refresh_devices(self) -> None:
        """Перечитывает список устройств (гарнитуру могли подключить только что)."""
        current = self._device_combo.currentData() or self._settings.microphone_key
        self._device_combo.clear()
        self._device_combo.addItem("Системное устройство по умолчанию", None)
        for device in list_input_devices():
            self._device_combo.addItem(device.display_name, device.key)

        index = self._device_combo.findData(current) if current else 0
        if index < 0:
            # Сохранённое устройство сейчас недоступно — показываем это явно.
            self._device_combo.addItem(f"{current} (недоступно)", current)
            index = self._device_combo.count() - 1
        self._device_combo.setCurrentIndex(max(0, index))

    def _update_model_description(self) -> None:
        descriptor = get_model(self._model_combo.currentData())
        self._model_description.setText(descriptor.describe())

    def _update_draft_description(self) -> None:
        descriptor = get_draft_model(self._draft_combo.currentData())
        if descriptor is None:
            self._draft_description.setText(
                "Черновой текст будет считать основная модель. Он появится точнее, "
                "но заметно позже — один проход большой модели занимает несколько секунд."
            )
            return
        self._draft_description.setText(
            "Показывает черновой текст почти сразу, пока основная модель готовит "
            f"точный результат.\n{descriptor.describe()}"
        )

    # ---------------------------------------------------------------- #

    def result_settings(self) -> Settings:
        """Возвращает настройки с изменениями, сделанными в диалоге."""
        return replace(
            self._settings,
            microphone_key=self._device_combo.currentData(),
            model_id=self._model_combo.currentData(),
            draft_model_id=self._draft_combo.currentData(),
            compute_device=self._device_choice.currentData(),
            preload_model=self._preload_check.isChecked(),
            show_partial_text=self._partial_check.isChecked(),
            commit_silence_ms=self._silence_spin.value(),
            autosave_interval_ms=self._autosave_spin.value(),
            hotkey_enabled=self._hotkey_check.isChecked(),
            hotkey=self._hotkey_edit.hotkey() or self._settings.hotkey,
        ).normalized()


def _backend_hint() -> str:
    """Поясняет, какое устройство будет использовано на этом компьютере."""
    if cuda_device_count() > 0:
        return "Обнаружена видеокарта NVIDIA — в режиме «Автоматически» будет использована она."
    return (
        "Ускорение CUDA недоступно, распознавание выполняется на процессоре "
        f"({default_cpu_threads()} потоков). Видеокарты AMD и Intel этим движком не поддерживаются."
    )
