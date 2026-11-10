NEMO CLI — Production Technical Specification

Architecture finalized
 Pre-development specification

NEMO
AI-Native Developer Operating Environment
A persistent, project-aware AI agent that understands natural language, manages development environments, executes terminal operations, coordinates IDEs and maintains long-term memory.

ImplementationPython-first

PlatformWindows 11

MemoryHybrid

Execution policyApproval-based

AI inferenceNVIDIA NIM

Agent orchestrationLangGraph


Architecture specification v1.0
10 November 2026 · Implementation has not started

We are locking the following decisions:
Decision	Final selection
Project name	Undecided (NEMO is the working codename)
Primary language	Python
Architecture	Modular monolith + background daemon
Memory	PostgreSQL + pgvector + Neo4j + Redis
Agent framework	LangGraph
Model provider	NVIDIA NIM
Primary model	Nemotron 3.5 Super VL 120B
Operating system	Windows 11
Shell support	PowerShell, CMD, Git Bash, WSL
Execution policy	Autonomous with approval for risky operations
Initial deployment	Local-first
Future deployment	Cross-platform

An important change from our earlier recommendation: We are now committing to Python as the primary language, including the CLI, agent orchestration, execution manager and background daemon. We will not introduce a separate Node.js runtime merely to run the application.

This is a perfectly viable architecture. Python has a mature ecosystem for agent orchestration, code intelligence, database integrations, embeddings and Windows process management.

The system will be designed to support an independent frontend or IDE extension later without requiring us to rewrite the core.

Part I — Product definition and system boundaries
1. Product vision
NEMO is not a chatbot, a terminal wrapper or a code-generation utility.

It is a persistent local development agent that operates across the developer's machine.

Its primary responsibility is to translate developer intent into verified operations.

For example:
Developer:
Open my COSEM project in Antigravity.
Restore the previous development context
and check whether all dependencies are installed.


The system should:
1. Identify the intended project.
2. Resolve its actual filesystem location.
3. Retrieve the project's previous state.
4. Retrieve relevant personal and project memories.
5. Check whether the project is already indexed.
6. Detect the IDE installation.
7. Open the project.
8. Inspect its dependency manifests.
9. Compare installed dependencies against required dependencies.
10. Request approval where an operation requires it.
11. Install missing dependencies.
12. Verify the installation.
13. Record the completed task.
The key product requirement is that the system must not rely on the LLM's statements to establish whether an operation succeeded.

The operating system, process manager, filesystem and database are the sources of truth.
2. Product requirements
Functional requirements
- FR-01: Understand natural-language instructions.
- FR-02: Execute native terminal commands.
- FR-03: Maintain persistent terminal sessions.
- FR-04: Wait for command completion and capture exit codes.
- FR-05: Diagnose and repair development errors.
- FR-06: Maintain long-term personal memory.
- FR-07: Maintain independent memory for each project.
- FR-08: Index codebases and their relationships.
- FR-09: Integrate with IDEs.
- FR-10: Manage background operations.
- FR-11: Resume interrupted agent tasks.
- FR-12: Maintain an auditable execution history.
- FR-13: Support configurable execution permissions.
- FR-14: Work without requiring an external cloud backend.

Non-functional requirements:
Requirement	Engineering target
Startup	Under 2 seconds for warm CLI launch, excluding model calls
Local command routing	No LLM call for deterministic commands
Command tracking	Reliable exit status and process lifecycle
Memory persistence	Durable storage with backup and recovery
Indexing	Incremental, resumable and background
Security	Least-privilege execution
Reliability	Recoverable daemon and agent tasks
Extensibility	Pluggable tools, models, shells and IDEs
Portability	Windows-first, portable core interfaces

These are engineering targets, not measured performance claims.
3. Scope boundaries
We should explicitly define what NEMO can and cannot do.
Capability	Scope
Normal shell commands	Execute supported local commands
Development commands	Execute, monitor and troubleshoot
Project understanding	Static analysis plus optional runtime inspection
IDE management	Launch, navigate and communicate through supported adapters
Memory	Persistent, searchable and correctable
Autonomous changes	Within configured permissions
Administrator operations	Explicit authorization
Arbitrary GUI automation	Future extension, not core dependency
Unrestricted machine control	Not supported

NEMO should be an operating layer for development, not an unrestricted replacement for the operating system.
Part II — Final technology architecture
4. Technology stack
We are choosing a Python-first stack with a strict separation between application logic, AI reasoning, execution and storage.
4.1 Core technologies
Component	Final technology	Responsibility
Language	Python 3.12+	Primary application runtime
CLI framework	Typer	Commands and argument parsing
Terminal UI	Rich	Formatting, progress, tables
Interactive interface	Textual	Optional full-screen terminal interface
Validation	Pydantic v2	Typed data contracts
Configuration	Pydantic Settings	Configuration management
Async runtime	asyncio	Concurrent operations
Agent framework	LangGraph	Stateful agent workflows
LLM integration	NVIDIA NIM + OpenAI Python SDK	Model inference
Local API	FastAPI	Daemon communication
HTTP client	httpx	Async API communication
ORM	SQLAlchemy 2	Database operations
Migrations	Alembic	Schema migrations
File watching	watchdog	Project change detection
Code parsing	Tree-sitter	Syntax and symbol analysis
Search	ripgrep	Fast exact code search
Terminal	pywinpty + subprocess	Windows process and PTY management
Testing	pytest	Automated testing
Packaging	PyInstaller initially	Windows executable distribution

Python version policy: target Python 3.12 or newer, pin and test the exact minor version in the release environment.
4.2 Agent and AI dependencies
The AI layer should be independent of the chosen provider.
NEMO/
    ai/
        providers/
            base.py
            nvidia_nim.py
            openai_compatible.py

        models/
            registry.py
            configuration.py

        prompts/
            planner.py
            executor.py
            memory.py

        schemas/
            tool_call.py
            agent_response.py
            task_plan.py


Recommended packages:
langgraph
langchain-core
langchain-openai
openai
pydantic
httpx


We should use LangGraph's native state and checkpointing features for workflow management. Human approval should use interrupts and resumable checkpoints, rather than implementing an independent approval mechanism inside every tool. 

GitHub+1

4.3 Windows execution stack
For Windows, the execution layer needs special consideration.

I recommend:
- subprocess and asyncio.create_subprocess_exec for normal commands.
- pywinpty for interactive terminal sessions.
- Windows ConPTY through pywinpty.
- Windows Job Objects for process-tree management.
- Named pipes for local daemon communication.
- Windows Credential Manager or DPAPI for credentials.
pywinpty supports Windows ConPTY, making it a suitable candidate for persistent terminal sessions. 

PyPI

We should not force every command through a PTY. Non-interactive commands should use normal subprocess execution because it is simpler and gives more reliable exit-code handling.

5. NVIDIA model integration specification
The selected model is:

nvidia/nemotron-3.5-super-vl-120b-a12b

NVIDIA's model page documents the hosted API at:

https://integrate.api.nvidia.com/v1

The API can be accessed using the OpenAI Python SDK. The model supports reasoning, coding, tool calling and image/video inputs. 

NVIDIA NIM+2

Model configuration
provider:
  name: nvidia
  api_base: https://integrate.api.nvidia.com/v1

model:
  id: nvidia/nemotron-3.5-super-vl-120b-a12b
  temperature: 1.0
  top_p: 0.95
  max_tokens: 8192
  reasoning: true
  streaming: true

runtime:
  request_timeout: 180
  max_retries: 3
  retry_backoff: exponential


These are initial application defaults, not NVIDIA-mandated settings. We will tune them using actual tool-calling and coding evaluations.
API connection
The initial integration contract:
from openai import AsyncOpenAIclient = AsyncOpenAI(    base_url="https://integrate.api.nvidia.com/v1",    api_key=nvidia_api_key,)response = await client.chat.completions.create(    model="nvidia/nemotron-3.5-super-vl-120b-a12b",    messages=[        {            "role": "user",            "content": "Explain the current project architecture."        }    ],    temperature=1.0,    top_p=0.95,    max_tokens=8192,    extra_body={        "chat_template_kwargs": {            "enable_thinking": True        }    })



The production adapter must additionally support streaming, structured tool calls, timeout handling, cancellation, usage tracking and response normalization.
Important model lifecycle decision
The selected model is listed as an early-access model, and NVIDIA's current model catalogue exposes availability and lifecycle information that can change. We must check its endpoint availability, access terms and deprecation date during setup and before every production release. 

Try NVIDIA NIM APIs+1

Therefore, our architecture must never hardcode the model into the agent engine.

The model registry should support:
Primary:
    Nemotron 3.5 Super VL 120B

Fallback:
    User-configured compatible model

Embeddings:
    Separately configured embedding model

Reranking:
    Separately configured reranker


Important: A chat model is not automatically an embedding model. We should use a dedicated NVIDIA embedding endpoint, such as a compatible Nemotron embedding model, and configure its vector dimensions from the actual model response.

Part III — Application architecture
6. Architectural pattern
We will use a modular monolith with independently supervised background workers.

Why not microservices?

Because NEMO initially runs on one developer machine. Splitting the application into numerous network services introduces complexity without providing a meaningful benefit.

However, we will maintain module boundaries so individual components can become services later.
NEMO application architecture
CLI APPLICATION

Typer · Rich · Textual


LOCAL APPLICATION GATEWAY

Authenticated IPC · Task routing · Session management


Agent Core
LangGraph workflows

Execution Core
Shell and processes

Memory Core
Retrieval and persistence

Project Core
Indexing and code graphs



PERSISTENCE AND INFRASTRUCTURE

PostgreSQL · pgvector · Neo4j · Redis · Filesystem


NVIDIA NIM
Remote inference

Developer tools
IDEs and shells



6.1 Three execution processes
The production installation will contain three main processes.

Process A: CLI
- Receives commands.
- Displays streaming responses.
- Collects approvals.
- Displays task progress.
- Communicates with the daemon.
Process B: NEMO Daemon
- Maintains active tasks.
- Owns terminal sessions.
- Coordinates agent execution.
- Manages local IPC.
- Handles memory access.
- Maintains IDE connections.
Process C: Background Worker
- Indexes projects.
- Generates embeddings.
- Updates knowledge graphs.
- Processes memory consolidation.
- Performs scheduled maintenance.
The worker must be able to restart without losing queued work.
6.2 Local communication
For Windows, use named pipes with a versioned message protocol.

Proposed pipe:
\\.\pipe\NEMO-daemon-v1


Every message should have a standard envelope:
{
  "protocol_version": "1.0",
  "request_id": "uuid",
  "type": "task.create",
  "timestamp": "ISO-8601",
  "payload": {}
}


