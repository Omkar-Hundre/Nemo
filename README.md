# NEMO

AI-Native Developer Operating Environment for Windows.

## Architecture
- Modular monolith + local daemon + background worker.
- Python 3.11+ runtime.
- Model provider: NVIDIA NIM (Nemotron 3.5 Super VL 120B).
- Storage: PostgreSQL + pgvector (core), Neo4j (graph projection), Redis (coordination).

## Development Setup
```powershell
uv venv --python 3.12
.venv\Scripts\activate
uv pip install -e .
```
