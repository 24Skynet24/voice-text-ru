# Technical Specification — Windows Local Speech-to-Text Application

## 1. Project Overview

Develop a Windows desktop application similar to a simple text editor such as Word, with one main purpose: **continuously convert the user's speech from a microphone into text in real time**.

The application should work primarily as a text editor with integrated local speech recognition.

The user must first create or open a text document, place the cursor where they want the transcription to be inserted, and then start recording.

While recording, the application continuously recognizes Russian speech locally on the user's computer and inserts the recognized text into the document.

The application must continue recording and processing speech even when its window is no longer focused.

### Example workflow

1. Open the application.
2. Create a new document such as `document.txt`.
3. Press the Record button.
4. Start speaking.
5. Recognized text gradually appears in the document.
6. Switch to a browser, VS Code, or another application.
7. Speech recognition continues running.
8. Return to the application.
9. Review and correct the text.
10. Copy the final text.

The main priorities are:

1. **Russian speech recognition accuracy**
2. **Low transcription latency**
3. **Fully local/offline processing**
4. **No artificial recording/session limits**
5. **Simple and reliable user experience**

---

# 2. Platform

The application is intended for **Windows**.

The final project must be possible to build into a production application that can be installed and launched like a normal Windows application.

The end user should not need to install Python, Node.js, development dependencies, or other development tools to run the final production build.

---

# 3. Text Editor

The application should have a simple document-editor interface.

It does NOT need to be a full Microsoft Word replacement.

The editor must support:

* Create a new document
* Open an existing document
* Edit text
* Save the document
* Automatic saving
* Cursor positioning
* Text selection
* Copy
* Paste
* Cut
* Undo
* Redo
* Continue recording from the current cursor position

The initial document format should be:

```text
.txt
```

No complex text formatting is required.

---

# 4. Creating and Opening Documents

## 4.1. New document

A document must exist before recording can start.

The application must NOT allow the user to start speech recognition without an open or newly created document.

When creating a new document, the user should choose:

* File name
* Save location

The application then creates the text file.

Only after the document exists should recording be available.

## 4.2. Opening an existing document

The user can open an existing `.txt` file.

After opening it, the user can:

* Edit it
* Place the cursor anywhere
* Press Record
* Continue dictating from the selected position

For example:

```text
First paragraph.

Second paragraph.

|Cursor is here|
```

After recording starts, newly recognized text should be inserted at the cursor position.

The application must NOT always append new text to the end of the document.

---

# 5. Recording

The main recording control should be a:

```text
Record / Stop
```

button.

When recording is active:

* The button must clearly indicate that recording is active.
* The application must show that the microphone is currently being used.
* The application should display a real-time microphone input level.
* The user must clearly understand whether the application is currently listening.

Example:

```text
● Recording

Microphone: [Default Microphone ▼]

Input level:
████████████░░░░
```

---

# 6. Background Recording

This is a **critical requirement**.

Losing window focus must NOT stop recording or speech recognition.

After recording has started, the user must be able to:

* Switch to another application
* Open a browser
* Open VS Code
* Open File Explorer
* Minimize the application
* Work in another application
* Return to the speech-to-text application later

Speech recognition must continue running during all of these actions.

The application must not depend on having window focus.

---

# 7. Global Hotkey

In addition to the Record button, the application must support a global keyboard shortcut.

For example:

```text
Ctrl + Shift + Space
```

The shortcut should work even when the application is not focused.

Behavior:

```text
Ctrl + Shift + Space
        ↓
Start recording

Ctrl + Shift + Space
        ↓
Stop recording
```

The hotkey should preferably be configurable in Settings.

Important:

The global hotkey must NOT allow recording to start if no document is currently open.

If the user tries to start recording without a document, display a clear message such as:

> Please create or open a document before recording.

---

# 8. Speech Recognition

Speech recognition must run **fully locally on the user's computer**.

Do not require a cloud speech-to-text API.

The reasons are:

* No time limits
* No per-minute API costs
* No dependency on an Internet connection
* Better privacy
* Ability to work completely offline

After the required speech recognition model has been installed, an Internet connection should not be required for transcription.

---

# 9. Language

The primary and required language is:

**Russian**

The architecture should preferably allow additional languages to be added later, such as English.

However, only Russian is required for the first version.

---

# 10. Real-Time Transcription

Speech recognition should happen as close to real time as reasonably possible.