The daemon must validate the message schema and authenticate the local client.

For the initial implementation, a localhost FastAPI server with a random per-installation bearer token is an acceptable development transport. Named pipes are the production Windows transport target.
Part IV — Repository structure
7. Final monorepo structure
This is the structure I recommend committing to before implementation.

We will use uv for Python dependency and environment management, with a pyproject.toml-based workspace.
NEMO/
│
├── apps/
│   ├── cli/
│   │   ├── commands/
│   │   │   ├── setup.py
│   │   │   ├── config.py
│   │   │   ├── memory.py
│   │   │   ├── project.py
│   │   │   ├── index.py
│   │   │   ├── ide.py
│   │   │   ├── terminal.py
│   │   │   ├── agent.py
│   │   │   └── doctor.py
│   │   ├── interface/
│   │   │   ├── chat.py
│   │   │   ├── approval.py
│   │   │   ├── progress.py
│   │   │   └── renderer.py
│   │   ├── main.py
│   │   └── app.py
│   │
│   ├── daemon/
│   │   ├── ipc/
│   │   ├── lifecycle/
│   │   ├── sessions/
│   │   ├── scheduler/
│   │   └── main.py
│   │
│   └── worker/
│       ├── indexing/
│       ├── embeddings/
│       ├── memory/
│       └── main.py
│
├── src/
│   └── NEMO/
│       │
│       ├── agent/
│       │   ├── graphs/
│       │   ├── nodes/
│       │   ├── state/
│       │   ├── checkpoints/
│       │   ├── planning/
│       │   ├── policies/
│       │   └── orchestration/
│       │
│       ├── ai/
│       │   ├── providers/
│       │   ├── models/
│       │   ├── prompts/
│       │   ├── embeddings/
│       │   ├── reranking/
│       │   └── schemas/
│       │
│       ├── memory/
│       │   ├── personal/
│       │   ├── episodic/
│       │   ├── semantic/
│       │   ├── project/
│       │   ├── retrieval/
│       │   ├── consolidation/
│       │   └── repository/
│       │
│       ├── intelligence/
│       │   ├── scanner/
│       │   ├── parser/
│       │   ├── symbols/
│       │   ├── dependencies/
│       │   ├── graph/
│       │   ├── chunks/
│       │   ├── retrieval/
│       │   └── indexing/
│       │
│       ├── execution/
│       │   ├── shells/
│       │   ├── processes/
│       │   ├── sessions/
│       │   ├── monitoring/
│       │   ├── output/
│       │   ├── jobs/
│       │   └── cancellation/
│       │
│       ├── integrations/
│       │   ├── ide/
│       │   │   ├── base.py
│       │   │   ├── antigravity.py
│       │   │   ├── vscode.py
│       │   │   ├── cursor.py
│       │   │   └── registry.py
│       │   ├── mcp/
│       │   └── git/
│       │
│       ├── security/
│       │   ├── approvals/
│       │   ├── permissions/
│       │   ├── secrets/
│       │   ├── sandbox/
│       │   └── audit/
│       │
│       ├── database/
│       │   ├── models/
│       │   ├── repositories/
│       │   ├── migrations/
│       │   └── connections/
│       │
│       ├── tools/
│       │   ├── registry.py
│       │   ├── filesystem/
│       │   ├── terminal/
│       │   ├── project/
│       │   ├── memory/
│       │   └── ide/
│       │
│       ├── config/
│       ├── observability/
│       ├── events/
│       ├── exceptions/
│       └── common/
│
├── extensions/
│   ├── vscode/
│   └── antigravity/
│
├── infrastructure/
│   ├── docker/
│   │   ├── compose.yaml
│   │   └── postgres/
│   ├── neo4j/
│   ├── redis/
│   └── windows/
│
├── tests/
│   ├── unit/
│   ├── integration/
│   ├── agent/
│   ├── execution/
│   ├── memory/
│   ├── indexing/
│   ├── security/
│   └── acceptance/
│
├── benchmarks/
│   ├── command_execution/
│   ├── retrieval/
│   ├── indexing/
│   └── autonomous_tasks/
│
├── docs/
│   ├── architecture/
│   ├── database/
│   ├── api/
│   ├── commands/
│   ├── security/
│   └── decisions/
│
├── scripts/
│
├── .env.example
├── .gitignore
├── pyproject.toml
├── uv.lock
├── README.md
└── LICENSE


Repository rules
1. apps/ contains executable applications.
2. src/NEMO/ contains reusable business logic.
3. integrations/ contains external application adapters.
4. tools/ contains capabilities exposed to the agent.
5. security/ owns all authorization decisions.
6. database/ owns persistence contracts.
7. No module should directly modify another module's internal database tables.
8. All external integrations must have typed interfaces.
9. All agent tools must have explicit input and output schemas.
10. The daemon must not import CLI presentation code.
This prevents the codebase from turning into one large collection of interdependent Python files.

Part V — Database and memory design
8. Database architecture
We will use four storage systems, each with a distinct responsibility.










PostgreSQL + pgvector
Primary source of truthUsers, projects, memory, conversations, execution history, embeddings and agent checkpoints.













Neo4j
Relationship intelligenceCode dependencies, architectural relationships, project entities and knowledge graphs.













Redis
Transient coordinationCaches, task queues, locks, event coordination and short-lived state.













Local filesystem
Original artifactsProject source, raw logs, archives, backups and generated indexing artifacts.



PostgreSQL remains authoritative. Neo4j is a derived graph projection that can be rebuilt from authoritative project and memory data.

This is important: we must not create a system where a Neo4j failure causes all project information to become inaccessible.
Database deployment policy
- PostgreSQL and pgvector: mandatory for production.
- Neo4j: enabled for full graph intelligence.
- Redis: enabled for the full daemon/worker configuration.
- Docker Compose: local infrastructure deployment.
- Database migrations: Alembic.
- Backup: scheduled PostgreSQL backups and graph reconstruction support.
For the first development iteration, we can run all three databases through Docker without installing them globally into Windows.
9. PostgreSQL schema
We should use UUID primary keys, timestamps, JSONB for flexible metadata and foreign keys wherever relationships are relational.

The following is the logical production schema. Actual migrations will be created incrementally.
9.1 User and environment
Table	Important columns	Purpose
user_profiles	id, name, preferences, timezone	User identity
environment_profiles	id, user_id, shell, default_ide, os	Development environment
api_providers	id, provider, model, endpoint, config	Model configuration without secret values
tool_definitions	id, name, version, schema, enabled	Registered tools
permission_policies	id, scope, policy, rules	Authorization configuration
secret_references	id, provider, credential_target	References to OS-protected credentials

API secrets must never be stored as plaintext database fields.
9.2 Projects
Table	Important columns	Purpose
projects	id, name, root_path, status	Registered projects
project_memberships	project_id, user_id, role	Ownership and access
project_settings	project_id, key, value	Project-specific settings
project_snapshots	id, project_id, commit_hash, created_at	Project state
project_files	id, project_id, path, hash, language	Indexed file metadata
project_symbols	id, file_id, name, kind, start_line, end_line	Functions, classes and symbols
project_dependencies	id, project_id, source, target, kind	Dependency information
index_jobs	id, project_id, status, progress	Indexing tasks

project_files should use a unique constraint on (project_id, path).
9.3 Memory
Table	Important columns	Purpose
memory_items	id, scope, content, importance, confidence	Canonical memory records
memory_embeddings	memory_id, model_id, vector	Vector representation
memory_relations	source_id, target_id, relation	Memory relationships
memory_versions	memory_id, version, content, changed_at	Historical changes
memory_sources	memory_id, source_type, source_id	Provenance
memory_events	id, event_type, payload, occurred_at	Memory event history
memory_conflicts	id, old_memory, new_memory, status	Contradiction management

9.4 Conversations and tasks
Table	Important columns	Purpose
conversations	id, project_id, title, started_at	Conversation sessions
conversation_messages	id, conversation_id, role, content	Conversation history
agent_tasks	id, thread_id, objective, status	Agent execution
agent_checkpoints	id, task_id, checkpoint_ref	Resumable state
task_steps	id, task_id, step, status, result	Execution plan
approvals	id, task_id, action, status, expires_at	User authorization

9.5 Terminal execution
Table	Important columns	Purpose
terminal_sessions	id, shell, cwd, status, pid	Persistent sessions
command_executions	id, session_id, command, exit_code	Command history
execution_events	id, execution_id, event_type, timestamp	Lifecycle events
execution_artifacts	id, execution_id, path, type	Logs and generated files
audit_events	id, actor, action, target, result	Security audit trail

Sensitive command arguments, tokens and environment variables must be redacted before persistence.
9.6 Code chunks and vector retrieval
Add these tables:
code_chunks
    id
    project_id
    file_id
    content
    content_hash
    language
    symbol_id
    start_line
    end_line
    embedding_model
    embedding
    indexed_at


The vector column will use pgvector with an explicit dimension matching the configured embedding model.

We should never assume the same vector dimensions across embedding models.

Use a model-specific index or collection when changing embedding models. Store the model identifier and embedding version with each record.
10. Logical memory schema
I recommend the following memory representation:
{
  "id": "uuid",
  "scope": "project",
  "scope_id": "project-uuid",
  "type": "technical_decision",
  "subject": "database",
  "predicate": "uses",
  "object": "PostgreSQL",
  "content": "The project uses PostgreSQL as its primary database.",
  "importance": 0.95,
  "confidence": 1.0,
  "valid_from": "2026-11-10T10:00:00Z",
  "valid_until": null,
  "status": "active",
  "source": {
    "type": "conversation",
    "id": "conversation-uuid"
  },
  "metadata": {
    "project": "COSEM",
    "category": "architecture"
  }
}


The subject, predicate and object fields make it easier to construct graph relationships and retrieve factual information.
Memory types
Type	Example
Profile	Preferred IDE is Antigravity
Preference	Prefers PowerShell
Technical decision	Uses PostgreSQL
Project fact	Backend runs on FastAPI
Episodic	Fixed a dependency error
Procedural	Deployment procedure
Goal	Finish authentication module
Task state	Integration tests pending
Environment	Python installed at a known location

Memory retrieval algorithm
When a user asks a question:
1. Identify the active project and memory scope.
2. Classify the query into memory categories.
3. Perform metadata and exact-text retrieval.
4. Perform vector similarity search.
5. Retrieve connected graph relationships.
6. Apply temporal validity.
7. Rank results by relevance, confidence and freshness.
8. Return evidence and provenance to the agent.
A starting ranking function could be:
\[
S = 0.40V + 0.25K + 0.15R + 0.10F + 0.10I
\]

