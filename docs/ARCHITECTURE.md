# Architecture & Technology Decisions

This document explains *why* the stack was chosen (TS §20, §35, §42) before describing *how*
the application is put together.

## 1. Speech recognition engine

The requirement priority order is: **Russian accuracy → low latency → fully local → stability**
(TS §43). Candidates evaluated:

| Engine | Russian quality | Streaming | Local | Windows packaging | Verdict |
|---|---|---|---|---|---|
| Vosk (`vosk-model-ru-0.42`) | Moderate (Kaldi, noticeably worse than Whisper on free speech) | Native, very low latency | Yes | Easy | Rejected — accuracy is priority #1 |
| Whisper (OpenAI reference, PyTorch) | High | No | Yes | Heavy (torch ≈ 2.5 GB) | Rejected — packaging/perf |
| **faster-whisper (CTranslate2)** | **High (same weights as Whisper)** | Chunked + VAD | Yes | Good (no torch) | **Selected** |
| NVIDIA NeMo / GigaAM-RNNT | Best-in-class Russian | Native streaming | Yes | Requires torch + NeMo, CUDA-centric | Rejected — huge deps, poor AMD story |
| whisper.cpp (Vulkan) | High | Chunked | Yes | Needs shipping custom-built binaries | Kept as a future engine (see §6) |

**Selected: `faster-whisper` (CTranslate2 runtime).** It runs Whisper weights 4–5× faster than the
reference implementation with lower memory, has no PyTorch dependency, supports INT8 quantisation on
CPU and FP16 on CUDA, and has no session-length limits.

### Model choice for this class of hardware

The reference machine is an **AMD Ryzen 5 7500F (6c/12t) + AMD Radeon RX 6900 XT**. CTranslate2 has
no ROCm/DirectML backend, so **the GPU cannot be used** and inference runs on the CPU. That makes the
accuracy/speed trade-off decisive, and the default is **`large-v3-turbo`**: it keeps `large-v3`'s
encoder (which carries most of the acoustic accuracy) and distils the decoder from 32 to 4 layers.

`small`, `medium` and full `large-v3` are also offered in Settings with plain-language descriptions
of the trade-off (TS §19).

### The measurement that shaped the design

Benchmarked on the reference machine with Russian speech (scripts in the session scratchpad,
figures reproducible via `faster_whisper` directly):

| Setting (5 s Russian clip) | Time for one pass |
|---|---|
| `small`, INT8, 6 threads | **0.95 s** |
| `medium`, INT8, 6 threads | 2.9 s |
| `large-v3-turbo`, INT8, 6 threads | 4.2 s |
| `large-v3-turbo`, INT8, 12 threads | **3.2 s** |
| `large-v3-turbo`, FP32, 12 threads | 5.0 s |
| `large-v3`, INT8, 6 threads | 5.1 s |

On transcription quality, only `large-v3-turbo` and `large-v3` reproduced «своём» with ё;
`small` and `medium` both returned «своем». `medium` is therefore a poor deal — nearly as slow as
turbo and measurably less accurate — which is why turbo is the default despite being the larger
download.

Two findings drive the architecture:

1. **A pass costs the same for 2 s of audio as for 6 s** (4.06 s / 4.12 s / 4.14 s measured at 2, 4
   and 6 seconds). Whisper's encoder always processes a zero-padded 30-second window.
   `chunk_length` does not change this in faster-whisper 1.2 — it was measured and made no
   difference. So latency is dominated by a *fixed* per-pass cost, not by utterance length. Longer
   utterances are therefore effectively free, which is why the segmenter prefers whole phrases.
2. **Using all logical CPUs is ~24% faster** than physical cores only, so `default_cpu_threads()`
   returns `os.cpu_count()`.

A 3-second delay before any text appears is not acceptable for dictation, which leads to the
two-tier engine below.

### End-to-end result

Feeding 18.6 s of Russian speech (three sentences separated by pauses) through the real pipeline at
real-time speed, with `large-v3-turbo` confirming and `small` drafting, produced:

```
[ 3.14s] PARTIAL: 'Сегодня я хочу'
[ 4.88s] PARTIAL: 'Сегодня я хочу рассказать о своем новом...'
[ 8.91s] COMMIT : 'Сегодня я хочу рассказать о своём новом проекте.'
...
Document: Сегодня я хочу рассказать о своём новом проекте. Это приложение распознаёт
          русскую речь прямо на компьютере. Подключение к интернету для работы не требуется.
```

The transcript is word-for-word correct, three utterances produced exactly three confirmations, and
drafts were replaced rather than appended. First draft appears ~2 s after speech starts; a phrase is
confirmed ~2.7 s after it ends.

### Why not "true" streaming ASR

Whisper is an offline encoder–decoder model; it has no streaming mode. The pipeline therefore
implements streaming *around* it (see §3) rather than pretending the model streams.