The application should NOT wait until the entire recording is finished.

For example, if the user says:

> Сегодня я хочу рассказать о своём новом проекте

the text should gradually appear while the user is speaking.

A small delay is acceptable because audio processing and speech recognition naturally require some processing time.

The target is:

* Low practical latency
* High accuracy
* Stable continuous processing

The implementation should choose an appropriate audio chunk / processing window size.

Avoid extremely small chunks if they significantly reduce recognition quality.

Avoid excessively large chunks that create noticeable latency.

---

# 11. Punctuation

Automatic punctuation is **not required** in the first version.

For example, if the user says:

> Сегодня я хочу рассказать о своём новом проекте

the result may simply be:

```text
Сегодня я хочу рассказать о своём новом проекте
```

The application does not need to automatically add:

* Periods
* Commas
* Colons
* Quotation marks
* Other punctuation

The user can manually edit the text afterward.

---

# 12. Transcription Accuracy

The application should reproduce what the user actually said as accurately as possible.

It should NOT automatically rewrite the user's speech into more literary or polished language.

For example:

Speech:

> Сегодня я тестирую новое приложение

Expected result:

```text
Сегодня я тестирую новое приложение
```

The application should not independently rewrite the sentence or change its meaning.

The user will manually correct recognition mistakes in the editor.

---

# 13. Editing the Transcribed Text

The recognized text must be normal editable text.

The user must be able to:

* Correct recognition errors
* Delete text
* Add text
* Move the cursor
* Select text
* Copy text
* Continue recording

After stopping the recording, the user should be able to review and edit the entire document normally.

---

# 14. Automatic Saving

This is another **critical requirement**.

The document must be automatically saved while recording.

The application should not wait for the user to press `Ctrl + S`.

Example:

```text
Recording
    ↓
Speech recognition
    ↓
Text updated
    ↓
Document automatically saved
```

The exact save interval should be chosen based on the implementation.

Prefer a safe strategy such as:

* Save after a new confirmed transcription segment is produced.
* Do not write to disk excessively often.
* Optionally enforce a minimum save interval such as 500–1000 ms.

The main goal is:

**If the application crashes unexpectedly, the user should not lose a significant amount of already-transcribed text.**

The document must also be saved immediately when recording stops.

---

# 15. Streaming Transcription and Partial Results

The speech recognition engine may initially produce a partial result and later revise it when additional audio becomes available.

For example:

```text
I want to create...
```

may later become:

```text
I want to create an application...
```

The architecture must correctly handle:

* Temporary / partial transcription results
* Confirmed transcription results

The application must NOT produce duplicated text such as:

```text
I want to create
I want to create an application
I want to create an application for
I want to create an application for Windows
```

Instead, the editor should contain only the current correct result:

```text
I want to create an application for Windows
```

Use an appropriate streaming transcription strategy that stabilizes partial results and commits confirmed text.

---

# 16. Continue Recording from the Cursor Position

The user can open an existing document:

```text
First paragraph.

Second paragraph.

Third paragraph.
```

Place the cursor somewhere in the document:

```text
First paragraph.

Second paragraph.

|Third paragraph.|
```

and start recording.

New recognized text must be inserted starting at that cursor position.

The application must NOT automatically move the insertion point to the end of the document.

The insertion position should be determined when recording starts.

---

# 17. Microphone Selection

Settings must provide a way to select the input device.

For example:

```text
Microphone

[ Default Microphone ▼ ]

Input level:

████████████░░░░
```

The application must detect available Windows audio input devices.

The user must be able to select a specific microphone.

If the selected microphone becomes unavailable, the application should display a clear error or warning.

---

# 18. Microphone Activity Indicator

While recording, display a visual microphone indicator.

For example:

```text
● Recording
```

Also provide a real-time audio input level meter if possible.

Example:

```text
Microphone

██████████████░░░░
```

The level meter is functional, not just decorative.

It should help the user verify that the application is actually receiving audio.

---

# 19. Speech Recognition Model Settings

The application should provide model-related settings.

For example:

```text
Speech Recognition Model

[ Model ▼ ]
```

Depending on the selected speech recognition technology, different model sizes may be available.

For example:

```text
Small
Faster, lower accuracy

Medium
Balanced

Large
Higher accuracy, higher hardware requirements
```

The exact available models depend on the chosen speech recognition engine.

The application should make the trade-offs understandable to a normal user.

---