Where:
- \(V\): vector similarity.
- \(K\): keyword relevance.
- \(R\): graph relationship relevance.
- \(F\): freshness.
- \(I\): importance.
These weights are initial tuning parameters, not universal optimal values. We should evaluate them against a retrieval benchmark.
Memory lifecycle
New Information
      |
      v
Extraction
      |
      v
Validation
      |
      v
Duplicate Detection
      |
      v
Conflict Resolution
      |
      v
PostgreSQL Persistence
      |
      +----> Vector Embedding
      |
      +----> Neo4j Relationship
      |
      v
Available for Retrieval


Critical design decision: Conversation history is not the same as memory.

We retain conversations as historical records. We separately extract and update useful memories. This prevents the database from becoming a giant collection of repeated conversational text.

11. Neo4j knowledge graph schema
We will create a graph with a small number of reusable node types.
Node types
(:User)
(:Project)
(:Directory)
(:File)
(:Symbol)
(:Package)
(:Service)
(:Database)
(:Memory)
(:Decision)
(:Task)
(:Technology)


Relationship types
(:User)-[:OWNS]->(:Project)

(:Project)-[:CONTAINS]->(:Directory)

(:Directory)-[:CONTAINS]->(:File)

(:File)-[:DECLARES]->(:Symbol)

(:Symbol)-[:CALLS]->(:Symbol)

(:File)-[:IMPORTS]->(:File)

(:Project)-[:DEPENDS_ON]->(:Package)

(:Project)-[:USES]->(:Technology)

(:Service)-[:CONNECTS_TO]->(:Database)

(:Project)-[:HAS_MEMORY]->(:Memory)

(:Decision)-[:SUPERSEDES]->(:Decision)

(:Task)-[:MODIFIES]->(:File)


Example
Example project knowledge graph
COSEM Project

CONTAINS

Auth Module
Directoryauth.controller.py


Database
ServicePostgreSQL



RELATIONSHIPS AND DEPENDENCIES

Unified project architecture
Files · Symbols · Calls · Imports · Packages · Decisions

Every graph node should have a stable ID. For code symbols, derive the ID from project ID, file path, qualified symbol name and symbol type.

We should store file hashes and source commit information so graph updates can be traced to the exact version of the code.

Neo4j should not receive every arbitrary code chunk as a node. That would create a huge and noisy graph. The graph should contain structural entities and meaningful relationships.

Part VI — Agent architecture
12. LangGraph architecture
This is the core of NEMO.

I recommend one primary supervisor graph with specialized subgraphs, not a collection of independent agents debating one another.

The supervisor determines which capabilities are needed and delegates to deterministic tools or specialized workflows.
Agent components
Component	Responsibility
Intent Router	Understand user intent
Context Builder	Retrieve relevant context
Planner	Generate task plans
Policy Evaluator	Evaluate action permissions
Tool Executor	Invoke registered tools
Observer	Collect execution results
Error Diagnoser	Analyze failures
Repair Planner	Generate recovery actions
Verifier	Verify final outcomes
Memory Writer	Store useful discoveries

Main agent graph
#chatgpt-mermaid-_r_uk_{font-family:-apple-system-body,ui-sans-serif,-apple-system,system-ui,"Segoe UI",Helvetica,"Apple Color Emoji",Arial,sans-serif,"Segoe UI Emoji","Segoe UI Symbol";font-size:16px;fill:rgb(237, 237, 237);}@keyframes edge-animation-frame{from{stroke-dashoffset:0;}}@keyframes dash{to{stroke-dashoffset:0;}}#chatgpt-mermaid-_r_uk_ .edge-animation-slow{stroke-dasharray:9,5!important;stroke-dashoffset:900;animation:dash 50s linear infinite;stroke-linecap:round;}#chatgpt-mermaid-_r_uk_ .edge-animation-fast{stroke-dasharray:9,5!important;stroke-dashoffset:900;animation:dash 20s linear infinite;stroke-linecap:round;}#chatgpt-mermaid-_r_uk_ .error-icon{fill:rgb(48, 48, 48);}#chatgpt-mermaid-_r_uk_ .error-text{fill:rgb(237, 237, 237);stroke:rgb(237, 237, 237);}#chatgpt-mermaid-_r_uk_ .edge-thickness-normal{stroke-width:1px;}#chatgpt-mermaid-_r_uk_ .edge-thickness-thick{stroke-width:3.5px;}#chatgpt-mermaid-_r_uk_ .edge-pattern-solid{stroke-dasharray:0;}#chatgpt-mermaid-_r_uk_ .edge-thickness-invisible{stroke-width:0;fill:none;}#chatgpt-mermaid-_r_uk_ .edge-pattern-dashed{stroke-dasharray:3;}#chatgpt-mermaid-_r_uk_ .edge-pattern-dotted{stroke-dasharray:2;}#chatgpt-mermaid-_r_uk_ .marker{fill:rgb(175, 175, 175);stroke:rgb(175, 175, 175);}#chatgpt-mermaid-_r_uk_ .marker.cross{stroke:rgb(175, 175, 175);}#chatgpt-mermaid-_r_uk_ svg{font-family:-apple-system-body,ui-sans-serif,-apple-system,system-ui,"Segoe UI",Helvetica,"Apple Color Emoji",Arial,sans-serif,"Segoe UI Emoji","Segoe UI Symbol";font-size:16px;}#chatgpt-mermaid-_r_uk_ p{margin:0;}#chatgpt-mermaid-_r_uk_ .label{font-family:-apple-system-body,ui-sans-serif,-apple-system,system-ui,"Segoe UI",Helvetica,"Apple Color Emoji",Arial,sans-serif,"Segoe UI Emoji","Segoe UI Symbol";color:rgb(237, 237, 237);}#chatgpt-mermaid-_r_uk_ .cluster-label text{fill:rgb(237, 237, 237);}#chatgpt-mermaid-_r_uk_ .cluster-label span{color:rgb(237, 237, 237);}#chatgpt-mermaid-_r_uk_ .cluster-label span p{background-color:transparent;}#chatgpt-mermaid-_r_uk_ .label text,#chatgpt-mermaid-_r_uk_ span{fill:rgb(237, 237, 237);color:rgb(237, 237, 237);}#chatgpt-mermaid-_r_uk_ .node rect,#chatgpt-mermaid-_r_uk_ .node circle,#chatgpt-mermaid-_r_uk_ .node ellipse,#chatgpt-mermaid-_r_uk_ .node polygon,#chatgpt-mermaid-_r_uk_ .node path{fill:rgb(9, 23, 44);stroke:rgb(31, 78, 148);stroke-width:1px;}#chatgpt-mermaid-_r_uk_ .rough-node .label text,#chatgpt-mermaid-_r_uk_ .node .label text,#chatgpt-mermaid-_r_uk_ .image-shape .label,#chatgpt-mermaid-_r_uk_ .icon-shape .label{text-anchor:middle;}#chatgpt-mermaid-_r_uk_ .node .katex path{fill:#000;stroke:#000;stroke-width:1px;}#chatgpt-mermaid-_r_uk_ .rough-node .label,#chatgpt-mermaid-_r_uk_ .node .label,#chatgpt-mermaid-_r_uk_ .image-shape .label,#chatgpt-mermaid-_r_uk_ .icon-shape .label{text-align:center;}#chatgpt-mermaid-_r_uk_ .node.clickable{cursor:pointer;}#chatgpt-mermaid-_r_uk_ .root .anchor path{fill:rgb(175, 175, 175)!important;stroke-width:0;stroke:rgb(175, 175, 175);}#chatgpt-mermaid-_r_uk_ .arrowheadPath{fill:rgb(175, 175, 175);}#chatgpt-mermaid-_r_uk_ .edgePath .path{stroke:rgb(175, 175, 175);stroke-width:1px;}#chatgpt-mermaid-_r_uk_ .flowchart-link{stroke:rgb(175, 175, 175);fill:none;}#chatgpt-mermaid-_r_uk_ .edgeLabel{background-color:rgb(0, 0, 0);text-align:center;}#chatgpt-mermaid-_r_uk_ .edgeLabel p{background-color:rgb(0, 0, 0);}#chatgpt-mermaid-_r_uk_ .edgeLabel rect{opacity:0.5;background-color:rgb(0, 0, 0);fill:rgb(0, 0, 0);}#chatgpt-mermaid-_r_uk_ .labelBkg{background-color:rgba(0, 0, 0, 0.5);}#chatgpt-mermaid-_r_uk_ .cluster rect{fill:rgb(48, 48, 48);stroke:rgba(255, 255, 255, 0.15);stroke-width:1px;}#chatgpt-mermaid-_r_uk_ .cluster text{fill:rgb(237, 237, 237);}#chatgpt-mermaid-_r_uk_ .cluster span{color:rgb(237, 237, 237);}#chatgpt-mermaid-_r_uk_ div.mermaidTooltip{position:absolute;text-align:center;max-width:200px;padding:2px;font-family:-apple-system-body,ui-sans-serif,-apple-system,system-ui,"Segoe UI",Helvetica,"Apple Color Emoji",Arial,sans-serif,"Segoe UI Emoji","Segoe UI Symbol";font-size:12px;background:rgb(48, 48, 48);border:1px solid rgba(255, 255, 255, 0.15);border-radius:2px;pointer-events:none;z-index:100;}#chatgpt-mermaid-_r_uk_ .flowchartTitleText{text-anchor:middle;font-size:18px;fill:rgb(237, 237, 237);}#chatgpt-mermaid-_r_uk_ rect.text{fill:none;stroke-width:0;}#chatgpt-mermaid-_r_uk_ .icon-shape,#chatgpt-mermaid-_r_uk_ .image-shape{background-color:rgb(0, 0, 0);text-align:center;}#chatgpt-mermaid-_r_uk_ .icon-shape p,#chatgpt-mermaid-_r_uk_ .image-shape p{background-color:rgb(0, 0, 0);padding:2px;}#chatgpt-mermaid-_r_uk_ .icon-shape .label rect,#chatgpt-mermaid-_r_uk_ .image-shape .label rect{opacity:0.5;background-color:rgb(0, 0, 0);fill:rgb(0, 0, 0);}#chatgpt-mermaid-_r_uk_ .label-icon{display:inline-block;height:1em;overflow:visible;vertical-align:-0.125em;}#chatgpt-mermaid-_r_uk_ .node .label-icon path{fill:currentColor;stroke:revert;stroke-width:revert;}#chatgpt-mermaid-_r_uk_ .node .neo-node{stroke:rgb(31, 78, 148);}#chatgpt-mermaid-_r_uk_ [data-look="neo"].node rect,#chatgpt-mermaid-_r_uk_ [data-look="neo"].cluster rect,#chatgpt-mermaid-_r_uk_ [data-look="neo"].node polygon{stroke:url(#chatgpt-mermaid-_r_uk_-gradient);filter:drop-shadow( 1px 2px 2px rgba(185,185,185,1));}#chatgpt-mermaid-_r_uk_ [data-look="neo"].swimlane.cluster rect{filter:none;}#chatgpt-mermaid-_r_uk_ [data-look="neo"].node path{stroke:url(#chatgpt-mermaid-_r_uk_-gradient);stroke-width:1px;}#chatgpt-mermaid-_r_uk_ [data-look="neo"].node .outer-path{filter:drop-shadow( 1px 2px 2px rgba(185,185,185,1));}#chatgpt-mermaid-_r_uk_ [data-look="neo"].node .neo-line path{stroke:rgb(31, 78, 148);filter:none;}#chatgpt-mermaid-_r_uk_ [data-look="neo"].node circle{stroke:url(#chatgpt-mermaid-_r_uk_-gradient);filter:drop-shadow( 1px 2px 2px rgba(185,185,185,1));}#chatgpt-mermaid-_r_uk_ [data-look="neo"].node circle .state-start{fill:#000000;}#chatgpt-mermaid-_r_uk_ [data-look="neo"].icon-shape .icon{fill:url(#chatgpt-mermaid-_r_uk_-gradient);filter:drop-shadow( 1px 2px 2px rgba(185,185,185,1));}#chatgpt-mermaid-_r_uk_ [data-look="neo"].icon-shape .icon-neo path{stroke:url(#chatgpt-mermaid-_r_uk_-gradient);filter:drop-shadow( 1px 2px 2px rgba(185,185,185,1));}#chatgpt-mermaid-_r_uk_ .node text{font-size:14px;font-weight:600;letter-spacing:normal;fill:rgb(153, 206, 255);}#chatgpt-mermaid-_r_uk_ .edgeLabels text{font-size:13px;font-weight:600;letter-spacing:-0.08px;fill:rgb(153, 206, 255);}#chatgpt-mermaid-_r_uk_ .node tspan[font-weight="normal"],#chatgpt-mermaid-_r_uk_ .edgeLabels tspan[font-weight="normal"]{font-weight:600;}#chatgpt-mermaid-_r_uk_ .edgeLabel .label rect{opacity:1;rx:13px;ry:13px;fill:rgb(0, 14, 26);stroke:rgb(26, 62, 95);stroke-width:1px;}#chatgpt-mermaid-_r_uk_ .node rect,#chatgpt-mermaid-_r_uk_ .node circle,#chatgpt-mermaid-_r_uk_ .node ellipse,#chatgpt-mermaid-_r_uk_ .node polygon,#chatgpt-mermaid-_r_uk_ .node path{fill:rgb(0, 40, 77);stroke:rgba(255, 255, 255, 0.1);stroke-width:1px;}#chatgpt-mermaid-_r_uk_ .node rect{rx:16px;ry:16px;}#chatgpt-mermaid-_r_uk_ .mermaid-decision .label-container{fill:rgb(0, 14, 26);stroke:rgb(26, 62, 95);stroke-dasharray:2,2;}#chatgpt-mermaid-_r_uk_ .edgePaths .flowchart-link{stroke:rgb(175, 175, 175);stroke-width:1px;stroke-linecap:round;stroke-linejoin:round;}#chatgpt-mermaid-_r_uk_ .marker{fill:rgb(175, 175, 175);stroke:rgb(175, 175, 175);}#chatgpt-mermaid-_r_uk_ :root{--mermaid-font-family:-apple-system-body,ui-sans-serif,-apple-system,system-ui,"Segoe UI",Helvetica,"Apple Color Emoji",Arial,sans-serif,"Segoe UI Emoji","Segoe UI Symbol";}User InputIntent RouterContext RetrievalTask PlannerPlan ValidationAction Requires Approval?Request User ApprovalTool ExecutionStop / ReplanObserve Actual ResultSuccessful?Verify OutcomeError DiagnosisRepair PlanUpdate MemoryRespond to UserYesApprovedRejectedNoYesNo