## 2. Application stack

**Python 3.12 + PySide6 (Qt 6)**, packaged with **PyInstaller** and an **Inno Setup** installer.

* The ASR runtime is a Python library, so a Python host avoids a second process and an IPC layer.
* Qt's `QPlainTextEdit` already provides the whole editor requirement list of TS §3 — cursor
  handling, selection, clipboard, undo/redo — with a document model whose `QTextCursor` objects
  *auto-adjust* when the document changes. That property is what makes "insert transcription at the
  cursor while the user edits elsewhere" (TS §16) robust rather than fragile index arithmetic.
* Qt runs the UI on the main thread only; audio capture and recognition live on their own threads,
  so recognition is entirely independent of window focus (TS §6, §32).
* PyInstaller + Inno Setup produce an installable `.exe` with an embedded interpreter, so the end
  user installs nothing else (TS §2, §39).

An Electron/Tauri front-end was rejected: it would require a second runtime and a Python sidecar
process purely to render a plain-text editor.

## 3. Streaming transcription strategy

This is the core of the design and the answer to TS §10 and §15.

```
microphone ─▶ AudioCapture (callback thread)
                 │  float32 @ device rate ─▶ anti-aliased resample ─▶ 16 kHz mono
                 ▼
             bounded queue
                 │
                 ▼
        TranscriptionWorker (worker thread)
                 │  utterance buffer + energy VAD
                 ├── every ~1 s of speech ─▶ draft model  (small, ~1 s) ─▶ PARTIAL (replaces previous)
                 └── on ~700 ms of silence ─▶ accurate model (turbo, beam=5) ─▶ COMMIT
                 ▼
          Qt queued signals
                 ▼
     TranscriptInserter ─▶ QPlainTextEdit ─▶ AutoSaveManager ─▶ UTF-8 .txt
```

**Why "re-transcribe the open utterance" instead of incremental chunks.** Feeding Whisper fixed
2-second chunks destroys accuracy, because the model loses the context it needs to resolve word
endings and case agreement — exactly what Russian needs most. Instead, the buffer holds the
*current utterance from its beginning*, and every refresh transcribes the whole utterance. Accuracy
therefore matches an offline transcription of that utterance. Since a pass costs the same regardless
of length (§1), re-transcribing the whole utterance is also no more expensive than a chunk would be.

**The two-tier engine (`asr/engine.py: TieredEngine`).** Because one pass of the accurate model
takes ~3 s, drafts are produced by a second, much smaller model (`small`, ~1 s) held in memory
alongside it. The user sees text about a second after speaking; when the phrase ends, the accurate
model replaces that draft with its own result. This is what makes "accuracy first, latency second"
achievable at the same time rather than as a trade-off, and it also keeps a draft pass from
delaying a confirmation by a full accurate pass. The draft model can be changed or switched off
entirely in Settings; without it, text simply appears only after pauses.

**Why this cannot duplicate text (TS §15).** The partial result is not appended — it *is* a region
of the document (`TranscriptInserter`), and each refresh **replaces** that region. Committing
replaces the same region one last time with the accurate result and then moves the insertion anchor
past it. Text is only ever appended at commit boundaries, so the
`"I want" / "I want to" / "I want to create"` failure mode is structurally impossible.

**Bounded work.** An utterance is force-committed at `max_utterance_seconds` (default 20 s) even
without a pause, cut at the quietest point near its end, so both buffer size and per-pass cost stay
bounded during multi-hour sessions (TS §22, §23). Three mechanisms keep the pipeline from falling
behind real time, in increasing order of severity:

1. **Self-throttling** — the interval before the next draft is at least 1.2× how long the last one
   took, so a slow machine automatically produces fewer drafts.
2. **A draft time budget** (`draft_time_budget`, default 30%) — drafts may consume at most that
   share of wall-clock time. Since one confirmation pass is a fixed ~3 s, unbudgeted drafts could
   otherwise consume the capacity that confirmations need, and lag would accumulate over a long
   session. Confirmations always win.
3. **A hard backlog cap** (`hard_backlog_seconds`, default 45 s) — past this, the oldest audio is
   dropped and the user is told to pick a smaller model, rather than letting memory grow without
   limit.

**Silence handling.** Whisper reliably hallucinates stock phrases on silence
(`«Продолжение следует…»`, `«Субтитры сделал DimaTorzok»`, `«Спасибо за просмотр!»`). Segments are
therefore filtered on `no_speech_prob` / `avg_logprob` and against a blocklist of known artefacts
(`asr/postprocess.py`), and a buffer containing no detected speech is never sent to the model.

### VAD

