# NEMO

AI-Native Developer Operating Environment for Windows.

## Architecture
- **Runtime**: Python 3.12+ modular monolith with local background daemon and asynchronous worker.
- **AI Models**: NVIDIA NIM Nemotron 3.5 Super VL 120B (`nvidia/nemotron-3.5-super-vl-120b-a12b`) with streaming deliberation, and Nemotron 3.5 Embed 1B (`nvidia/nemotron-3.5-embed-1b`) 2048-d semantic embeddings.
- **Storage Layer**: Local SQLite/PostgreSQL with pgvector for semantic long-term memory; Neo4j knowledge graph projections (`CONTAINS`, `DECLARES`, `IMPORTS`, `CALLS`).
- **Execution & Security**: Native Windows PowerShell / CMD subprocess execution with detached process-tree tracking and L0-L3 risk policy sandbox.
- **Agent Depth & Verification**: Structured hypothesis deliberation (`thought` + `hypothesis`), reflection on failures, and automated ground-truth verification gates (`OutcomeVerifier`) checking filesystem existence, non-emptiness, AST syntax validation, and project test suite regression.

## Quickstart & CLI Commands

```powershell
# Setup & Health
nemo setup                     # Interactive verification wizard
nemo doctor --test-api         # System diagnostics & live NVIDIA NIM ping
nemo status                    # Fast local system metrics

# Deep Agent Workflows
nemo task "Refactor auth"      # Autonomous agent with hypothesis tracking & verification
nemo ask "Explain AST parser"  # Semantic ask with memory recall
nemo diagnose "pytest"         # Root-cause failure diagnosis via Nemotron

# Ground-Truth Verification & Code Intelligence
nemo verify --file src/app.py  # Verify file existence and AST syntax validity
nemo verify --test             # Run ground-truth project test suite
nemo dependencies              # Discover manifests, lockfiles, and validation scripts
nemo index                     # Incremental SHA-256 codebase indexing

# Persistent Terminal & Daemon
nemo sessions create -s powershell
nemo run "git status"
nemo daemon start --detach
```

## Running Verification Tests
```powershell
.\.venv\Scripts\python.exe -m pytest
```