Why this graph?
The planner should never directly execute commands.

It creates a plan containing proposed actions.

The policy evaluator checks the plan.

The executor performs authorized operations.

The observer obtains actual results.

The verifier checks whether the user's objective was achieved.

This separation is fundamental to reliable agent design.
13. Agent state definition
LangGraph requires a well-defined state that can be serialized and restored.

Our primary state:
from typing import TypedDict, Literal, Anyclass NEMOState(TypedDict, total=False):    task_id: str    thread_id: str    user_input: str    intent: str    active_project_id: str    working_directory: str    conversation_context: list[dict]    retrieved_memories: list[dict]    project_context: dict    execution_plan: list[dict]    current_step: int    pending_approval: dict | None    tool_calls: list[dict]    tool_results: list[dict]    execution_status: Literal[        "planning",        "waiting_approval",        "executing",        "observing",        "failed",        "completed",        "cancelled"    ]



We should store references to large files and outputs, not place complete terminal logs or entire source files inside the graph state.

The checkpoint should be compact and serializable.
Checkpointing strategy
Use LangGraph's PostgreSQL checkpointer in production.

This gives us:
- Resume after interruption.
- Recover paused tasks.
- Human approval checkpoints.
- Task inspection.
- Execution history.
- Debugging and replay.
The checkpoint is not a substitute for our application database. Task records, approvals and execution artifacts remain authoritative application records.
14. Tool registry specification
Every tool available to the agent must implement a standard interface.
from typing import Protocol, Anyfrom pydantic import BaseModelclass ToolResult(BaseModel):    success: bool    data: dict[str, Any] = {}    error: str | None = None    artifacts: list[str] = []class NEMOTool(Protocol):    name: str    description: str    input_schema: type[BaseModel]    async def execute(        self,        arguments: BaseModel,        context: dict    ) -> ToolResult:        ...



Each tool must also define:
- Permission category.
- Risk classification.
- Timeout policy.
- Retry policy.
- Idempotency characteristics.
- Audit requirements.
- Expected side effects.
Initial tool catalogue
Category	Tools
Filesystem	list, read, search, write, move
Project	inspect, register, switch, index
Terminal	execute, stream, wait, cancel
Package management	detect, inspect, install, validate
IDE	detect, launch, open workspace, open file
Git	status, diff, log, branch
Memory	search, create, update, supersede
Database	inspect schema, test connection
Development	build, test, lint, diagnose
System	environment detection, process inspection

The model should only see tools relevant to the current task.

For example, a request to retrieve a project memory should not expose filesystem deletion or process termination tools to the model.

Part VII — Terminal and execution engine
15. Execution architecture
The terminal engine is a first-class component, not an ordinary AI tool wrapper.

It needs two execution modes.
Mode A: One-shot execution
For commands such as:
git status
python --version
npm install
pytest


Use asyncio.create_subprocess_exec.

The process lifecycle:
CREATED
   |
   v
STARTED
   |
   v
RUNNING
   |
   v
COLLECTING OUTPUT
   |
   v
EXITED
   |
   v
EXIT CODE RECORDED


The system must collect stdout and stderr without deadlocks, retain the exit code, support timeout and cancellation, and distinguish a process that has exited from one that is merely quiet.
Mode B: Persistent interactive execution
For:
python
psql
npm run dev
ssh user@server


Use a persistent PTY session.

The session manager should maintain:
class Session:    session_id: str    shell: str    cwd: str    process_id: int | None    state: str    created_at: str    last_activity: str



It should support:
- Starting sessions.
- Sending input.
- Streaming output.
- Resizing the terminal.
- Tracking process state.
- Sending interrupt signals.
- Terminating sessions.
- Reconnecting to surviving processes.
- Capturing logs.
For long-running processes, the daemon should own the process rather than the CLI.
15.1 Shell detection
At setup, detect:
Shell	Detection
PowerShell 7	pwsh.exe
Windows PowerShell	powershell.exe
CMD	cmd.exe
Git Bash	bash.exe
WSL	wsl.exe

The default shell should be PowerShell.

NEMO must not translate every shell command into PowerShell syntax. The user's selected shell determines the execution environment.
15.2 Command execution contract
A command request should look like:
{
  "shell": "powershell",
  "working_directory": "D:\\Projects\\COSEM",
  "command": "npm install",
  "execution_mode": "one_shot",
  "timeout_seconds": 600,
  "capture_output": true,
  "approval_id": null
}


And the result:
{
  "execution_id": "uuid",
  "status": "completed",
  "exit_code": 0,
  "stdout_ref": "artifact-uuid",
  "stderr_ref": null,
  "duration_ms": 42800
}


15.3 Waiting and completion detection
There is a subtle problem with interactive terminal execution.

A running process may produce no output for several minutes. That does not mean it has completed.

Therefore:
- Process termination is the primary completion signal.
- Exit code is the primary success signal.
- PTY output is an observation, not a completion signal.
- Interactive sessions require explicit session state.
- Shell prompt detection can be supplementary but must not be authoritative.
15.4 Package management intelligence
The dependency manager should detect project types from manifests and lockfiles.
Ecosystem	Detection	Installation
Node.js	package.json	npm, pnpm, yarn, bun
Python	pyproject.toml, requirements.txt	uv, pip
Rust	Cargo.toml	cargo
Java	pom.xml, build.gradle	Maven, Gradle
.NET	*.csproj, *.sln	dotnet
PHP	composer.json	Composer
Ruby	Gemfile	Bundler
Go	go.mod	Go modules

Important rules:
1. Respect the existing lockfile.
2. Detect the project's declared package manager.
3. Do not blindly install the latest versions.
4. Do not modify lockfiles without an authorized installation plan.
5. Never invent dependencies simply because an LLM thinks they might be useful.
6. Run the project's validation command after installation.
7. Report conflicts instead of repeatedly changing dependency versions.

16. Security and approval architecture
This is a non-negotiable part of the production build.

I recommend four risk levels.
Level	Examples	Behaviour
L0	Read files, inspect Git, list directories	Automatic
L1	Build, tests, package installation in trusted project	Automatic within configured policy
L2	Modify source, environment or project configuration	Approval according to policy
L3	Delete data, administrator operations, destructive Git or system operations	Explicit approval, strong warnings or block