Segmentation uses a self-contained **adaptive-energy VAD** (`asr/vad.py`): it tracks the noise floor
with an asymmetric follower and applies hysteresis, so it adapts to room noise without an extra
model dependency, and it is deterministic and unit-testable. It only decides *when* to cut — Silero
VAD (bundled with faster-whisper) additionally cleans the audio inside `transcribe()`, so a
mis-timed cut costs latency, never accuracy.

## 4. Threading model

| Thread | Owns | Notes |
|---|---|---|
| Qt main | UI, document, auto-save timer, hotkey event filter | Never blocks on ASR |
| PortAudio callback | Level metering, resampling, enqueue | Real-time; does no allocation-heavy work |
| `TranscriptionWorker` | Audio buffer, VAD, engine calls | Emits Qt signals (auto-queued to main thread) |
| `ModelLoader` (transient) | `WhisperModel` construction | Keeps the UI responsive during first load |

Shutdown is explicit and ordered (TS §33): stop capture → flush remaining audio → final commit →
save document → close engine → release device.

## 5. Module map

```
voicetext_ru/
├─ app.py, __main__.py        entry point, crash logging, `--selftest` diagnostics
├─ paths.py, logging_setup.py app data dirs, size-capped rotating log (TS §37)
├─ asr/engine.py              also holds TieredEngine (draft + accurate models)
├─ settings.py                typed, JSON-persisted preferences (TS §38)
├─ audio/
│  ├─ devices.py              WASAPI-first device enumeration (TS §17)
│  ├─ resample.py             streaming windowed-sinc resampler
│  └─ capture.py              InputStream, level metering, bounded queue
├─ asr/
│  ├─ types.py                engine-neutral result/update types
│  ├─ catalog.py              model descriptors shown in Settings (TS §19)
│  ├─ engine.py               SpeechEngine protocol + FasterWhisperEngine
│  ├─ vad.py                  adaptive-energy voice activity detection
│  ├─ postprocess.py          hallucination / low-confidence filtering
│  └─ worker.py               streaming orchestration (the loop above)
├─ core/
│  ├─ document.py             UTF-8 load/save, encoding + newline preservation
│  ├─ autosave.py             debounced, atomic saves (TS §14)
│  ├─ hotkey.py               Win32 RegisterHotKey + native event filter (TS §7)
│  └─ state.py                explicit application states (TS §31)
├─ controller.py              session orchestration, the only place threads meet
└─ ui/
   ├─ main_window.py          menus, toolbar, status, shutdown sequence
   ├─ editor.py               QPlainTextEdit configuration
   ├─ transcript_inserter.py  the draft-region mechanism described above
   ├─ level_meter.py          logarithmic input level meter (TS §18)
   ├─ settings_dialog.py      microphone / model / hotkey settings
   ├─ hotkey_edit.py          "press the shortcut" input field
   └─ theme.py                palette-derived dim colour for secondary labels
```

### Build layout

```
build/
├─ entrypoint.py      absolute-import entry for PyInstaller (see below)
├─ voicetext_ru.spec  PyInstaller recipe: native DLLs in, unused Qt modules out
├─ make_icon.py       draws src/voicetext_ru/resources/app.ico so no binary lives in the repository
├─ installer.iss      Inno Setup script, per-user install, no admin rights
└─ build.ps1          one command for the whole chain
```

Two Windows-specific traps are guarded by tests in `tests/test_build_files.py`, because both fail
only at build time and produce confusing errors:

* `build.ps1` and `installer.iss` **must** be UTF-8 **with BOM** — Windows PowerShell 5.1 otherwise
  reads them as ANSI and the Cyrillic text turns into a parse error.
* PyInstaller runs its entry file as a plain script with no parent package, so
  `voicetext_ru/__main__.py` (which uses `from .app import ...`) cannot be that file. `build/
  entrypoint.py` uses an absolute import instead. Without it the frozen application dies before
  logging is even configured, leaving no diagnostics at all.

The engine is reached only through the `SpeechEngine` protocol and `asr/catalog.py`, so replacing it
(TS §35) touches no UI code.

### Diagnostics

A packaged windowed application has no console, so a failure to load a native library would surface
only as an empty crash dialog. `--selftest [file.wav]` therefore runs the whole recognition stack
without the UI and writes a report to `%LOCALAPPDATA%\VoiceTextRU\selftest.txt`: detected
microphones, CUDA presence, thread count, model load result and, if a WAV is given, the
transcription. This is what separates "the build is broken" from "the microphone is misconfigured".

## 6. Known limitations / future work

* **AMD GPU acceleration** is not available through CTranslate2. A `whisper.cpp` Vulkan engine
  implementing the same `SpeechEngine` protocol is the natural way to add it; nothing outside
  `asr/` would change.
* Automatic punctuation restoration is out of scope for v1 (TS §11) — Whisper's own punctuation is
  kept as-is.
* System tray and start-with-Windows are deliberately not implemented (TS §28, §29); the
  controller/UI split leaves room for both.
