<p align="center">
  <img src="assets/nemo-banner.svg" alt="NEMO Banner" width="100%" />
</p>

<p align="center">
  <a href="https://nemo-runtime.netlify.app"><img src="https://img.shields.io/badge/Netlify-Live%20Landing%20Page-00C7B7?style=for-the-badge&logo=netlify&logoColor=white" alt="Live Landing Page" /></a>
  <img src="https://img.shields.io/badge/Tests-42%2F42%20Passing-10b981?style=for-the-badge&logo=pytest&logoColor=white" alt="Tests" />
  <img src="https://img.shields.io/badge/Windows-11%20Native-0078D4?style=for-the-badge&logo=windows&logoColor=white" alt="Windows 11 Native" />
  <img src="https://img.shields.io/badge/Whisper-Local%20INT8-00f0ff?style=for-the-badge&logo=openai&logoColor=black" alt="Whisper Local" />
  <img src="https://img.shields.io/badge/Python-3.11+-3776AB?style=for-the-badge&logo=python&logoColor=white" alt="Python 3.11+" />
  <img src="https://img.shields.io/badge/License-MIT-f59e0b?style=for-the-badge" alt="License" />
</p>

<p align="center">
  <strong>Autonomous, voice-first Windows developer operating runtime that automates coding, desktop GUI tasks, hardware diagnostics, database introspection, and deployments natively on Windows 11.</strong>
</p>

<p align="center">
  <a href="https://nemo-runtime.netlify.app">🌐 Live Web Demo</a> •
  <a href="#-one-click-install">🚀 Quickstart</a> •
  <a href="#-voice-assistant--floating-avatar-pill">🎙️ Voice Assistant</a> •
  <a href="#-features--natural-language-catalog">⚡ Capabilities</a> •
  <a href="#-architecture">🏗️ Architecture</a> •
  <a href="USER_GUIDE.md">📖 User Guide</a>
</p>

---

## 🚀 One-Click Install

### Direct PowerShell One-Liner
Run this command in Windows PowerShell to automatically install prerequisites, register the global `nemo` command, and configure your local workspace:

```powershell
irm https://raw.githubusercontent.com/Omkar-Hundre/Nemo/main/scripts/install.ps1 | iex
```

### Or Share the Distributable Zip
1. Grab `dist/Nemo-Windows-Installer.zip` from releases.
2. Unzip on any Windows 10/11 system.
3. Double-click `install.bat`. It auto-detects `uv`, builds local isolated environments, prompts for permissions, and wires everything in under 15 seconds.

---

## 🖥️ Live Terminal & Taskbar Pill Interface

<p align="center">
  <img src="assets/demo-interface.svg" alt="NEMO Interface" width="100%" />
</p>

Run commands directly in plain English — no complex subcommands needed:

```powershell
# 1. Vision-Guided Snipping & Web Fix Synthesis
nemo "snip the error popup on screen and search fix"

# 2. Jarvis Canvas & Mathematical Image Annotation
nemo "draw a red box around the submit button in screenshot.png"

# 3. Windows Terminal 3-Pane Developer Layout
nemo "open 3-pane terminal with backend, frontend, and docker logs"

# 4. Instant YouTube Autoplay Discovery
nemo "open YouTube in Chrome and play lofi beats"

# 5. Native Hardware Microphone Capture
nemo "record 10 seconds of mic audio"

# 6. Interactive Hands-Free Voice Controller
nemo voice --autostart
```

---

## 🎙️ Voice Assistant & Floating Avatar Pill

NEMO turns your machine into a hands-free voice-controlled development workstation:

```powershell
nemo voice --autostart
```

- **Local Whisper INT8**: High-accuracy local speech-to-text without streaming sensitive source code or credentials over the cloud.
- **Wake-Word Detection**: Activates hands-free on `"Nemo"` or `"Hey Nemo"`.
- **Always-on-Top Floating Taskbar Pill**: Minimalist translucent status indicator in the bottom-right corner that pulses green when listening, blue when executing, and red when alerting.
- **Cinema & Gaming Auto-Hide**: Detects full-screen video playback and games via Win32 `GetForegroundWindow` / DirectShow and conceals itself automatically.
- **Tiered Concurrency & Idempotency**:
  - **Tier 1 (Emergency/Control)**: *"Nemo, stop"*, *"cancel that"* immediately pauses execution without corrupting files.
  - **Tier 2 (Concurrent Query)**: *"Nemo, how much RAM is free?"* executes in parallel without pausing long builds.
  - **Tier 3 (Mutating Task)**: Sequential FIFO task queue with a 15-second debounce window to prevent repeated execution.

---

## 🏗️ Architecture

<p align="center">
  <img src="assets/architecture-diagram.svg" alt="NEMO Architecture" width="100%" />
</p>