The user's selected approval mode means the default policy should automatically handle safe routine development work but request approval before risky or consequential modifications.
Approval workflow
#chatgpt-mermaid-_r_105_{font-family:-apple-system-body,ui-sans-serif,-apple-system,system-ui,"Segoe UI",Helvetica,"Apple Color Emoji",Arial,sans-serif,"Segoe UI Emoji","Segoe UI Symbol";font-size:16px;fill:rgb(237, 237, 237);}@keyframes edge-animation-frame{from{stroke-dashoffset:0;}}@keyframes dash{to{stroke-dashoffset:0;}}#chatgpt-mermaid-_r_105_ .edge-animation-slow{stroke-dasharray:9,5!important;stroke-dashoffset:900;animation:dash 50s linear infinite;stroke-linecap:round;}#chatgpt-mermaid-_r_105_ .edge-animation-fast{stroke-dasharray:9,5!important;stroke-dashoffset:900;animation:dash 20s linear infinite;stroke-linecap:round;}#chatgpt-mermaid-_r_105_ .error-icon{fill:rgb(48, 48, 48);}#chatgpt-mermaid-_r_105_ .error-text{fill:rgb(237, 237, 237);stroke:rgb(237, 237, 237);}#chatgpt-mermaid-_r_105_ .edge-thickness-normal{stroke-width:1px;}#chatgpt-mermaid-_r_105_ .edge-thickness-thick{stroke-width:3.5px;}#chatgpt-mermaid-_r_105_ .edge-pattern-solid{stroke-dasharray:0;}#chatgpt-mermaid-_r_105_ .edge-thickness-invisible{stroke-width:0;fill:none;}#chatgpt-mermaid-_r_105_ .edge-pattern-dashed{stroke-dasharray:3;}#chatgpt-mermaid-_r_105_ .edge-pattern-dotted{stroke-dasharray:2;}#chatgpt-mermaid-_r_105_ .marker{fill:rgb(175, 175, 175);stroke:rgb(175, 175, 175);}#chatgpt-mermaid-_r_105_ .marker.cross{stroke:rgb(175, 175, 175);}#chatgpt-mermaid-_r_105_ svg{font-family:-apple-system-body,ui-sans-serif,-apple-system,system-ui,"Segoe UI",Helvetica,"Apple Color Emoji",Arial,sans-serif,"Segoe UI Emoji","Segoe UI Symbol";font-size:16px;}#chatgpt-mermaid-_r_105_ p{margin:0;}#chatgpt-mermaid-_r_105_ .label{font-family:-apple-system-body,ui-sans-serif,-apple-system,system-ui,"Segoe UI",Helvetica,"Apple Color Emoji",Arial,sans-serif,"Segoe UI Emoji","Segoe UI Symbol";color:rgb(237, 237, 237);}#chatgpt-mermaid-_r_105_ .cluster-label text{fill:rgb(237, 237, 237);}#chatgpt-mermaid-_r_105_ .cluster-label span{color:rgb(237, 237, 237);}#chatgpt-mermaid-_r_105_ .cluster-label span p{background-color:transparent;}#chatgpt-mermaid-_r_105_ .label text,#chatgpt-mermaid-_r_105_ span{fill:rgb(237, 237, 237);color:rgb(237, 237, 237);}#chatgpt-mermaid-_r_105_ .node rect,#chatgpt-mermaid-_r_105_ .node circle,#chatgpt-mermaid-_r_105_ .node ellipse,#chatgpt-mermaid-_r_105_ .node polygon,#chatgpt-mermaid-_r_105_ .node path{fill:rgb(9, 23, 44);stroke:rgb(31, 78, 148);stroke-width:1px;}#chatgpt-mermaid-_r_105_ .rough-node .label text,#chatgpt-mermaid-_r_105_ .node .label text,#chatgpt-mermaid-_r_105_ .image-shape .label,#chatgpt-mermaid-_r_105_ .icon-shape .label{text-anchor:middle;}#chatgpt-mermaid-_r_105_ .node .katex path{fill:#000;stroke:#000;stroke-width:1px;}#chatgpt-mermaid-_r_105_ .rough-node .label,#chatgpt-mermaid-_r_105_ .node .label,#chatgpt-mermaid-_r_105_ .image-shape .label,#chatgpt-mermaid-_r_105_ .icon-shape .label{text-align:center;}#chatgpt-mermaid-_r_105_ .node.clickable{cursor:pointer;}#chatgpt-mermaid-_r_105_ .root .anchor path{fill:rgb(175, 175, 175)!important;stroke-width:0;stroke:rgb(175, 175, 175);}#chatgpt-mermaid-_r_105_ .arrowheadPath{fill:rgb(175, 175, 175);}#chatgpt-mermaid-_r_105_ .edgePath .path{stroke:rgb(175, 175, 175);stroke-width:1px;}#chatgpt-mermaid-_r_105_ .flowchart-link{stroke:rgb(175, 175, 175);fill:none;}#chatgpt-mermaid-_r_105_ .edgeLabel{background-color:rgb(0, 0, 0);text-align:center;}#chatgpt-mermaid-_r_105_ .edgeLabel p{background-color:rgb(0, 0, 0);}#chatgpt-mermaid-_r_105_ .edgeLabel rect{opacity:0.5;background-color:rgb(0, 0, 0);fill:rgb(0, 0, 0);}#chatgpt-mermaid-_r_105_ .labelBkg{background-color:rgba(0, 0, 0, 0.5);}#chatgpt-mermaid-_r_105_ .cluster rect{fill:rgb(48, 48, 48);stroke:rgba(255, 255, 255, 0.15);stroke-width:1px;}#chatgpt-mermaid-_r_105_ .cluster text{fill:rgb(237, 237, 237);}#chatgpt-mermaid-_r_105_ .cluster span{color:rgb(237, 237, 237);}#chatgpt-mermaid-_r_105_ div.mermaidTooltip{position:absolute;text-align:center;max-width:200px;padding:2px;font-family:-apple-system-body,ui-sans-serif,-apple-system,system-ui,"Segoe UI",Helvetica,"Apple Color Emoji",Arial,sans-serif,"Segoe UI Emoji","Segoe UI Symbol";font-size:12px;background:rgb(48, 48, 48);border:1px solid rgba(255, 255, 255, 0.15);border-radius:2px;pointer-events:none;z-index:100;}#chatgpt-mermaid-_r_105_ .flowchartTitleText{text-anchor:middle;font-size:18px;fill:rgb(237, 237, 237);}#chatgpt-mermaid-_r_105_ rect.text{fill:none;stroke-width:0;}#chatgpt-mermaid-_r_105_ .icon-shape,#chatgpt-mermaid-_r_105_ .image-shape{background-color:rgb(0, 0, 0);text-align:center;}#chatgpt-mermaid-_r_105_ .icon-shape p,#chatgpt-mermaid-_r_105_ .image-shape p{background-color:rgb(0, 0, 0);padding:2px;}#chatgpt-mermaid-_r_105_ .icon-shape .label rect,#chatgpt-mermaid-_r_105_ .image-shape .label rect{opacity:0.5;background-color:rgb(0, 0, 0);fill:rgb(0, 0, 0);}#chatgpt-mermaid-_r_105_ .label-icon{display:inline-block;height:1em;overflow:visible;vertical-align:-0.125em;}#chatgpt-mermaid-_r_105_ .node .label-icon path{fill:currentColor;stroke:revert;stroke-width:revert;}#chatgpt-mermaid-_r_105_ .node .neo-node{stroke:rgb(31, 78, 148);}#chatgpt-mermaid-_r_105_ [data-look="neo"].node rect,#chatgpt-mermaid-_r_105_ [data-look="neo"].cluster rect,#chatgpt-mermaid-_r_105_ [data-look="neo"].node polygon{stroke:url(#chatgpt-mermaid-_r_105_-gradient);filter:drop-shadow( 1px 2px 2px rgba(185,185,185,1));}#chatgpt-mermaid-_r_105_ [data-look="neo"].swimlane.cluster rect{filter:none;}#chatgpt-mermaid-_r_105_ [data-look="neo"].node path{stroke:url(#chatgpt-mermaid-_r_105_-gradient);stroke-width:1px;}#chatgpt-mermaid-_r_105_ [data-look="neo"].node .outer-path{filter:drop-shadow( 1px 2px 2px rgba(185,185,185,1));}#chatgpt-mermaid-_r_105_ [data-look="neo"].node .neo-line path{stroke:rgb(31, 78, 148);filter:none;}#chatgpt-mermaid-_r_105_ [data-look="neo"].node circle{stroke:url(#chatgpt-mermaid-_r_105_-gradient);filter:drop-shadow( 1px 2px 2px rgba(185,185,185,1));}#chatgpt-mermaid-_r_105_ [data-look="neo"].node circle .state-start{fill:#000000;}#chatgpt-mermaid-_r_105_ [data-look="neo"].icon-shape .icon{fill:url(#chatgpt-mermaid-_r_105_-gradient);filter:drop-shadow( 1px 2px 2px rgba(185,185,185,1));}#chatgpt-mermaid-_r_105_ [data-look="neo"].icon-shape .icon-neo path{stroke:url(#chatgpt-mermaid-_r_105_-gradient);filter:drop-shadow( 1px 2px 2px rgba(185,185,185,1));}#chatgpt-mermaid-_r_105_ .node text{font-size:14px;font-weight:600;letter-spacing:normal;fill:rgb(153, 206, 255);}#chatgpt-mermaid-_r_105_ .edgeLabels text{font-size:13px;font-weight:600;letter-spacing:-0.08px;fill:rgb(153, 206, 255);}#chatgpt-mermaid-_r_105_ .node tspan[font-weight="normal"],#chatgpt-mermaid-_r_105_ .edgeLabels tspan[font-weight="normal"]{font-weight:600;}#chatgpt-mermaid-_r_105_ .edgeLabel .label rect{opacity:1;rx:13px;ry:13px;fill:rgb(0, 14, 26);stroke:rgb(26, 62, 95);stroke-width:1px;}#chatgpt-mermaid-_r_105_ .node rect,#chatgpt-mermaid-_r_105_ .node circle,#chatgpt-mermaid-_r_105_ .node ellipse,#chatgpt-mermaid-_r_105_ .node polygon,#chatgpt-mermaid-_r_105_ .node path{fill:rgb(0, 40, 77);stroke:rgba(255, 255, 255, 0.1);stroke-width:1px;}#chatgpt-mermaid-_r_105_ .node rect{rx:16px;ry:16px;}#chatgpt-mermaid-_r_105_ .mermaid-decision .label-container{fill:rgb(0, 14, 26);stroke:rgb(26, 62, 95);stroke-dasharray:2,2;}#chatgpt-mermaid-_r_105_ .edgePaths .flowchart-link{stroke:rgb(175, 175, 175);stroke-width:1px;stroke-linecap:round;stroke-linejoin:round;}#chatgpt-mermaid-_r_105_ .marker{fill:rgb(175, 175, 175);stroke:rgb(175, 175, 175);}#chatgpt-mermaid-_r_105_ :root{--mermaid-font-family:-apple-system-body,ui-sans-serif,-apple-system,system-ui,"Segoe UI",Helvetica,"Apple Color Emoji",Arial,sans-serif,"Segoe UI Emoji","Segoe UI Symbol";}Agent proposes actionPolicy engineRisk assessmentExecute within policyRequest approvalExplicit confirmationRejectUser decisionExecuteCancelVerifyLowMediumHighBlockedApproveReject





