"""Управление сеансом записи — единственное место, где встречаются потоки.

Здесь связаны захват звука (поток PortAudio), распознавание (рабочий поток)
и интерфейс (главный поток Qt). Наружу всё выходит только сигналами Qt,
поэтому виджеты никогда не обращаются к чужим потокам напрямую.
"""

from __future__ import annotations

import logging
import threading

from PySide6.QtCore import QObject, QTimer, Signal

from .asr.engine import FasterWhisperEngine, TieredEngine
from .asr.types import EngineInfo, ModelLoadError, SpeechEngine
from .asr.worker import StreamConfig, TranscriptionWorker, WorkerCallbacks
from .audio.capture import AudioCapture, AudioCaptureError
from .audio.devices import AudioDevice, default_input_device, resolve_device
from .core.state import AppState
from .settings import Settings

logger = logging.getLogger(__name__)

_LEVEL_REFRESH_MS = 33
_WORKER_JOIN_TIMEOUT = 30.0


class RecognitionController(QObject):
    """Жизненный цикл распознавания: загрузка модели, запись, остановка."""

    stateChanged = Signal(object)  # AppState
    partialReady = Signal(str)
    textCommitted = Signal(str)
    errorOccurred = Signal(str)
    warningRaised = Signal(str)
    engineReady = Signal(object)  # EngineInfo
    levelChanged = Signal(float)
    recordingFinished = Signal()

    # Внутренние сигналы: переносят события рабочих потоков в главный поток Qt.
    _modelLoaded = Signal(object)
    _modelFailed = Signal(str)
    _workerFinished = Signal()

    def __init__(self, settings: Settings, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._settings = settings
        self._engine: SpeechEngine | None = None
        self._capture: AudioCapture | None = None
        self._worker: TranscriptionWorker | None = None
        self._loader: threading.Thread | None = None
        self._state = AppState.NO_DOCUMENT
        self._start_after_load = False
        self._pending_context = ""
        self._shutting_down = False

        self._level_timer = QTimer(self)
        self._level_timer.setInterval(_LEVEL_REFRESH_MS)
        self._level_timer.timeout.connect(self._on_level_tick)

        self._modelLoaded.connect(self._on_model_loaded)
        self._modelFailed.connect(self._on_model_failed)
        self._workerFinished.connect(self._on_worker_finished)

    # ---------------------------------------------------------------- #
    # Состояние
    # ---------------------------------------------------------------- #

    @property
    def state(self) -> AppState:
        return self._state

    @property
    def is_recording(self) -> bool:
        return self._state is AppState.RECORDING

    @property
    def engine_info(self) -> EngineInfo | None:
        return self._engine.info if self._engine is not None else None

    def set_state(self, state: AppState) -> None:
        if state is self._state:
            return
        logger.debug("Состояние: %s → %s", self._state.name, state.name)
        self._state = state
        self.stateChanged.emit(state)

    # ---------------------------------------------------------------- #
    # Настройки
    # ---------------------------------------------------------------- #

    def apply_settings(self, settings: Settings) -> None:
        """Принимает новые настройки; при смене модели движок перезагружается."""
        reload_needed = (
            settings.model_id != self._settings.model_id
            or settings.draft_model_id != self._settings.draft_model_id
            or settings.compute_device != self._settings.compute_device
            or settings.language != self._settings.language
        )
        self._settings = settings
        if reload_needed and self._engine is not None:
            logger.info("Настройки модели изменены — движок будет загружен заново")
            self._release_engine()

    # ---------------------------------------------------------------- #
    # Модель
    # ---------------------------------------------------------------- #

    def preload_model(self) -> None:
        """Загружает модель заранее, чтобы первая запись началась без паузы."""
        if self._engine is None and self._loader is None:
            self._start_model_load()

    def _start_model_load(self) -> None:
        self.set_state(AppState.LOADING_MODEL)
        settings = self._settings
        loader = threading.Thread(
            target=self._load_model_blocking,
            args=(settings.model_id, settings.draft_model_id, settings.compute_device, settings.language),
            name="ModelLoader",
            daemon=True,
        )
        self._loader = loader
        loader.start()

    def _load_model_blocking(
        self, model_id: str, draft_model_id: str, device: str, language: str
    ) -> None:
        """Выполняется в отдельном потоке: загрузка модели занимает секунды."""
        try:
            accurate = FasterWhisperEngine(model_id, device_preference=device, language=language)
        except ModelLoadError as error:
            self._modelFailed.emit(str(error))
            return
        except Exception as error:  # непредвиденное — тоже не должно ронять приложение
            logger.exception("Непредвиденная ошибка загрузки модели")
            self._modelFailed.emit(f"Не удалось загрузить модель: {error}")
            return

        draft: FasterWhisperEngine | None = None
        if draft_model_id:
            try:
                draft = FasterWhisperEngine(
                    draft_model_id, device_preference=device, language=language
                )
            except Exception:
                # Черновая модель — ускорение, а не необходимость: без неё
                # приложение работает, просто текст появляется только после пауз.
                logger.exception("Не удалось загрузить черновую модель %s", draft_model_id)
                self.warningRaised.emit(
                    f"Быстрая модель «{draft_model_id}» не загрузилась. "
                    "Черновой текст будет появляться медленнее."
                )

        self._modelLoaded.emit(TieredEngine(accurate, draft))

    def _on_model_loaded(self, engine: object) -> None:
        self._loader = None
        if self._shutting_down:
            engine.close()  # type: ignore[attr-defined]
            return
        self._engine = engine  # type: ignore[assignment]
        self.engineReady.emit(self._engine.info)
        if self._start_after_load:
            self._start_after_load = False
            self._begin_session()
        else:
            self.set_state(AppState.READY)

    def _on_model_failed(self, message: str) -> None:
        self._loader = None
        self._start_after_load = False
        self.set_state(AppState.ERROR)
        self.errorOccurred.emit(message)

    # ---------------------------------------------------------------- #
    # Запись
    # ---------------------------------------------------------------- #

    def start(self, context: str = "") -> None:
        """Начинает запись. Модель при необходимости загружается автоматически."""
        if self._state in (AppState.RECORDING, AppState.PROCESSING):
            return
        self._pending_context = context

        if self._engine is None:
            self._start_after_load = True
            if self._loader is None:
                self._start_model_load()
            return

        self._begin_session()

    def _begin_session(self) -> None:
        device = self._select_device()
        capture = AudioCapture(device, on_stream_error=self._on_capture_error)
        try:
            capture.start()
        except AudioCaptureError as error:
            self.set_state(AppState.ERROR)
            self.errorOccurred.emit(str(error))
            return

        assert self._engine is not None
        worker = TranscriptionWorker(
            engine=self._engine,
            source=capture,
            callbacks=WorkerCallbacks(
                on_partial=self.partialReady.emit,
                on_commit=self.textCommitted.emit,
                on_error=self.warningRaised.emit,
                on_finished=self._workerFinished.emit,
            ),
            config=StreamConfig(
                commit_silence_ms=self._settings.commit_silence_ms,
                max_utterance_seconds=float(self._settings.max_utterance_seconds),
                emit_partial=self._settings.show_partial_text,
            ),
        )
        worker.set_context(self._pending_context)

        self._capture = capture
        self._worker = worker
        worker.start()

        self._level_timer.start()
        self.set_state(AppState.RECORDING)
        logger.info("Запись начата")

    def stop(self) -> None:
        """Останавливает запись и корректно дорабатывает остаток звука (ТЗ §33)."""
        if self._state not in (AppState.RECORDING,):
            return
        logger.info("Остановка записи")
        self.set_state(AppState.PROCESSING)
        self._level_timer.stop()
        self.levelChanged.emit(0.0)

        # Сначала закрываем микрофон: остаток звука уже лежит в очереди,
        # и поток распознавания обработает его перед завершением.
        if self._capture is not None:
            self._capture.stop()
        if self._worker is not None:
            self._worker.request_stop()

    def _on_worker_finished(self) -> None:
        """Рабочий поток завершил обработку остатка."""
        worker, self._worker = self._worker, None
        capture, self._capture = self._capture, None

        if worker is not None:
            worker.join(timeout=_WORKER_JOIN_TIMEOUT)
            if worker.is_alive():
                logger.warning("Поток распознавания не завершился за %.0f с", _WORKER_JOIN_TIMEOUT)
        if capture is not None:
            capture.stop()

        if not self._shutting_down:
            self.set_state(AppState.READY)
        self.recordingFinished.emit()
        logger.info("Запись остановлена")

    # ---------------------------------------------------------------- #
    # Микрофон
    # ---------------------------------------------------------------- #

    def _select_device(self) -> AudioDevice | None:
        """Выбирает сохранённый микрофон; при его отсутствии — системный (ТЗ §17)."""
        if self._settings.microphone_key:
            device = resolve_device(self._settings.microphone_key)
            if device is not None:
                return device
            self.warningRaised.emit(
                "Выбранный микрофон недоступен. Используется устройство по умолчанию — "
                "проверьте выбор в настройках."
            )
        return default_input_device()

    def _on_capture_error(self, message: str) -> None:
        """Вызывается из потока PortAudio при обрыве потока (ТЗ, тест 8)."""
        self.errorOccurred.emit(message)

    def _on_level_tick(self) -> None:
        capture = self._capture
        if capture is None:
            return
        self.levelChanged.emit(capture.level)
        if capture.has_failed:
            self._level_timer.stop()
            self.stop()

    # ---------------------------------------------------------------- #
    # Завершение
    # ---------------------------------------------------------------- #

    def shutdown(self) -> None:
        """Освобождает все ресурсы. Блокирует до завершения обработки (ТЗ §33, §36)."""
        self._shutting_down = True
        self._level_timer.stop()

        # Порядок важен: сначала освобождаем микрофон, затем даём потоку
        # распознавания доработать уже записанный звук, и только потом
        # выгружаем модель (ТЗ §33).
        capture, self._capture = self._capture, None
        if capture is not None:
            capture.stop()

        worker, self._worker = self._worker, None
        if worker is not None:
            worker.request_stop()
            worker.join(timeout=_WORKER_JOIN_TIMEOUT)
            if worker.is_alive():
                logger.warning("Поток распознавания не остановился за отведённое время")

        self._release_engine()
        logger.info("Ресурсы распознавания освобождены")

    def _release_engine(self) -> None:
        engine, self._engine = self._engine, None
        if engine is not None:
            try:
                engine.close()
            except Exception:
                logger.exception("Ошибка при остановке движка распознавания")
