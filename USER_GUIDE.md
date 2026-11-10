# 📖 NEMO — The Complete User Guide & Operating Manual

> **Welcome to NEMO!**  
> NEMO is an autonomous, project-aware developer operating environment designed specifically for Windows. Powered by **NVIDIA NIM** (Nemotron 3.5 Super VL 120B), NEMO acts as your tireless technical pair programmer and operating partner. It inspects repositories, runs servers, executes tests, reads and generates rich documents, manages Git and databases, and integrates natively with your Windows desktop.

This guide is designed to be your permanent handbook. Whether you are using NEMO yourself or sharing it with friends and teammates, this manual covers everything from installation to advanced workflows.

---

## 📑 Table of Contents

1. [1-Minute Quick Start & Installation](#1-1-minute-quick-start--installation)
   - [For You (Global Usage)](#for-you-global-usage)
   - [For Sharing with Friends](#for-sharing-with-friends)
2. [The 3 Ways to Use NEMO](#2-the-3-ways-to-use-nemo)
   - [Method 1: Direct Command (No `nemo task` needed)](#method-1-direct-command-no-nemo-task-needed)
   - [Method 2: Interactive REPL Chat (`nemo`)](#method-2-interactive-repl-chat-nemo)
   - [Method 3: Native Terminal Hybrid Commands](#method-3-native-terminal-hybrid-commands)
3. [Human-First Session Management & History](#3-human-first-session-management--history)
   - [Arrow-Key Interactive Selector](#arrow-key-interactive-selector)
   - [Resuming by Number or Keyword](#resuming-by-number-or-keyword)
   - [Renaming, Forking & Exporting Transcripts](#renaming-forking--exporting-transcripts)
4. [Automated Background Memory (Zero Manual Effort)](#4-automated-background-memory-zero-manual-effort)
5. [The 5 Core Developer Beast Tools](#5-the-5-core-developer-beast-tools)
   - [1. Git Operations & GitHub Sync (`git_operations`)](#1-git-operations--github-sync-git_operations)
   - [2. Database Explorer & SQL Engine (`database_inspector`)](#2-database-explorer--sql-engine-database_inspector)
   - [3. API & Webhook Testing Client (`api_tester`)](#3-api--webhook-testing-client-api_tester)
   - [4. Live Windows System & Hardware Inspector (`system_inspector`)](#4-live-windows-system--hardware-inspector-system_inspector)
   - [5. Windows Clipboard & Toast Notifications (`desktop_integration`)](#5-windows-clipboard--toast-notifications-desktop_integration)
6. [Document & Presentation Intelligence](#6-document--presentation-intelligence)
   - [Creating Styled Word Documents (.docx)](#creating-styled-word-documents-docx)
   - [Reading Documents (.docx, .pdf, .csv, .tsv)](#reading-documents-docx-pdf-csv-tsv)
   - [Generating Interactive Slide Presentations](#generating-interactive-slide-presentations)
7. [Deployment & Safety Auditing](#7-deployment--safety-auditing)
8. [Real-World Step-by-Step Workflows](#8-real-world-step-by-step-workflows)
9. [Troubleshooting & FAQs](#9-troubleshooting--faqs)

---

## 1. 1-Minute Quick Start & Installation

### For You (Global Usage)
NEMO is installed as a global Windows tool in your user path. You can open **PowerShell** or **Command Prompt** in **any folder or drive** (e.g., `C:\Projects\my-app`, `D:\work`, `Desktop`) and run `nemo` immediately:

```powershell
# Open interactive session in your current folder:
nemo

# Or run any prompt directly:
nemo "inspect this project and tell me what it does"
```

### For Sharing with Friends
You can give NEMO to any friend or colleague with a single pre-built installer:

1. **Locate the Installer Archive**:
   - `dist/Nemo-Windows-Installer.zip` (around ~0.2 MB).
2. **Send it to your friend**:
   - Share via Google Drive, Discord, Telegram, or flash drive.
3. **Friend installs in one click**:
   - They extract the zip file.
   - Double-click **`install.bat`**.
   - The installer checks Python, installs NEMO into `~/.local/bin/nemo.exe`, adds it to their Windows PATH, and validates the installation.
   - They open a new terminal and type `nemo`!

---

## 2. The 3 Ways to Use NEMO

### Method 1: Direct Command (No `nemo task` needed)
You don't need to type `nemo task "..."`. Just pass your instruction in plain quotes:

```powershell
# Dev server and port management:
nemo "check if port 3000 is occupied, find the process PID, and kill it"

# Code scaffolding:
nemo "scaffold a FastAPI backend project named backend_service"

# Document creation:
nemo "generate an architecture report at docs/architecture.docx with a metrics table"

# Codebase questions:
nemo "what dependencies does this project have and are there any security issues?"
```

### Method 2: Interactive REPL Chat (`nemo`)
Type `nemo` without any arguments to enter the dedicated interactive terminal runtime:

```powershell
PS D:\MyProject> nemo
```
```text
╭────────────────────────────────────────── NEMO v0.1.0 — Developer Runtime ───────────────────────────────────────────╮
│ NEMO ASSISTANT ● Connected                                                                                           │
│                                                                                                                      │
│ Active Project:  MyProject (D:\MyProject)                                                                            │
│ IDE Adapter:     antigravity                                                                                         │
│ Memory System:   Synchronized                                                                                        │
│ Code Index:      24 files up to date                                                                                 │
│                                                                                                                      │
│ Usability: 'resume' (↑/↓ arrow menu), 'history', 'rename', 'fork', 'export', 'new'                                   │
╰──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────╯
nemo> can you check the git status and create a new feature branch called login-ui?
```

### Method 3: Native Terminal Hybrid Commands
Inside the interactive REPL, you can execute native Windows commands or run developer tools directly:

```text
nemo> dir
nemo> git status
nemo> npm test
nemo> code .
```
NEMO automatically recognizes whether your input is a native terminal command or an AI instruction and handles it with zero latency.

---

## 3. Human-First Session Management & History

Never worry about losing context or typing long machine UUIDs. NEMO is built with human-friendly navigation:

### Arrow-Key Interactive Selector
Whenever you type `resume` in the REPL (or `nemo resume` from the command line), an interactive terminal dialog opens:

```text
Select Session to Resume (Use ↑/↓ arrows, Enter to pick, 1-9 direct jump, Esc to cancel):
  ❯ [1] Refactor Authentication Service (2026-11-11 00:25) [4 msgs]
    [2] Benchmark Database Latency (2026-11-10 23:40) [6 msgs]
    [3] System Architecture Specification (2026-11-10 22:15) [2 msgs]
    [+] Start Fresh Session
```
- Press **`↑` / `↓`** to highlight any past session.
- Press **`Enter`** to instantly resume with full conversation context and memory.
- Press **`1`–`9`** for instant direct jumping.
- Press **`Esc`** to cancel.

### Resuming by Number or Keyword
If you already know what session you want:

| Command | Action | Example |
| :--- | :--- | :--- |
| `resume <#>` | Resume by 1-based number | `resume 1` (resumes most recent), `resume 2` (resumes 2nd) |
| `resume <keyword>` | Search title by keyword | `resume auth` (resumes "Refactor Authentication") |
| `new` | Start a fresh blank session | `new` |
| `history` | Print tabular list of sessions | `history` |

### Renaming, Forking & Exporting Transcripts

- **Rename a Session**:
  ```text
  nemo> rename Sprint 4 Backend Migration
  nemo> rename 2 Docker Compose Setup
  ```
- **Fork / Branch a Session**:
  Want to experiment with an alternate technical approach without losing your original session? Fork it:
  ```text
  nemo> fork
  nemo> fork 2
  ```
  This creates an independent clone with all previous messages preserved. Changes in the fork will never alter the original session.
- **Export Formatted Markdown Transcript**:
  Need to share a task log or conversation with a teammate or client?
  ```text
  nemo> export
  nemo> export 1
  ```
  Exports a clean, formatted Markdown file (`session_transcript_*.md`) complete with timestamps, developer instructions, and NEMO agent solutions.

---

## 4. Automated Background Memory (Zero Manual Effort)

You **never** have to tell NEMO to *"remember this"* or manually run memorization commands.

- **How it works**:
  When any task finishes, NEMO's background memory engine automatically extracts durable technical facts:
  - Port numbers used (e.g. `FastAPI runs on port 8000`, `Frontend on 3000`).
  - Framework conventions (e.g. `Tailwind CSS used with Vite`, `Prisma schema in prisma/schema.prisma`).
  - Architectural decisions (e.g. `SQLite database used for local dev`, `JWT tokens with 15-minute expiration`).
- **Deduplication**:
  Duplicate facts are automatically merged.
- **Instant Recall**:
  When you start a task tomorrow, NEMO automatically injects recalled project facts into its reasoning engine.
- **Inspect Your Memories**:
  ```powershell
  nemo memory list
  ```

---

## 5. The 5 Core Developer Beast Tools

NEMO includes 5 native tools designed to replace third-party desktop tools (Postman, DBeaver, Task Manager, Git GUI) directly inside your workflow:

### 1. Git Operations & GitHub Sync (`git_operations`)
Manage version control directly through natural commands:
- *"Check git status and tell me what is untracked."*
- *"Create a branch called `feat/dark-mode` and switch to it."*
- *"Stage all modified files and commit with a clean conventional commit message."*
- *"Push this branch to origin and set upstream."*
- *"Show me the last 5 commits with authors and dates."*

### 2. Database Explorer & SQL Engine (`database_inspector`)
Inspect local databases (`.db`, `.sqlite`, `.sqlite3`) and cloud databases (extracting `DATABASE_URL` from `.env`):
- *"List all tables in `app.db` and show their row counts."*
- *"Show me the schema, columns, and foreign keys for the `users` table."*
- *"Run a query to find the top 5 users created this week."*
- **Safety First**: By default, destructive write operations (`DROP`, `DELETE`, `ALTER`) are blocked to prevent accidental data loss.

### 3. API & Webhook Testing Client (`api_tester`)
Built-in CLI Postman/curl engine:
- *"Send a GET request to `http://localhost:8000/api/health` and check latency."*
- *"Send a POST request to `/api/login` with email `dev@nemo.ai` and password `secret`."*
- *"Send a test Stripe webhook payload to `http://localhost:3000/api/webhook`."*
- Returns formatted JSON, response time in milliseconds, HTTP status code, and headers.

### 4. Live Windows System & Hardware Inspector (`system_inspector`)
Real-time diagnostic and process management tool for local dev servers:
- *"Show me current CPU, RAM, and disk utilization."* (Uses native Win32 C-API in <1ms).
- *"List all active processes matching `node` or `python`."*
- *"What ports are currently in LISTENING state?"*
- *"Kill the runaway process on PID 14210."*
- **Protection**: Core Windows system processes (`explorer.exe`, `svchost.exe`, `system`) are strictly protected from accidental termination.

### 5. Windows Clipboard & Toast Notifications (`desktop_integration`)
Bridge NEMO directly with your Windows desktop:
- *"Copy this Dockerfile directly to my clipboard."* (Press `Ctrl + V` anywhere).
- *"Fix the error currently on my clipboard."* (Reads clipboard text directly without you pasting 50 lines).
- *"Run the full test suite and notify me when it's done."* (Fires a native Windows desktop toast notification when completed so you can safely Alt-Tab to other work).

---

## 6. Document & Presentation Intelligence

NEMO can author and read enterprise-grade documents without third-party office software installed.

### Creating Styled Word Documents (.docx)
NEMO can author beautifully formatted Word documents with:
- Multi-tier headings (Title, Level 1, Level 2).
- Tables with bold headers, zebra striping, and cell alignments.
- Code snippets formatted in **Consolas** font.
- Styled callout quotes for notes and warnings.
- Embedded PNG charts and diagrams with centered captions.

```powershell
nemo "generate an architecture report at docs/Architecture.docx with a table of microservices and an overview of our security model"
```

### Reading Documents (.docx, .pdf, .csv, .tsv)
Extract structured knowledge from complex files:
- **PDF**: Extracts multi-page text, page counts, metadata, and handles encrypted or scanned files gracefully.
- **DOCX**: Extracts structured heading hierarchy, full table rows/columns, image count, author, and word counts.
- **CSV / TSV**: Delimiter auto-sniffer automatically detects commas, semicolons, tabs, or pipes, preserving multiline quoted records.

```powershell
nemo "read metrics.csv, calculate the average latency, and summarize the findings"
nemo "read docs/API_Spec.docx and tell me what headers are required for the payment route"
```

### Generating Interactive Slide Presentations
Create standalone responsive HTML presentations with dark/light themes and keyboard arrow navigation:

```powershell
nemo "generate a slide deck at presentation.html explaining our Q1 engineering roadmap with 4 slides"
```
- Open in any browser (`presentation.html`).
- Press **`→` / `Space`** for next slide, **`←`** for previous.
- Press **`F`** for fullscreen mode.

---

## 7. Deployment & Safety Auditing

Before you push code to GitHub or deploy to Netlify/Vercel, ask NEMO to audit your workspace:

```powershell
nemo "audit this project for deployment readiness"
```

NEMO automatically scans for:
1. **Critical Secret Leaks**: Checks if `.env`, `.env.local`, or `.env.production` exist without being covered in `.gitignore`.
2. **Git Index Leaks**: Flags if sensitive `.env` files are already tracked in Git history (`git ls-files .env`).
3. **Hardcoded API Tokens**: Scans pending Git diffs for exposed tokens (`ghp_`, `nvapi-`, `sk-`, `AKIA`).
4. **Build Readiness**: Verifies `package.json` build scripts and checks if `dist` / `build` directories exist.
5. **Platform Recommendations**: Provides copy-paste deploy commands for Netlify (`netlify deploy --prod`) or Vercel (`vercel --prod`).

---

## 8. Real-World Step-by-Step Workflows

### Workflow 1: "I Just Cloned a New Repository"
```powershell
cd C:\Projects\new-service
nemo "inspect this codebase, install any missing dependencies, check the database configuration, and tell me how to run it"
```

### Workflow 2: "Port 3000 is Blocked"
```powershell
nemo "check why port 3000 is occupied, find the process PID, kill it, and start our dev server on port 3000"
```

### Workflow 3: "Fix Bug from Clipboard"
1. Copy an error stack trace from your browser console (`Ctrl + C`).
2. Run:
```powershell
nemo "analyze the error on my clipboard, find the responsible file in this project, and fix it"
```

### Workflow 4: "Prepare Safe GitHub Release"
```powershell
nemo "run the tests, audit for secret leaks, stage modified files, commit with a clean message, and push to origin"
```

---

## 9. Troubleshooting & FAQs

#### Q: Where does NEMO store my session history and memories?
**A:** Everything is stored locally on your machine in a SQLite database at:  
`~/.nemo/nemo.db` (usually `C:\Users\<YourUsername>\.nemo\nemo.db`). It is completely private and never uploaded to third-party cloud trackers.

#### Q: How do I switch to a clean session?
**A:** Inside the REPL, type `new`. From the command line, start a fresh query with `nemo "new task..."`.

#### Q: Can NEMO run when I'm in any drive (`D:\`, `E:\`, `C:\`)?
**A:** **Yes.** NEMO is installed globally in `~/.local/bin/nemo.exe`. It automatically detects the active folder you are in and sets it as the working project context.

#### Q: How do I update NEMO to the latest version?
**A:** Run:
```powershell
cd D:\Nemo
uv tool install --editable . --force
```

---

*This guide is continually updated as new capabilities (Voice Control, Windows GUI Automation, AST Refactoring) are released.*