# 20. Speech Recognition Technology

Choose the most appropriate **local speech-to-text technology** based on the actual requirements.

The technology should be evaluated according to:

1. Russian language accuracy
2. Real-time performance
3. Low latency
4. Fully local/offline operation
5. No artificial duration limits
6. Windows compatibility
7. Stability during long recording sessions
8. Availability of hardware acceleration where possible

Do not select a technology simply because it is easier to implement.

Before final implementation, evaluate suitable local speech recognition engines/models and select the option that best matches these requirements.

---

# 21. GPU and Hardware Acceleration

The application should use hardware acceleration when it is beneficial and available.

Do NOT hard-code the architecture around NVIDIA CUDA only.

The application should also work on systems with AMD GPUs.

If the selected speech recognition engine performs better on CPU or another backend, that is acceptable.

The primary criteria are:

**maximum recognition quality + low latency + stability.**

The implementation should automatically use the most appropriate available backend where practical.

---

# 22. Performance

The application must be designed for long recording sessions.

It should support sessions such as:

* 10 minutes
* 30 minutes
* 1 hour
* Several hours

There should be no artificial limitation such as:

```text
Maximum recording duration: 5 minutes
```

or:

```text
Session limit reached
```

unless technically unavoidable.

Monitor and optimize:

* RAM usage
* CPU usage
* GPU usage
* Audio buffer size
* Memory leaks
* Temporary data growth

Do not keep an entire multi-hour audio recording in RAM unnecessarily.

---

# 23. Long Recording Architecture

The application must support continuous streaming.

Do NOT implement the system like this:

```text
Record entire audio
        ↓
Store everything in RAM
        ↓
Process entire recording
        ↓
Generate text
```

Instead use a streaming architecture:

```text
Microphone
    ↓
Audio stream
    ↓
Audio buffer
    ↓
Speech recognition
    ↓
Partial result
    ↓
Confirmed result
    ↓
Text editor
    ↓
Auto-save
```

This is required for long sessions and low latency.

---

# 24. File Format

The document should be stored as a normal text file.

Initial format:

```text
.txt
```

Use UTF-8 encoding.

Russian text must always be saved correctly without encoding corruption.

---

# 25. Unsaved Changes

The application should track document modifications.

For example:

```text
document.txt *
```

where `*` indicates unsaved changes.

However, automatic saving should normally keep the file synchronized with the editor according to the auto-save strategy.

Before closing the application, handle any remaining unsaved changes safely.

---

# 26. Copying Text

Normal keyboard shortcuts must work:

```text
Ctrl + C
Ctrl + V
Ctrl + X
Ctrl + A
```

A `Copy` button may also be provided.

The user should be able to:

1. Read the transcription.
2. Correct it.
3. Select the required text.
4. Copy it.
5. Paste it into another application.

---

# 27. Document History

A built-in transcription history is **not required**.

The application should not automatically maintain a database of all previous recordings.

The user manages documents manually.

Supported workflows:

```text
New document
      ↓
Record
      ↓
Save document
```

or:

```text
Open existing document
      ↓
Place cursor
      ↓
Record
      ↓
Save document
```

---

# 28. System Tray

System Tray support is **not required for the first version**.

However, the architecture should not make adding System Tray support later difficult.

---

# 29. Windows Startup

Starting the application automatically with Windows is **not required for the first version**.

The application may support this in the future.

---

# 30. User Interface

The interface should be simple and focused.

The main purpose of the application is:

**document editing + speech recording.**

Avoid unnecessary UI complexity.

Suggested layout:

```text
┌──────────────────────────────────────────────────────────┐
│ File   Edit   Settings                                   │
├──────────────────────────────────────────────────────────┤
│                                                          │
│  [ New ] [ Open ] [ Save ]          [ ● Record ]         │
│                                                          │
│  Microphone: [ Default ▼ ]                              │
│  Input:      ████████████░░                              │
│                                                          │
├──────────────────────────────────────────────────────────┤
│                                                          │
│  Text document                                           │
│                                                          │
│  Сегодня я хочу рассказать о своем новом проекте         │
│  который я сейчас разрабатываю                           │
│                                                          │
│  Здесь продолжается текст...                             │
│                                                          │
│                                                          │
├──────────────────────────────────────────────────────────┤
│ Ready                                                    │
└──────────────────────────────────────────────────────────┘
```

The text editor should occupy most of the window.