Security controls
- Never execute raw model-generated shell strings without validation.
- Never concatenate untrusted user input into shell commands.
- Use explicit executable paths and argument lists wherever possible.
- Treat shell scripts and pipelines as executable code, not harmless strings.
- Prevent path traversal outside permitted workspace boundaries.
- Prevent unauthorized symlink/junction traversal.
- Protect secrets and redact them from terminal logs.
- Use an execution allowlist and denylist as policy inputs, not as the only security mechanism.
- Enforce process-tree termination through Windows Job Objects.
- Use timeouts, output limits and disk quotas.
- Require confirmation for elevation and destructive actions.
- Maintain immutable-style audit records with restricted modification permissions.
Important: Approval is not a substitute for isolation. An approved command can still be malicious or misinterpreted. We should offer execution inside a restricted workspace or disposable environment for untrusted projects.

Part VIII — Project intelligence and indexing
17. Complete indexing architecture
The indexing engine should be independent of the conversational agent.

It should be possible to run:
NEMO index D:\Projects\COSEM


without calling the LLM at every stage.
Indexing stages
Stage	Operation	Technology
1	File discovery	pathlib, scandir
2	Ignore filtering	.gitignore-aware scanner
3	Hashing	SHA-256
4	Language detection	Extension + Tree-sitter
5	Syntax parsing	Tree-sitter
6	Symbol extraction	AST queries
7	Dependency extraction	Language-specific analyzers
8	Chunk generation	Structure-aware chunker
9	Embedding	NVIDIA embedding API
10	Graph construction	Custom extraction + Neo4j
11	Metadata persistence	PostgreSQL
12	Validation	Index integrity checks

What must be excluded?
The scanner should exclude by default:
.git/
.venv/
venv/
node_modules/
__pycache__/
dist/
build/
coverage/
.next/
target/
vendor/
.cache/


It must also respect .gitignore.

Additional sensitive exclusions:
.env
.env.*
*.pem
*.key
*.p12
*.pfx
credentials.json
secrets/


The user can explicitly authorize indexing particular files, but credentials should not be ingested into the memory or vector index.
Chunking strategy
Do not split code using a fixed number of characters alone.

Use:
1. File-level metadata.
2. Class-level boundaries.
3. Function-level boundaries.
4. Import relationships.
5. Documentation blocks.
6. Line ranges.
7. Token-based limits.
Each chunk should contain:
{
  "project_id": "uuid",
  "file_path": "src/auth/controller.py",
  "symbol": "AuthController.refresh_token",
  "language": "python",
  "start_line": 40,
  "end_line": 95,
  "content_hash": "sha256",
  "embedding_model": "configured-model-id"
}


Incremental indexing
The most important optimization:
File change detected
       |
       v
Calculate new hash
       |
       v
Compare previous hash
       |
       +---- Unchanged ---> Skip
       |
       v
Parse changed file
       |
       v
Update symbols and chunks
       |
       v
Invalidate dependent graph edges
       |
       v
Regenerate affected embeddings
       |
       v
Update Neo4j projection
       |
       v
Mark index healthy


Use a debounce period for file watchers so that a single save operation doesn't trigger dozens of duplicate indexing jobs.
Project understanding levels
I propose three indexing levels.
Level	What it does
Quick	Project tree, manifests, basic metadata
Standard	Symbols, imports, dependencies, embeddings
Deep	Full graph, cross-file analysis, architecture summaries

Deep indexing should not mean sending the entire source tree to Nemotron. Use static analysis first and targeted model analysis afterward.
Graphify integration
Graphify can be used as an optional graph-generation adapter if its current CLI/API supports the required operations.

We should define an internal contract:
class GraphExtractor:    async def extract(        self,        project_snapshot: str    ) -> list[dict]:        ...



This allows Graphify, a custom Tree-sitter-based extractor or another graph engine to be swapped without affecting retrieval.

The source of truth must remain our own normalized graph schema.

18. Hybrid retrieval engine
Project questions should use multiple retrieval methods.

For example:
How does the payment module communicate
with the database, and where is the connection
configured?


NEMO should:
1. Search for payment-related symbols.
2. Search semantically for database communication.
3. Traverse graph relationships.
4. Locate configuration files.
5. Retrieve relevant file sections.
6. Check the latest project snapshot.
7. Supply the evidence to the agent.
The retrieval pipeline:
Query
  |
  v
Intent and Scope Detection
  |
  +------> Keyword Search
  |
  +------> Vector Search
  |
  +------> Graph Traversal
  |
  +------> Symbol Lookup
  |
  v
Result Fusion
  |
  v
Reranking
  |
  v
Context Assembly
  |
  v
Nemotron


We should also preserve source references:
- File path.
- Line range.
- Git commit.
- Index version.
- Retrieval method.
This allows NEMO to answer with evidence rather than inventing project architecture.
Part IX — IDE integrations
19. IDE adapter architecture
The system must support different editors without depending on their internal implementation.

Every editor adapter should follow this contract:
from typing import Protocolclass IDEAdapter(Protocol):    async def detect(self) -> bool:        ...    async def get_installation(self) -> dict:        ...    async def open_project(self, path: str) -> bool:        ...    async def open_file(        self,        path: str,        line: int | None = None    ) -> bool:        ...    async def get_capabilities(self) -> dict:        ...



Initial integrations
IDE	Integration method	Priority
Antigravity	Executable discovery and supported launch arguments	P0
VS Code	code CLI and extension	P0
Cursor	CLI and editor adapter	P1
Windsurf	CLI and editor adapter	P2
Other editors	Custom adapter interface	P2

Antigravity-specific requirements
We must not assume Antigravity behaves identically to VS Code.

The adapter needs to:
1. Locate the executable.
2. Detect its installation path.
3. Check its supported command-line arguments.
4. Open a specified workspace.
5. Avoid launching duplicate instances unnecessarily.
6. Verify that the intended workspace opened.
For more advanced functionality, a dedicated IDE extension or supported local communication interface will be required.
IDE bridge
I recommend an optional extension that communicates with the daemon.

It can provide:
- Active workspace identification.
- Current file and selection.
- Editor diagnostics.
- File navigation.
- Approved code modifications.
- Agent status.
- Project context synchronization.
The extension should not become a requirement for basic CLI functionality.

Part X — Command-line interface specification
20. Command hierarchy
The command namespace should be consistent and predictable.

The following is the proposed complete command catalogue.
20.1 Root commands
Command	Description
NEMO	Launch interactive assistant
NEMO chat	Enter conversational mode
NEMO ask	Submit a single question
NEMO status	Display system status
NEMO doctor	Diagnose installation
NEMO version	Display version
NEMO update	Update NEMO

20.2 Setup and configuration
NEMO setup
NEMO setup ai
NEMO setup memory
NEMO setup database
NEMO setup ide
NEMO setup environment

NEMO config show
NEMO config set shell powershell
NEMO config set ide antigravity

NEMO provider list
NEMO provider configure nvidia
NEMO provider test
NEMO model list
NEMO model switch nemotron
NEMO model test


The setup flow must validate actual connectivity and dependencies, not merely save configuration values.
20.3 Personal profile
NEMO profile show
NEMO profile set name "Omkar"
NEMO profile set default-ide antigravity
NEMO profile set default-shell powershell
NEMO profile workspace add "D:\Projects"
NEMO profile workspace list


20.4 Memory
NEMO memory init
NEMO memory status
NEMO memory search "Redis configuration"
NEMO memory inspect <id>
NEMO memory update <id>
NEMO memory export
NEMO memory backup
NEMO memory restore
NEMO memory forget <id>

NEMO remember "Project uses PostgreSQL"


Memory deletion should distinguish between deleting an extracted fact and deleting its underlying conversation source. The user should be able to understand the scope of deletion.
20.5 Projects
NEMO project add "D:\Projects\COSEM"
NEMO project list
NEMO project show COSEM
NEMO project open COSEM
NEMO project remove COSEM
NEMO project switch COSEM

NEMO project explain COSEM
NEMO project dependencies COSEM
NEMO project architecture COSEM


Removing a project from NEMO must not delete its original directory.
20.6 Indexing
NEMO index .
NEMO index . --quick
NEMO index . --standard
NEMO index . --deep
NEMO index . --incremental
NEMO index . --rebuild
NEMO index . --watch

NEMO index status
NEMO index history
NEMO index cancel <job-id>


20.7 IDE
NEMO ide list
NEMO ide detect
NEMO ide set antigravity
NEMO ide open COSEM
NEMO ide open-file src/main.py
NEMO ide status


20.8 Terminal
NEMO run "npm install"
NEMO run "npm run dev"

NEMO shell
NEMO shell powershell
NEMO shell cmd
NEMO shell bash

NEMO sessions
NEMO sessions show <id>
NEMO sessions attach <id>
NEMO sessions stop <id>

NEMO history
NEMO history --project COSEM


20.9 Autonomous operations
NEMO diagnose
NEMO fix
NEMO fix --auto
NEMO build
NEMO test
NEMO lint
NEMO dependencies
NEMO explain-error
NEMO plan
NEMO task list
NEMO task resume <id>
NEMO task cancel <id>


20.10 Security
NEMO security status
NEMO security policy show
NEMO security policy set
NEMO approvals list
NEMO approvals show <id>
NEMO approvals approve <id>
NEMO approvals reject <id>
NEMO audit


20.11 Native command passthrough
This is an especially important requirement.

The CLI must not force developers to learn an entirely new command language.

We should support two entry modes:

Explicit native execution:
NEMO run --shell powershell -- npm install


Interactive shell passthrough:
NEMO> git status
NEMO> python --version
NEMO> docker ps


Built-in commands take precedence only when the first token matches a registered NEMO command. Other inputs are passed to the selected native shell.

For interactive shell mode, we should support:
- Quoted arguments.
- Pipes.
- Redirection.
- Environment variables.
- Shell-specific syntax.
- Multi-line input.
- Keyboard interrupts.
We should not try to recreate PowerShell's parser inside Python. Native shell syntax must be handled by PowerShell itself.

21. Natural-language routing specification
We need an explicit intent classification layer.

