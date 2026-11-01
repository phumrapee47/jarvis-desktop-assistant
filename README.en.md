# Jarvis — a Thai-language voice assistant for Windows

🇹🇭 [ภาษาไทย](README.md) · 🇬🇧 English

A voice assistant that runs in the background on Windows. Say **"Hey Jarvis"** and give a spoken command. It shows a 3D orb and a message bubble
in the bottom-right corner of the screen. The brain is Claude (Haiku), speech is transcribed with Whisper on the GPU, and it controls the PC
by voice and by **hand gestures through the webcam**. It is designed with programmers in mind (git/GitHub status, a Claude Code bridge,
morning brief, memory and reminders).

> Status: a personal project under active development, tested on a single Windows 11 machine. No license yet (all rights reserved by default).
> Commands and replies are in Thai; the code comments and UI strings are mostly Thai.

## Features

| Area | Examples |
|---|---|
| Chat and PC control | Open/close any installed app (searched from the Start Menu), open websites / Google search, media and volume control, lock the screen, ask the time |
| Gmail (read-only) | "What emails do I have today?" |
| For programmers | Look at the screen / clipboard, git status of a project, a standup summary of recent work, PRs waiting for review, watch a process or run a build/test and report the result |
| Claude Code | Ask Claude Code to read a project (read-only), or let it edit files on a new branch (you must say "confirm") |
| Memory and reminders | "Remember that...", "Remind me at 3 pm to push", daily/weekday repeating reminders, an automatic morning brief |
| Hand gestures | Drag windows, swipe to switch windows, 👍👎 confirm/cancel, ✌️ look at the screen, ✊ play/pause, and an **air-mouse mode** |

## Setup

Requirements: Windows 11, Python 3.11, a microphone, (recommended) an NVIDIA GPU for Whisper medium, a webcam (gesture mode only).

```powershell
pip install -r requirements.txt
copy .env.example .env      # then put your ANTHROPIC_API_KEY in it (required)
python jarvis.py
```

The first run downloads the Whisper and wake-word models automatically. Startup takes roughly 1–2 minutes each time while the models load.

### Optional

- **Gmail:** create an OAuth client (type: Desktop) in Google Cloud, enable the Gmail API, and add your own address as a Test user.
  Save the downloaded JSON as `credentials.json` in this folder, then run `python gmail_tool.py` once to authorize (read-only scope).
- **GPU (CUDA):** `pip install nvidia-cublas-cu12 nvidia-cudnn-cu12==9.*` (already listed in requirements). If the GPU can't be used it falls back to Whisper `small` on CPU.
- **Gesture mode:**
  ```powershell
  python -m venv gesture_env
  gesture_env\Scripts\python -m pip install -r gesture_requirements.txt
  mkdir models
  # Download Google's MediaPipe hand model (~7.6 MB) to models\hand_landmarker.task
  Invoke-WebRequest https://storage.googleapis.com/mediapipe-models/hand_landmarker/hand_landmarker/float16/latest/hand_landmarker.task -OutFile models\hand_landmarker.task
  ```
  Turn it on from the tray icon ("โหมดท่ามือ (เปิดกล้อง)" = gesture mode, camera on) or say "turn on gesture mode", then hold an open palm for 1 second.
  The gestures are documented at the top of `gestures.py`.
- **Claude Code bridge:** install the Claude Code CLI and run `claude auth login`. Jarvis strips the API key from the environment before calling it, so it uses your plan's quota.
- **Autostart + auto-restart on crash:** point a Startup shortcut at `pythonw.exe supervisor.py` (you can quit from the tray menu).

## Gestures at a glance

First enable gesture mode, then hold an open palm ✋ for 1 second. With no hand visible for 5 seconds it disarms itself.

| Gesture | Action |
|---|---|
| 🤏 pinch thumb + index (other fingers extended), move | grab the window under the fingertip and drag it |
| 👋 swipe left / right | switch windows (Alt+Tab) |
| ✋ swipe down / up | minimize the active window / open Task View |
| 👍 / 👎 hold | confirm / cancel the action Jarvis is waiting on |
| ✌️ hold | have Jarvis look at the screen |
| ✊ hold | play / pause |
| ☝️ point with one finger (hold 0.5 s) | enter **mouse mode**: the real cursor follows your hand |
| mouse mode: 🤏 thumb + index | left click (tap), drag (pinch and hold) |
| mouse mode: thumb + middle finger | right click |
| mouse mode: ✌️ then move up/down | scroll |
| mouse mode: ✋ hold open palm | back to normal gesture mode |

In air-mouse mode, gestures become **real clicks**. Try it on a harmless window first.

## Layout

| File | Role |
|---|---|
| `jarvis.py` | main loop: wake word → record → Whisper → Claude (tool use) → speak; tray icon |
| `overlay.py` | 3D orb + message bubble, bottom-right (PyQt6 + a numpy shader) |
| `tools_pc.py` / `tools_dev.py` / `tools_memory.py` / `tools_brief.py` | tools Claude can call: PC control / programmer tools + confirmation gate / memory + reminders / morning brief |
| `gmail_tool.py` | read-only Gmail |
| `gestures.py`, `gesture_logic.py`, `gesture_worker.py` | gestures: decision logic, pose classification, camera process (runs in a separate venv) |
| `supervisor.py`, `watchdog.py` | restart on crash; detect hangs and dump stacks to a log |
| `tts_fallback.ps1` | offline Thai fallback voice (Windows OneCore) when edge-tts fails |
| `tests/` | regression tests (`python -m unittest discover tests -v`) |

## Safety design

- **There is no "run any command" tool**, because spoken commands can be mis-transcribed. New abilities are added only as narrow, specific tools.
- Anything that edits files or runs commands **requires you to say "confirm" (or give a 👍) yourself**. The check uses your actual speech/gesture, so Claude cannot confirm on your behalf. A confirmation is single-use, expires in 90 seconds, and "don't confirm" counts as a cancel.
- Claude Code can edit only git repos with no uncommitted changes, on a new branch, with no commit or push. Repos, worktrees and submodules are all recognized.
- Deleting a memory note or reminder needs exactly one clear target: empty/very short queries match nothing, and ambiguous queries are refused with a list (you can also use `#id`).
- Memory refuses secrets (keys/passwords/card numbers) and won't store text that came from email/web/screen content unless you said it yourself.
- The camera is off until you turn it on, processing is local, and frames are never saved or sent. (A screenshot is sent to the API only when you ask Jarvis to look at the screen.)
- Secrets and personal data (`.env`, `credentials.json`, `token.json`, `memory.json`, logs) are all in `.gitignore`.

## Tests

```powershell
python -m unittest discover tests -v
```

The tests use temporary files and temporary git repos (including a real worktree and a submodule); they never touch your real `memory.json` and never call Claude Code.

## Approximate cost

Claude Haiku through the API is roughly 0.05–0.25 THB (about a cent or less) per command — an estimate. Whisper, the wake word, speech output (edge-tts) and the Gmail API are free.
Work handed to Claude Code uses your Pro/Max plan quota.
