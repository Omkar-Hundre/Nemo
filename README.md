# NEMO — AI-Native Developer Operating Environment for Windows

NEMO is a persistent, project-aware developer operating environment designed specifically for Windows. Powered by **NVIDIA NIM** (Nemotron 3.5 Super VL 120B & Nemotron 3.5 Embed 1B), NEMO acts as an autonomous operating, inspection, and coordination layer — managing dev servers, checking ports, scaffolding tech stacks, reading and generating docs, and verifying outcomes with ground-truth rigor.

> 🗺️ **Looking for upcoming features?** Check out the [Feature Roadmap & Architecture Blueprint](file:///d:/Nemo/ROADMAP.md) detailing Voice Control (`edge-tts`), Windows GUI Automation (`pywinauto`), Git Sync, Database Explorer, API Tester, and Desktop Integration.

---

## ⚡ Direct Prompt Execution (No `nemo task` Needed!)

You don't need to prefix commands with `nemo task`. Simply pass your instruction directly:

```powershell
# Directly run any instruction in plain English:
nemo "inspect this project, install missing dependencies, start dev server, and open the browser"
nemo "scaffold a React TypeScript project named client-dashboard with Tailwind"
nemo "check if port 3000 is occupied, find the process PID, and kill it"
nemo "generate an architecture report at docs/system.docx and verify all sections"
nemo "generate an interactive presentation slide deck at slides.html and open it"
nemo "what can you do?"

# Or launch the interactive chat REPL by running nemo with no arguments:
nemo
```

---

## 🧠 Automated Background Memory (No "Remember This" Required)

NEMO **automatically extracts and memorizes** durable technical knowledge as it executes tasks:
- **Zero manual work**: You never have to manually run `nemo remember`.
- **Automatic Extraction**: When a task completes, NEMO's background consolidator extracts key architectural decisions, dev ports, framework choices, and project conventions.
- **Deduplication**: Identical or duplicate facts are automatically deduplicated.
- **Instant Recall**: Future prompts automatically recall relevant memories in the system prompt.

---

## 🚀 One-Click Windows Installer (Share with Friends)

You can share NEMO with anyone on Windows in one single package:

### Option A: Share Pre-Packaged Release Zip
1. Locate `dist/Nemo-Windows-Installer.zip` (0.18 MB).
2. Send it to your friend.
3. They unzip the archive and double-click:
   ```cmd
   install.bat
   ```
4. NEMO automatically sets up `uv`, installs the global `nemo` command in their Windows User `PATH`, prompts for their NVIDIA API key (if needed), initializes the database, and is ready in 10 seconds!

### Option B: Build a Fresh Installer Package Anytime
```powershell
python scripts/package_release.py
```

---

## 🛠️ Complete Native Tool Matrix (25 Tools)

| Category | Native Tool | Description |
| :--- | :--- | :--- |
| **Network & Ports** | `port_manager` | Inspects Windows TCP stack (`netstat -ano -p tcp`), identifies PID and process name (`node.exe`, `python.exe`), or kills occupant process trees (`taskkill /PID <pid> /T /F`). |
| | `http_probe` | Tests endpoints via `httpx`. Checks HTTP status, latency in ms, content-type, and body preview before browser launch. |
| **Files & Scaffolding** | `find_files` | Fast recursive glob search (`**/*.config.*`, `**/package.json`) with auto-exclusion of `.git`, `.venv`, `node_modules`, `dist`. |
| | `scaffold_project` | Non-interactive tech stack generator (`react-ts`, `vue-ts`, `nextjs`, `fastapi`, `node`) guaranteed never to hang on terminal prompts. |
| | `read_file` / `write_file` / `list_directory` | Full filesystem operations with L0-L2 risk boundaries. |
| **Documents & Slides** | `read_document` | Unified extractor for `.pdf` (`pypdf`), `.docx` (`python-docx`), `.csv`, `.tsv`, `.md`, `.json`. |
| | `generate_document` | Creates formatted `.docx` Word documents, responsive executive `.html` reports, or Markdown. |
| | `generate_presentation` | Builds standalone responsive HTML slide presentations with keyboard navigation (`←`/`→`/`Space`), fullscreen (`F`), and themes. |
| **Code Intelligence** | `get_codebase_summary` | Single-step architectural overview of all indexed modules, files, and AST symbols. |
| | `query_code_graph` | Graph traversal for callers, callees, imports, and declarations. |
| | `ast_grep` | Structural AST pattern search for functions, classes, decorators, and call sites without fragile regex. |
| | `search_code` / `lookup_symbol` | Keyword search across filenames and symbol definitions. |
| | `semantic_search_code` | 2048-dimensional dense vector search via NVIDIA Embeddings. |
| **Environment & Git** | `inspect_project_environment`| Detects ecosystem, manifests, lockfile, install status, and default URLs. |
| | `inspect_env_config` | Compares `.env` with `.env.example`, detects missing keys and unpopulated placeholders without leaking secrets. |
| | `git_diff` | Line-by-line inspection of unstaged and uncommitted changes against `HEAD`. |
| | `open_browser` / `open_in_ide` | Opens local URLs in default browser; navigates to line numbers in VS Code / Antigravity. |
| | `launch_background_process` | Detached server lifecycle management (`npm run dev`, `uvicorn`) with port readiness polling. |

---

## 💻 CLI Commands Reference

```powershell
# System & Diagnostics
nemo status                        # Check runtime version, IDE, database, and credentials
nemo doctor --test-api             # Health check & live ping to NVIDIA NIM
nemo verify --test                 # Run project test suite ground-truth check
nemo dependencies                  # Inspect detected manifests & package managers

# Memory Management
nemo memory status                 # View memory metrics & active records count
nemo memory list                   # List stored developer memories
nemo memory search "PostgreSQL"    # Search memories by keyword
nemo memory inspect <id>           # View complete memory metadata and timestamps
nemo memory export                 # Export active memories to formatted JSON
nemo memory backup                 # Atomic zero-downtime hot backup of SQLite database
nemo memory restore <file>         # Hot restore from backup archive

# Background Worker & Daemon
nemo daemon start --detach         # Start local IPC daemon in background
nemo daemon status                 # View active terminal sessions and daemon health
nemo daemon stop                   # Terminate running daemon server
nemo worker run --once             # Run one-shot maintenance pass (indexing + memory consolidation)
nemo worker index                  # Trigger background codebase indexing
nemo worker consolidate            # Run memory deduplication pass
```

---

## 🧪 Ground-Truth Verification

All test suites verify against real filesystem, AST syntax, process lifecycle, and database isolation:

```powershell
nemo verify --test
```
*(42/42 tests passing across 10 test suites)*
