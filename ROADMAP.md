# NEMO Developer Runtime — Master Feature Roadmap & Architecture Blueprint

> **Vision**: Transform NEMO into an autonomous, voice-driven, AI-native Windows developer operating environment that automates coding, desktop GUI tasks, database queries, deployment safety, and developer workflows directly on your machine.

---

## 1. Verified Core Foundation (Current State: 145/145 Tests Passing)

All foundational systems are built natively using existing dependencies, zero unnecessary abstractions, and backed by 145 automated edge-case tests:

- **5 Core Developer Beast Tools**:
  - `git_operations`: Branching, staging, atomic unstaging with empty-repo fallback, semantic conventional commits, upstream push, logs, and staged diffs.
  - `database_inspector`: SQLite schema introspection, column definitions, primary/foreign keys, indexes, table row counts, and safe read-only queries with write protection.
  - `api_tester`: Async HTTP/REST client supporting GET, POST, PUT, DELETE with latency tracking (`response_time_ms`), custom headers, Bearer tokens, and JSON formatting.
  - `system_inspector`: Real-time Win32 `GlobalMemoryStatusEx` RAM diagnostics (<1ms), disk space, active listening ports, process enumeration, and safe process termination.
  - `desktop_integration`: Windows clipboard read/write via PowerShell stdin streaming (immune to quoting/escaping), and native Windows desktop toast notifications.
- **Autonomous Web Researcher & Doc Scraper** (`web_researcher`):
  - Live web queries via DuckDuckGo with TLS browser fingerprint impersonation.
  - Clean Markdown extraction from technical docs (MDN, blogs) via Trafilatura (zero HTML tag soup or cookie clutter).
  - PyPI package specifications, versions, licenses, and dependencies via official PyPI JSON API.
  - Wikipedia encyclopedic concept definitions via Wikipedia REST API.
  - Deep multi-source research synthesis combining search citations with extracted article text.
- **Microsoft Natural Neural Voice Engine** (`nemo.voice.speaker`, `voice_speak`, `nemo speak`):
  - High-fidelity human-like speech powered by Microsoft Natural Neural TTS (`edge-tts` at `+15%` rate).
  - Personas: Jenny, Guy, Aria, Prabhat, Neerja.
  - Native Windows Multimedia playback (`winmm.dll`) with zero external audio dependencies.
- **Windows Desktop GUI Automation** (`gui_automation`):
  - Direct accessibility-tree desktop automation via `pywinauto` (UIA backend) and Win32 desktop binding.
  - Launch applications (`notepad`, `calc`, `code`), list active windows with PIDs.
  - Focus, minimize, maximize, restore, close windows.
  - Click buttons and menu items by name or Automation ID, type text and shortcuts (`^s`, `{ENTER}`).
  - Accessible control hierarchy inspection (`inspect_tree`).
- **Windows Auto-Start Logon Daemon** (`nemo daemon autostart`):
  - Lightweight, non-blocking startup registration at `%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup`.
  - Zero administrator permissions needed, easily enabled/disabled/audited via CLI.
- **Document Intelligence Engine** (`read_document`, `generate_document`, `generate_presentation`):
  - DOCX generation with multi-tier headings (Title, H1, H2, H3), rich multi-column tables, bold headers, empty cells, Consolas code blocks, styled callouts, and raw PNG byte image embedding.
  - Document reading with structural heading trees, table parsing, image counts, word counts, and metadata round-tripping.
  - Multi-page PDF extraction with `max_pages` bounds and corrupt PDF error recovery.
  - CSV delimiter auto-sniffing (`,`, `;`, `\t`, `|`) and multiline quoted field handling.
  - Standalone presentation slides with keyboard navigation and dark/light themes.
- **Deployment & CI/CD Safety Auditor** (`analyze_deployment`):
  - Secret leak blockers (unignored `.env`, `.env.local`, `.env.production`).
  - Actively tracked Git secret blocker (`git ls-files .env`).
  - Pending diff regex scanning for API tokens (`ghp_`, `nvapi-`, `sk-`, `AKIA`).
  - Target platform guidance (`netlify`, `vercel`, `github`, `all`).
- **Human-First Session Management & History**:
  - Interactive Windows console selector (`↑` / `↓` arrow keys, `Enter`, `1–9` direct jump, `Esc`).
  - 1-based index resolution (`resume 1`, `resume 2`).
  - Title keyword search (`resume refactor`) and short UUID prefix lookup.
  - Session branching (`fork`), renaming (`rename`), and Markdown transcript export (`export`).

---

## 2. Voice Control & Autonomous Desktop GUI Automation (The Next Leap)