Suggested intent categories:
Intent	Example	Destination
OPEN_IDE	Open Antigravity	IDE adapter
OPEN_PROJECT	Load COSEM	Project manager
EXECUTE_COMMAND	Run npm install	Execution engine
INSTALL_DEPENDENCIES	Install required packages	Dependency workflow
INDEX_PROJECT	Understand this codebase	Indexer
SEARCH_CODE	Find authentication logic	Retrieval engine
DEBUG_ERROR	Fix the build failure	Diagnostic workflow
EXPLAIN_PROJECT	Explain the architecture	Project retrieval
RECALL_MEMORY	What did we decide yesterday?	Memory retrieval
CREATE_TASK	Implement refresh tokens	Agent workflow
CONFIGURE_SYSTEM	Set up NVIDIA	Setup manager

Routing design
User Input
    |
    v
Fast Deterministic Parser
    |
    +---- Known NEMO command
    |          |
    |          v
    |      Command Handler
    |
    +---- Recognized native shell command
    |          |
    |          v
    |      Native Execution
    |
    +---- Natural language
               |
               v
         Intent Classifier
               |
               v
          Context Builder
               |
               v
          Agent Planner


We should not use an LLM to classify every command.

For example, NEMO status, git status and python --version can be routed deterministically.

For ambiguous instructions, Nemotron should resolve the intended action.
Project resolution
When the user says:
Open my current project.


Resolution order:
1. Explicit project argument.
2. Active NEMO project.
3. Active IDE workspace, if available.
4. Current shell working directory.
5. Recently opened registered project.
If multiple candidates remain, ask one clarification rather than guessing.

Part XI — Configuration and system initialization
22. Configuration architecture
Configuration should be layered.
1. Built-in defaults
2. Installation configuration
3. User configuration
4. Project configuration
5. Temporary command overrides


Suggested paths:
%APPDATA%\NEMO\
    config.yaml
    profiles/
    logs/
    cache/
    state/

%LOCALAPPDATA%\NEMO\
    databases/
    index/
    artifacts/
    backups/
    temporary/


The actual paths should be configurable, but this is the default Windows layout.
Example configuration
app:
  name: NEMO
  environment: production
  log_level: INFO

runtime:
  shell: powershell
  default_ide: antigravity
  workspace_roots:
    - "D:\\Projects"

ai:
  provider: nvidia
  model: nvidia/nemotron-3.5-super-vl-120b-a12b
  streaming: true
  reasoning: true

memory:
  backend: hybrid
  semantic_search: true
  graph_search: true

databases:
  postgres:
    enabled: true
  neo4j:
    enabled: true
  redis:
    enabled: true

agent:
  max_iterations: 12
  require_approval_for_risky_actions: true
  verify_before_completion: true

execution:
  default_timeout: 600
  output_limit_mb: 25
  allow_admin_commands: false

indexing:
  mode: incremental
  watch_enabled: true
  respect_gitignore: true


The API key must be referenced through the OS credential store rather than this YAML file.
Setup wizard
The complete first-run flow:
NEMO SETUP

01. Welcome
02. NVIDIA API credentials
03. Model verification
04. PostgreSQL initialization
05. pgvector verification
06. Neo4j initialization
07. Redis initialization
08. Windows shell detection
09. IDE discovery
10. User profile
11. Workspace registration
12. Permission configuration
13. Background daemon setup
14. System health checks
15. Initial project indexing

              COMPLETE


Setup should support partial completion and resumption. If Neo4j is unavailable, the wizard should explain which capabilities are disabled instead of silently claiming a complete hybrid setup.

23. API and event contracts
Even though this is a local CLI, we need explicit internal API contracts.

Proposed daemon API groups:
Endpoint	Purpose
GET /v1/health	Daemon health
GET /v1/status	System status
POST /v1/tasks	Create agent task
GET /v1/tasks/{id}	Inspect task
POST /v1/tasks/{id}/resume	Resume task
POST /v1/tasks/{id}/cancel	Cancel task
POST /v1/approvals/{id}	Submit decision
POST /v1/terminal/sessions	Create terminal
POST /v1/terminal/execute	Execute command
GET /v1/terminal/sessions	List sessions
POST /v1/projects	Register project
POST /v1/index/jobs	Start indexing
GET /v1/index/jobs/{id}	Check indexing

Streaming:
GET /v1/tasks/{id}/events


Use Server-Sent Events for task progress in the initial implementation, with WebSockets reserved for bidirectional editor communication.
Standard event format
{
  "event_id": "uuid",
  "task_id": "uuid",
  "type": "execution.output",
  "timestamp": "2026-11-10T12:00:00Z",
  "data": {
    "stream": "stdout",
    "text": "Installing packages..."
  }
}


Events should include:
task.created
task.planned
task.waiting_approval
task.approved
task.rejected
task.started
execution.started
execution.output
execution.completed
execution.failed
index.started
index.progress
index.completed
memory.updated
task.completed
task.cancelled


The event stream must not be treated as the durable task record. Persist important lifecycle transitions in PostgreSQL.

Part XII — Production reliability
24. Failure recovery
A real developer agent needs to recover from interruptions.

We should explicitly handle the following cases.
Failure	Required recovery
CLI closes	Daemon continues active tasks
Daemon crashes	Recover task state and clean orphan processes
NVIDIA API unavailable	Retry, pause or use configured fallback
Database disconnects	Reconnect with bounded backoff
Neo4j unavailable	Continue using PostgreSQL retrieval
Redis unavailable	Degrade to database-backed job queue where supported
Indexing interrupted	Resume from last committed checkpoint
IDE not installed	Report unavailable and suggest supported alternative
Terminal process hangs	Timeout or user-controlled cancellation
Agent loops	Iteration limit and budget enforcement

Task durability
Every agent task should have:
- A unique task ID.
- A stable thread ID.
- A durable execution plan.
- Completed-step records.
- Pending approval records.
- Execution artifact references.
- Recovery metadata.
For commands with side effects, retries require special handling.

For example, blindly retrying a database migration or file deletion is not acceptable.

We should use idempotency keys where possible and inspect the previous operation state before retrying.
25. Logging and observability
Use Pino's Python equivalent, structlog, with standard Python logging integration.

Each task should have a correlation ID.

Log:
- Task creation.
- Intent classification.
- Memory retrieval.
- Tool invocation.
- Approval decisions.
- Process execution.
- Exit status.
- Model request latency.
- Token usage.
- Indexing progress.
- Database errors.
- Recovery operations.
Do not log:
- API keys.
- Passwords.
- Authentication tokens.
- Unredacted .env contents.
- Sensitive command arguments.
Useful diagnostics:
NEMO doctor
NEMO doctor --deep
NEMO status --verbose
NEMO audit --recent



26. Performance architecture
We should separate fast local actions from model-dependent actions.
Operation	Model required?
NEMO status	No
NEMO doctor	No
git status	No
Open known IDE	No
Find registered project	No
Search exact file text	No
Search semantically	Embedding model
Explain architecture	Reasoning model
Diagnose complex error	Reasoning model
Plan multi-step repair	Reasoning model
Summarize historical development	Retrieval + reasoning

Performance optimizations
1. Cache project metadata.
2. Reuse embeddings when hashes are unchanged.
3. Index changed files only.
4. Use asynchronous I/O for network and database operations.
5. Batch embedding requests within provider limits.
6. Limit context to relevant files and memories.
7. Cache IDE discovery results.
8. Avoid repeated package-manager scans.
9. Stream output instead of waiting for full responses.
10. Apply bounded concurrency to indexing and terminal jobs.
Memory and index size management
Do not promise mathematically infinite memory.

The correct production design is effectively unbounded logical retention, limited by available disk space, database capacity, model quotas and configured storage policies.

NEMO should expose:
NEMO storage status
NEMO storage optimize
NEMO storage backup
NEMO storage restore


It should also provide retention and backup controls, without automatically deleting valuable history to free space.
Part XIII — Implementation roadmap
27. Development phases and deliverables
We will build NEMO in twelve implementation phases.

I would not compress these into one development sprint. Each phase must produce a working, tested component that becomes the foundation for the next.
Implementation roadmap
1. Phase 0 — Architecture and engineering foundation
   Specification phase
   Deliverables:
   - Repository initialization.
   - Dependency management.
   - Coding standards.
   - Module contracts.
   - Architecture decision records.
   - CI pipeline.
   - Development environment.
2. Phase 1 — CLI foundation
   - Typer commands.
   - Rich terminal rendering.
   - Interactive command mode.
   - Configuration loader.
   - Logging.
   - Native command passthrough.
   Acceptance: NEMO launches, accepts commands and runs ordinary PowerShell commands.
3. Phase 2 — NVIDIA AI integration
   - NVIDIA provider adapter.
   - API credential management.
   - Streaming responses.
   - Tool calling.
   - Error handling.
   - Model configuration.
   Acceptance: NEMO understands natural-language requests through Nemotron.
4. Phase 3 — Terminal execution engine
   - Subprocess management.
   - Persistent PTY sessions.
   - PowerShell, CMD and Bash.
   - Process monitoring.
   - Output streaming.
   - Cancellation and timeout.
   - Exit-code verification.
   Acceptance: NEMO can run commands, wait, observe failures and manage processes.
5. Phase 4 — Database and memory foundation
   - PostgreSQL.
   - pgvector.
   - Redis.
   - Neo4j.
   - Database migrations.
   - Profile storage.
   - Conversation persistence.
   Acceptance: User information and conversation history survive restarts.
6. Phase 5 — Intelligent memory engine
   - Memory extraction.
   - Semantic search.
   - Keyword search.
   - Graph relationships.
   - Temporal memory.
   - Conflict detection.
   - Memory correction.
   Acceptance: NEMO recalls previously established facts with source provenance.
7. Phase 6 — Project intelligence
   - Project scanner.
   - Tree-sitter parsing.
   - Symbol extraction.
   - Dependency analysis.
   - Vector indexing.
   - Graph extraction.
   - Incremental indexing.
   Acceptance: NEMO can explain a project using actual indexed source evidence.
8. Phase 7 — IDE integration
   - VS Code.
   - Antigravity.
   - Workspace detection.
   - Project launching.
   - File navigation.
   - IDE adapter registry.
   Acceptance: NEMO opens the intended project and verifies the workspace launch.
9. Phase 8 — Agent orchestration
   - LangGraph supervisor.
   - Planner.
   - Tool registry.
   - Context builder.
   - Approval interrupts.
   - Checkpointing.
   - Task recovery.
   Acceptance: Multi-step natural-language tasks can be planned and executed.
10. Phase 9 — Autonomous debugging
    - Terminal error detection.
    - Dependency troubleshooting.
    - Build diagnostics.
    - Repair planning.
    - Controlled file modifications.
    - Regression verification.
    Acceptance: NEMO fixes a supported test failure and demonstrates that the failure is resolved.