### Key Architectural Layers:
1. **Audio Ingestion Plane**: WASAPI 44.1kHz continuous sliding 500ms ring buffer prevents syllable clipping. WebRTC Voice Activity Detection gates fan noise and keystrokes.
2. **Idempotency & Concurrency Controller**: SHA256 intent normalization, semantic state checking, and prioritized task dispatching.
3. **Agent Orchestrator**: Multi-step planner powered by NVIDIA Nemotron 120B with automatic session memory consolidation and SQLite vector indexing.
4. **Windows Native Execution**: Deep desktop bindings via Win32 GDI+, `pywinauto` UIA accessibility trees, DirectShow headless camera capture, and Windows Terminal IPC.
5. **Ground-Truth Verification Gates**: Every action must pass file existence checks, AST syntax verification, and regression tests before completion is declared.

---

## ⚡ Features & Natural Language Catalog

### 1. Vision-Guided Snipping & Region Crop (`snip_screen`)
- Captures full-resolution desktop display across multi-monitor setups.
- Uses UIA window introspection and Nemotron 3.5 VL to locate popups, buttons, or dialogs.
- Automatically crops to the exact bounding box and saves to `%USERPROFILE%\Downloads`.
- Synchronizes with Windows Clipboard in `CF_DIB` format (press `Ctrl+V` to paste into Discord, Slack, or Paint).
- Automatically opens in **Windows Snip & Sketch** (`SnippingTool.exe`).
- When invoked with *"search fix"*, extracts OCR error text and performs web research on DuckDuckGo to return a verified fix.

### 2. Jarvis Canvas & Visual Annotator (`annotate_image`)
- Uses Python's mathematical imaging engine (`PIL.ImageDraw`) to draw pixel-perfect annotations:
  - **Bounding Boxes**: Crisp rounded corners, customizable stroke width, vibrant colors, semi-transparent highlight tint, and pill badge labels.
  - **Directional Arrows**: Clean line shafts with mathematically computed triangular arrowheads pointing directly at target coordinates.
  - **Marker Highlights**: Semi-transparent colored highlight overlays across text or UI sections.
- Opens annotated results directly in Snip & Sketch ready for sharing.

### 3. The 5 Core Developer Beast Tools
- `git_operations`: Autonomous branching, staging, semantic conventional commits, upstream pushing, and staged diff reviews.
- `database_inspector`: Safe SQLite schema introspection, column types, primary/foreign keys, indexes, and read-only query execution.
- `api_tester`: Async HTTP/REST client supporting GET, POST, PUT, DELETE with millisecond latency metrics (`response_time_ms`), headers, and JSON formatting.
- `system_inspector`: Real-time Win32 `GlobalMemoryStatusEx` RAM diagnostics (<1ms), disk space, active listening ports, and runaway process termination.
- `desktop_integration`: DirectShow webcam snapshots with 2-3s auto-exposure stabilization, multi-pane Windows Terminal layouts, and native Windows 11 toast notifications.

---

## 🛠️ Complete CLI Command Reference

```powershell
# Core Agent & Prompt
nemo "your task in plain English"   # Autonomous multi-step execution
nemo                                # Interactive conversational REPL

# Voice & Background Daemon
nemo voice --autostart              # Launch hands-free voice listener & floating pill
nemo daemon start --detach          # Start background worker daemon
nemo daemon status                  # Check background sessions and health
nemo daemon stop                    # Stop background daemon

# Diagnostics & Health
nemo status                         # Check runtime version, IDE, database, and credentials
nemo doctor --test-api              # Health check & live ping to NVIDIA NIM
nemo verify --test                  # Ground-truth test runner (42/42 tests)
nemo dependencies                   # Inspect detected manifests & package managers

# Memory & Knowledge Base
nemo memory status                  # View active records & vector memory metrics
nemo memory list                    # List learned project conventions
nemo memory search "SQLite"         # Search memories by semantic query
nemo memory backup                  # Atomic zero-downtime hot backup of SQLite database
nemo memory restore <backup.db>     # Restore database from archive

# Distributable Release Packaging
python scripts/package_release.py   # Re-package clean installer zip for distribution
```

---

## 🧪 Ground-Truth Verification

All functionality is backed by automated tests testing real Win32 APIs, AST trees, filesystem manipulation, and process lifecycles:

```powershell
uv run pytest tests/test_voice_avatar.py tests/test_beast_tools.py
```

```text
============================= test session starts =============================
platform win32 -- Python 3.12.12, pytest-9.2.0, pluggy-1.7.0
collected 42 items

tests\test_voice_avatar.py .................                             [ 40%]
tests\test_beast_tools.py .........................                      [100%]

============================= 42 passed in 100% ==============================
```

---

## 🌐 Live Web Experience

Visit the official NEMO landing page deployed on Netlify:  
👉 **[https://nemo-runtime.netlify.app](https://nemo-runtime.netlify.app)**

---

## 📄 License

Distributed under the **MIT License**. Built for the Windows developer community by **[Omkar Hundre](https://github.com/Omkar-Hundre)**.