```
                            ┌────────────────────────┐
                            │   Windows Background   │
                            │   Logon Auto-Start     │
                            └───────────┬────────────┘
                                        │
                          [Low-Power Audio Thread]
                                        ▼
                              ┌───────────────────┐
                              │ Wake-Word Engine  │
                              │   "Nemo / Hey"    │
                              └─────────┬─────────┘
                                        │ Triggered
                                        ▼
                              ┌───────────────────┐
                              │ Speech-to-Text    │
                              │ (Fast STT Engine) │
                              └─────────┬─────────┘
                                        │ Intent
                                        ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                    NEMO Agentic Operating Core                          │
│         (NVIDIA Nemotron Super VL 120B + Context + Memory)              │
└───────────────┬───────────────────────────────────────┬─────────────────┘
                │ Action / Tool Call                    │ Conversational Voice
                ▼                                       ▼
    ┌───────────────────────┐               ┌────────────────────────┐
    │  Windows GUI Engine   │               │  Microsoft Neural TTS  │
    │ (pywinauto + UIA Tree)│               │ (`edge-tts` Natural)   │
    └───────────────────────┘               └────────────────────────┘
```

### A. Microsoft Neural Text-to-Speech Engine (`nemo.voice.speaker`)
- **No Robotic Voices**: Replaces legacy SAPI5 robotic speech with Microsoft’s natural neural voices (the same models powering Microsoft Copilot and Edge).
- **Available Personas**:
  - `en-US-JennyNeural`: Warm, natural, friendly conversational assistant.
  - `en-US-GuyNeural`: Energetic, modern male companion.
  - `en-IN-PrabhatNeural` / `en-IN-NeerjaNeural`: Natural Indian English with authentic cadence.
- **Personality & Tone**:
  - Dynamic rate (`+15%`) for energetic, non-boring conversational delivery.
  - Humorous, sharp, human-touch responses configured through agent prompt steering.
- **Portability**: Uses `edge-tts`—100% free, keyless, and zero-configuration on any Windows machine.

### B. Background Voice Control & Wake-Word Listening (`nemo.voice.listener`)
- **Wake Word**: Continuous low-power listening for *"Nemo"* or *"Hey Nemo"*.
- **Local Speech-to-Text**: Low-latency transcription capturing natural voice requests.
- **Hands-Free Task Dispatch**: Transcribed audio routes directly into `AgentOrchestrator.run_task` without opening a terminal window.

### C. Windows Logon Auto-Start Daemon (`nemo.daemon.autostart`)
- **Auto-Boot**: Registers a Windows Scheduled Task or `HKCU\...\Run` entry so NEMO initializes silently when your laptop powers on.
- **Resource Footprint**: Runs as a lightweight background tray daemon (<25MB RAM in idle listening mode).

### D. Windows Desktop GUI Automation Tool (`pywinauto` with UIA Backend)
- **Why `pywinauto` (UIA)**: Unlike fragile pixel-coordinate tools (`pyautogui`) that break when windows move or display DPI scaling is set to 125%/150%, `pywinauto` queries Microsoft's native UI Automation accessibility tree (`AutomationId`, ControlType, Name).
- **Key Capabilities**:
  - `open_app(name)`: Launch apps (`notepad`, `calc`, `code`, `spotify`, `explorer`, browser).
  - `click_control(window, control_name, control_type)`: Click buttons, menus, tabs.
  - `type_text(window, text, control_name)`: Type into text fields, search bars, or editors.
  - `window_action(window, action)`: Maximize, minimize, tile, focus, or close windows.
  - `read_ui_tree(window)`: Inspect all accessible controls and text within an active window.

---

## 3. The 5 Core Developer Beast Tools

### 1. Git Operations & GitHub Sync Tool (`git_operations`)
- **Purpose**: Autonomous, safe Git operations directly through natural language.
- **Capabilities**:
  - `status`: Staged, unstaged, untracked files, current branch, ahead/behind status.
  - `branch`: List branches, create new branch, checkout branch (`git checkout -b <name>`).
  - `stage`: Stage specific files or all (`git add <files>`).
  - `unstage`: Unstage files (`git restore --staged <files>`).
  - `commit`: Auto-generate semantic conventional commit message based on staged diff and commit.
  - `push`: Push to remote (`git push -u origin <branch>`) with dry-run verification.
  - `log`: Review commit history (hash, author, date, message).

### 2. Database Explorer & SQL Query Engine (`database_inspector`)
- **Purpose**: Inspect local databases, query data, and verify schema migrations.
- **Capabilities**:
  - Supports SQLite (`.db`, `.sqlite`, `.sqlite3`), PostgreSQL, and MySQL.
  - `list_tables`: Enumerate all tables, views, and row counts.
  - `schema`: Inspect column definitions, data types, primary/foreign keys, and indexes.
  - `query`: Execute read-only SQL queries (`SELECT`, `PRAGMA`, `EXPLAIN`) with safety guards against accidental `DROP` / `DELETE` without explicit authorization.
  - Formatted tabular output with pagination and execution latency metrics.