11. Phase 10 — Background daemon
    - Windows daemon.
    - IPC.
    - Background indexing.
    - Persistent terminal sessions.
    - Worker scheduling.
    - Crash recovery.
    Acceptance: Closing the CLI does not interrupt daemon-managed work.
12. Phase 11 — Production release
    - Security audit.
    - Database backup and restore.
    - Installer.
    - Executable packaging.
    - Update mechanism.
    - Performance benchmarks.
    - User documentation.
    Acceptance: A clean Windows installation can be configured and used without manually editing source code.

Estimated development duration
For one developer working substantially on the project:
Milestone	Indicative duration
CLI, AI and execution foundation	2–3 weeks
Memory and database	2–3 weeks
Project intelligence	2–3 weeks
IDE and agent integration	2–3 weeks
Daemon and reliability	1–2 weeks
Security, testing and release	2 weeks
Total	11–16 weeks

This is a planning estimate, not a delivery guarantee. Complex IDE integration and Windows process management may require additional investigation.

Part XIV — Testing and quality strategy
28. Testing architecture
We must test more than whether the model returns a sensible response.

NEMO is a system that performs real actions, so testing must cover the complete action lifecycle.
Testing layers
Layer	Framework	What we test
Unit	pytest	Individual functions and modules
Integration	pytest	Database and external integrations
Agent	LangGraph test harness	Planning, interrupts and recovery
Execution	pytest + Windows test processes	Terminal behaviour
Memory	Retrieval evaluation	Recall accuracy
Indexing	Fixture repositories	Code and graph extraction
Security	pytest + adversarial tests	Authorization and injection resistance
End-to-end	pytest	Full developer workflows
Performance	pytest-benchmark	Latency and resource usage

28.1 Terminal test cases
We need a dedicated Windows test suite.
Test	Expected result
Run python --version	Correct output and exit code
Run npm install	Wait until process exits
Run a failing command	Correct nonzero exit code
Run a long-running server	Session remains active
Send Ctrl+C	Process receives interruption
Kill parent process	Child process handling is verified
Close CLI	Daemon-managed process survives
Run CMD syntax	Correct shell interpretation
Run PowerShell pipeline	Correct pipeline behaviour
Run command with spaces	Arguments remain correctly quoted
Command timeout	Process tree is terminated
Large output	Output limits and log references work

28.2 Memory evaluation
Create a benchmark with questions whose answers are known.

Example:
Memory event 1:
The project uses PostgreSQL.

Memory event 2:
The authentication service uses Redis.

Memory event 3:
We migrated the database from MongoDB to PostgreSQL.


Test queries:
Which database is currently used?
What does Redis manage?
Which database did we use previously?
When did we change the database?


Metrics:
- Recall@5.
- Precision@5.
- Mean Reciprocal Rank.
- Correct temporal resolution.
- Contradiction resolution.
- Source attribution accuracy.
Initial release targets:
Metric	Target
Known-fact retrieval recall@5	95%
Correct temporal fact retrieval	95%
Memory source attribution	100%
False current-fact retrieval	Below 2%

These targets apply to a curated evaluation dataset, not arbitrary real-world questions.
28.3 Project intelligence evaluation
Create fixture repositories containing:
- Python projects.
- React/TypeScript projects.
- Node.js backends.
- Rust applications.
- Multi-package monorepos.
- Projects with circular imports.
- Projects with generated files.
- Projects with large dependencies.
Test:
1. Correct file discovery.
2. Correct language identification.
3. Correct symbol extraction.
4. Import graph accuracy.
5. Dependency detection.
6. Incremental update correctness.
7. Vector retrieval quality.
8. Source line attribution.
28.4 Agent evaluation
Create repeatable tasks:
Task 1:
Open an existing project in VS Code.

Task 2:
Identify missing Python dependencies.

Task 3:
Install dependencies and run tests.

Task 4:
Diagnose a deliberately broken build.

Task 5:
Fix a missing import.

Task 6:
Explain the authentication architecture.

Task 7:
Recall a previous technical decision.

Task 8:
Resume a task after daemon restart.


Measure:
- Task completion rate.
- Number of unnecessary actions.
- Tool-call accuracy.
- Approval policy violations.
- Recovery success.
- Verification success.
- Model tokens consumed.
- Total execution time.
A task is successful only when its expected external outcome is verified. A convincing textual answer is not sufficient.

29. Production acceptance criteria
Before declaring the first production release, these conditions must pass.
Release acceptance checklist
0 of 20 verified
0%



[ ] Clean Windows installation succeeds
[ ] NVIDIA API configuration and validation work
[ ] Native PowerShell commands execute correctly
[ ] CMD and Bash execution work
[ ] Persistent terminal sessions survive CLI closure
[ ] Process completion and exit codes are reliable
[ ] Approval policy blocks unauthorized actions
[ ] PostgreSQL backup and restoration are tested
[ ] Personal memory persists across restarts
[ ] Project-specific memory is isolated
[ ] Semantic and graph retrieval work
[ ] Incremental project indexing works
[ ] VS Code integration works
[ ] Antigravity integration works on the supported installation
[ ] Agent tasks can pause and resume
[ ] Failed operations are recorded correctly
[ ] Source changes are verified with tests
[ ] Daemon recovers from a simulated crash
[ ] Secrets are never logged or stored in plaintext
[ ] End-to-end benchmark suite passes
Reset checklist

Part XV — Architectural decisions and risks
30. Architecture Decision Records
These are the decisions we should preserve in docs/decisions/.
ADR	Decision	Status
ADR-001	Python-first architecture	Accepted
ADR-002	Modular monolith	Accepted
ADR-003	LangGraph orchestration	Accepted
ADR-004	PostgreSQL as primary database	Accepted
ADR-005	pgvector for semantic memory	Accepted
ADR-006	Neo4j for relationship graph	Accepted
ADR-007	Redis for transient coordination	Accepted
ADR-008	Windows-first execution	Accepted
ADR-009	Daemon-owned process management	Accepted
ADR-010	Approval-based autonomy	Accepted
ADR-011	NVIDIA provider abstraction	Accepted
ADR-012	Incremental project indexing	Accepted
ADR-013	Structured tool execution	Accepted
ADR-014	Temporal memory and provenance	Accepted
ADR-015	Cross-platform architecture	Accepted

Remaining engineering decisions
These are implementation choices we should validate before final dependency lock:
1. Exact NVIDIA embedding model and vector dimension.
2. Whether to use a dedicated NVIDIA reranker.
3. Exact Antigravity launch and extension integration capabilities.
4. Production Windows daemon hosting mechanism.
5. Native named-pipe transport versus an authenticated local API.
6. Whether Redis is necessary for the initial single-machine installation or can be enabled only in full mode.
7. Whether Graphify adds enough value over our own Tree-sitter graph extraction to justify maintaining an adapter.
These do not block the overall architecture.
31. Main technical risks
Risk	Mitigation
Model API availability changes	Provider abstraction and fallback
Model tool-call errors	Typed validation and execution verification
Large codebases	Incremental indexing
Embedding costs	Hash caching and selective indexing
Memory contradictions	Temporal validity and source provenance
Windows PTY complexity	Dedicated ConPTY test suite
IDE CLI differences	Individual adapters
Agent loops	Iteration and budget limits
Unsafe commands	Policy engine and approvals
Database complexity	PostgreSQL as authoritative storage
Daemon instability	Checkpoints and supervised workers
Prompt injection from source files	Treat repository content as untrusted data

One critical distinction about security
A malicious README, source comment, package script or terminal output may contain instructions directed at the AI.

Those instructions must be treated as untrusted project data, never as authorization to execute actions.

The agent must obey the developer's instructions and NEMO's security policies, not instructions embedded in files it happens to inspect.

Part XVI — Final product definition
32. What the completed NEMO should look like
Here is the final target experience we should build toward.
NEMO
Target experience

AI Developer Environment · Local Runtime
NEMO ASSISTANT
Connected

Good evening.
Your development environment is ready.

ACTIVE PROJECT

COSEM

IDE

Antigravity

MEMORY

Synchronized

INDEX

Up to date



Recent activity
- Project dependencies verified
- Project knowledge base available
- Previous development context restored
- Background monitoring active

NATURAL LANGUAGE INPUT

What would you like to work on?

Example: Analyse the authentication system, identify missing tests and implement refresh token rotation.


The important part is that this interface is only the entry point. All the actual intelligence, execution and memory live in the underlying architecture.
33. Final decisions I recommend locking
There are two things I want to emphasize before implementation.

First: NVIDIA model lifecycle.

The current NVIDIA catalogue identifies our chosen Nemotron model, but the catalogue also displays a deprecation warning on its listing. We need to verify the actual endpoint's retirement schedule and availability before committing it as the production default. 

Try NVIDIA NIM APIs+1

The model card advertises up to 1M context, while the hosted Build page currently lists 262K. We should configure against the actual endpoint's supported limit, not assume the theoretical maximum. 

NVIDIA NIM+1

Second: Don't overcomplicate the initial installation.

The architecture supports PostgreSQL, pgvector, Neo4j and Redis, but the setup wizard should manage their installation, configuration and health checks. The user should never need to manually configure multiple databases to use basic NEMO functionality.

My preferred installation experience is:
NEMO setup
NEMO provider configure nvidia
NEMO memory init
NEMO project add "D:\Projects\COSEM"
NEMO index "D:\Projects\COSEM" --deep
NEMO


Everything else should be progressively configurable.

34. Specification completion status
Architecture specified
Deliverable	Status
Product definition	Specified
Production tech stack	Selected
Repository structure	Specified
Database architecture	Specified
PostgreSQL schema	Designed
Knowledge graph	Designed
Memory architecture	Designed
LangGraph architecture	Designed
Terminal execution	Specified
IDE integrations	Specified
Command hierarchy	Specified
Security architecture	Specified
Testing strategy	Specified
Development roadmap	Specified
Coding and implementation	Not started

My recommendation for the next stage
Before writing the first application module, we should create three foundational engineering documents:
1. Architecture and interface contracts: Exact module responsibilities, Python class interfaces, events, IPC contracts and dependency rules.
2. Database implementation specification: Actual PostgreSQL DDL, Neo4j constraints, indexes, migrations and LangGraph checkpoint integration.
3. Agent and execution specification: Complete tool schemas, LangGraph node definitions, approval state transitions and Windows process lifecycle.
These will remove ambiguity when implementation begins.

My recommendation is to freeze this architecture as NEMO v1.0 and move into detailed engineering design, followed by implementation of Phase 0 and Phase 1. We should not start building the AI agent before the terminal runtime, tool contracts and security boundaries are established.