The UI should be clean and practical rather than visually complex.

---

# 31. Application States

The application should explicitly handle the following states.

## No document

```text
No document
```

Recording is disabled.

## Document opened

```text
Ready
```

Recording can be started.

## Recording

```text
● Recording
```

The microphone is active and speech recognition is running.

## Processing

If the recognition engine requires final processing:

```text
Processing...
```

## Error

Examples:

```text
Microphone unavailable
```

or:

```text
Speech recognition model failed to load
```

Errors must be understandable to a normal user.

---

# 32. Minimized Application

If the user starts recording and minimizes the application:

```text
Application
    ↓
Record
    ↓
Minimize
```

recording must continue.

Speech recognition and auto-saving must also continue.

---

# 33. Closing During Recording

If the user tries to close the application while recording:

1. Stop recording.
2. Process any remaining audio that can still be processed.
3. Save the document.
4. Properly shut down the speech recognition engine.
5. Release the microphone.
6. Close the application.

Do not silently lose already recognized text.

---

# 34. Privacy

Speech should be processed locally.

Do not send audio or transcribed text to external servers without explicit user permission.

Do not require a cloud API for speech recognition.

The application should work offline after the required model files have been installed.

---

# 35. Architecture

Choose the technology stack based on performance, reliability, Windows integration, and maintainability.

The stack itself is not predetermined.

Choose the most appropriate solution rather than assuming a particular framework.

The application should be divided into independent logical components.

Suggested architecture:

```text
UI
│
├── Document Editor
├── Recording Controls
├── Settings
└── Status / Microphone Indicator

Application Core
│
├── Document Manager
├── Auto Save Manager
├── Hotkey Manager
└── Application State

Audio
│
├── Microphone Manager
├── Audio Capture
└── Audio Buffer

Speech Recognition
│
├── Speech-to-Text Engine
├── Streaming / Chunk Processing
├── Partial Results
└── Confirmed Results

Storage
│
└── UTF-8 Text Files
```

The speech recognition engine should be replaceable without requiring a complete rewrite of the UI.

---

# 36. Code Quality

The code should be:

* Well structured
* Readable
* Maintainable
* Properly separated by responsibility
* Strongly typed where appropriate
* Free of unnecessary global state
* Free of hardcoded absolute paths
* Properly handling errors
* Properly releasing resources

Avoid extremely large files containing unrelated logic.

Pay particular attention to:

* Microphone cleanup
* Audio stream cleanup
* Speech recognition shutdown
* Temporary buffer cleanup
* File handling
* Memory leaks
* Thread/task cancellation

---

# 37. Logging

Implement application logging for important events and errors.

Examples:

```text
Application started
Microphone initialized
Speech model loaded
Recording started
Recording stopped
Document saved
Speech recognition error
Microphone disconnected
```

Logs should help diagnose problems.

Do not allow logs to grow indefinitely.

---

# 38. Persistent Settings

Application settings should persist between launches.

Examples:

* Selected microphone
* Selected speech recognition model
* Global hotkey
* Other application preferences

When the application starts again, previously selected settings should be restored.

---

# 39. Production Build

The project must provide a clear production build process:

```text
Development
    ↓
Build
    ↓
Production application
    ↓
Windows executable / installer
```

The final application should be installable and runnable without a development environment.

Provide documentation explaining:

1. How to install development dependencies.
2. How to run the application in development mode.
3. How to build the production version.
4. Where the final `.exe` or installer is generated.
5. How to package the application if an installer is used.

---

# 40. Testing Requirements

The implementation must be tested against at least the following scenarios.

## Test 1 — Basic recording

```text
Create document
Start recording
Speak Russian
Stop recording
```

Expected:

* Russian speech is transcribed.
* Text appears in the document.
* Document is saved.

---

## Test 2 — Background recording

```text
Create document
Start recording
Switch to Chrome
Speak
Switch back
Stop recording
```

Expected:

* Recording continues while Chrome is active.
* Speech recognition continues.
* No significant transcription is lost.

---

## Test 3 — Minimized application

```text
Create document
Start recording
Minimize application
Speak
Restore application
Stop recording
```

Expected:

* Recording continues while minimized.
* Recognized text is available after restoring the application.

---

## Test 4 — Global hotkey

```text
Open document
Switch to another application
Press global hotkey
Speak
Press global hotkey again
```

Expected:

* Recording starts and stops using the global hotkey.
* The application does not need to be focused.

---

## Test 5 — Existing document

```text
Open existing .txt file
Place cursor in the middle of the document
Start recording
Speak
Stop recording
```

Expected:

* New text is inserted at the selected cursor position.
* Existing text is preserved.

---

## Test 6 — Automatic saving

```text
Create document
Start recording
Speak for several minutes
```

Expected:

* The file is periodically updated while recording.
* A significant amount of recognized text is not lost if the application unexpectedly terminates.

---

## Test 7 — Long recording

Run a continuous recording session for at least 30–60 minutes.

Verify:

* Stable memory usage
* No major performance degradation
* No duplicated transcription
* No progressive increase in latency
* No audio buffer growth without bounds
* Correct auto-saving

---

## Test 8 — Microphone disconnect

Start recording and disconnect/disable the selected microphone.

Expected:

* The application detects the problem.
* The user receives a clear error/warning.
* The application does not crash.

---

## Test 9 — Application close during recording

Start recording and attempt to close the application.

Expected:

* Recording stops safely.
* Remaining processable audio is handled.
* Document is saved.
* Resources are released.
* Application closes cleanly.

---

# 41. Acceptance Criteria

The first version can be considered complete when all of the following are true:

* [ ] Windows production build works.
* [ ] User can create a `.txt` document.
* [ ] User can open an existing `.txt` document.
* [ ] Recording cannot start without an open document.
* [ ] User can start/stop recording using a button.
* [ ] User can start/stop recording using a global hotkey.
* [ ] Recording continues when the application loses focus.
* [ ] Recording continues while the application is minimized.
* [ ] Russian speech is transcribed locally.
* [ ] Transcription appears with low practical latency.
* [ ] Transcription does not require an Internet connection.
* [ ] There are no artificial recording duration limits.
* [ ] Text is editable.
* [ ] User can continue recording from the cursor position.
* [ ] Partial transcription does not produce duplicated text.
* [ ] Document is automatically saved during recording.
* [ ] Document is saved after recording stops.
* [ ] UTF-8 Russian text is preserved correctly.
* [ ] User can select and copy text.
* [ ] User can select the microphone.
* [ ] Microphone input level is displayed.
* [ ] Speech recognition model can be configured where appropriate.
* [ ] Application handles microphone errors gracefully.
* [ ] Application handles closing during recording safely.
* [ ] Long recording sessions do not cause uncontrolled memory growth.
* [ ] Production build can be installed and launched without development tools.

---

# 42. Development Approach

Before writing the complete application, first analyze the requirements and choose the most suitable technical approach.

In particular, evaluate:

1. Which local speech-to-text engine provides the best Russian recognition quality.
2. Which model provides the best balance between accuracy and latency.
3. How to achieve streaming/near-real-time transcription.
4. How to implement Windows global hotkeys reliably.
5. How to capture microphone audio continuously in the background.
6. How to efficiently handle partial and confirmed transcription results.
7. How to implement safe automatic saving.
8. How to package the speech recognition model with or alongside the application.
9. How to achieve the best performance on both CPU and available GPU hardware.
10. How to produce a reliable Windows production build.

Do not start by blindly implementing the UI.

First establish the technical architecture, especially the speech recognition pipeline.

Then implement the application incrementally.

---

# 43. Important Priorities

When making technical decisions, use the following priority order:

### 1. Speech recognition accuracy

Russian speech recognition quality is the highest priority.

### 2. Low latency

Text should appear as close to real time as reasonably possible.

### 3. Fully local processing

No mandatory cloud services or API limits.

### 4. Reliability

The application must remain stable during long recording sessions.

### 5. Simplicity

The UI should be easy to understand and use.

### 6. Maintainability

The architecture should make future improvements and additional languages possible.

### 7. Visual design

The application should look clean and professional, but visual complexity is less important than functionality and performance.

---

# 44. Final Product Concept

The final application should feel like a **simple text editor with a powerful built-in voice transcription system**.

The ideal user experience is:

```text
Open/Create document
        ↓
Place cursor
        ↓
Press Record
        ↓
Speak Russian
        ↓
Text appears in real time
        ↓
Switch to other applications if necessary
        ↓
Speech recognition continues
        ↓
Stop recording
        ↓
Review and correct text
        ↓
Copy the final text
```

The application should feel lightweight, reliable, private, and unrestricted by cloud transcription limits.