### 3. API & Webhook Testing Client (`api_tester`)
- **Purpose**: A native CLI Postman/curl tool built into the assistant.
- **Capabilities**:
  - HTTP Methods: `GET`, `POST`, `PUT`, `PATCH`, `DELETE`, `HEAD`.
  - Supports custom headers, Bearer tokens, API keys, and basic authentication.
  - Automatic JSON request payload formatting and response pretty-printing.
  - Metrics: Response latency (ms), HTTP status code, response headers, and content size.
  - Query parameter builder and form-urlencoded payload support.

### 4. Live Windows System & Hardware Inspector (`system_inspector`)
- **Purpose**: Real-time diagnostic and process management tool for local dev servers and resource monitoring.
- **Capabilities**:
  - `summary`: CPU core utilization, total/available RAM, and disk storage metrics.
  - `processes`: List top memory/CPU processes or search processes by name (e.g. `node.exe`, `python.exe`, `uvicorn.exe`).
  - `kill`: Terminate hung background dev servers or runaway processes by PID or image name.
  - `network`: Inspect active listening ports and established socket connections.

### 5. Windows Clipboard & Native Toast Notifications (`desktop_integration`)
- **Purpose**: Bridge agent output directly into Windows desktop interaction.
- **Capabilities**:
  - `clipboard_copy`: Copy generated code snippets, Markdown tables, or Git diffs directly to the Windows clipboard.
  - `clipboard_read`: Paste and analyze clipboard contents inside NEMO.
  - `notify`: Fire native Windows 10/11 toast notifications when background tasks, builds, or test suites complete (e.g., *"Regression suite passed: 106 tests green"*).

---

## 4. Additional Advanced Developer Features (Extended Roadmap)

To make NEMO an indispensable, complete development runtime, the following complementary modules are scheduled:

### 6. Autonomous Web Researcher & Doc Scraper (`web_researcher`)
- Query live technical documentation (MDN, PyPI, GitHub releases, official frameworks).
- Extract and summarize changelogs, breaking changes, and migration guides into concise Markdown.

### 7. AST Semantic Refactoring & Symbol Renamer (`ast_refactor`)
- Project-wide symbol renaming using Python AST traversal.
- Prevents substring replacement accidents (e.g. renaming `user` without mutating `username` or comments).
- Generates clean unified diffs before applying changes.

### 8. Docker & Container Runtime Controller (`docker_controller`)
- Introspect local Docker daemon (containers, images, volumes).
- View container logs (`docker logs --tail 100 <container>`).
- Start/stop dev containers (`docker compose up -d`, `docker compose down`).

### 9. Dependency & Security Vulnerability Auditor (`security_auditor`)
- Scan `pyproject.toml`, `requirements.txt`, and `package.json` against known CVE vulnerability databases.
- Flag outdated dependencies and generate upgrade recommendations.

### 10. Windows System Tray Companion & Status Bar (`tray_companion`)
- Lightweight Windows system tray icon (`NEMO` logo).
- Right-click menu: Quick Voice Prompt, Open Chat, View Memory, Restart Daemon, Exit.
- Visual status indicator: Green (Idle), Blue (Executing Task), Red (Error / Alert).

---

## 5. Implementation Status & Priority Matrix

| Phase | Module | Target Tools | Complexity | Status |
| :---: | :--- | :--- | :---: | :---: |
| **Phase 1** | **Git Operations** | `git_operations` | Low | **COMPLETE (100% Tested)** |
| **Phase 2** | **Database Inspector** | `database_inspector` | Low | **COMPLETE (100% Tested)** |
| **Phase 3** | **API Tester** | `api_tester` | Low | **COMPLETE (100% Tested)** |
| **Phase 4** | **System & Desktop** | `system_inspector`, `desktop_integration` | Low | **COMPLETE (100% Tested)** |
| **Phase 5** | **Natural Voice Engine** | `nemo.voice.speaker`, `voice_speak`, `nemo speak` | Medium | **COMPLETE (100% Tested)** |
| **Phase 6** | **Windows GUI Automation** | `WindowsGuiTool` (`pywinauto` UIA) | Medium | **COMPLETE (100% Tested)** |
| **Phase 7** | **Logon Auto-Start Daemon** | `nemo daemon autostart` | Low | **COMPLETE (100% Tested)** |
| **Phase 8** | **Web Researcher & Doc Scraper** | `web_researcher` (DDGS + Trafilatura + PyPI + Wiki) | Medium | **COMPLETE (100% Tested)** |
| **Phase 9** | **Continuous Wake-Word Listener** | `nemo.voice.listener` (`System.Speech` / STT) | Medium | In Progress |
| **Phase 10** | **AST Semantic Refactoring** | `ast_refactor` (Python AST symbol rename) | Medium | Planned |
| **Phase 11** | **Container Controller** | `docker_controller` (local Docker engine) | Medium | Planned |

---

*This document is committed to version control and serves as the single source of truth for NEMO's architectural evolution.*

