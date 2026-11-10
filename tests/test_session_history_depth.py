"""Production-grade in-depth test suite for conversation sessions, history, 1-based resume, fork, and export."""

# 1. Standard library imports
from contextlib import asynccontextmanager
from pathlib import Path
import tempfile

# 2. Third-party imports
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

# 3. Local / internal imports
from nemo.cli.chat import interactive_session_picker
from nemo.database.models import Base, Conversation, ConversationMessage
from nemo.memory.repository import ConversationRepository

# 4. Types, Protocols, Schemas
# (None)

# 5. Core logic / classes / functions
@asynccontextmanager
async def create_isolated_conv_repo():
    """Create isolated SQLite database engine and ConversationRepository per test."""
    with tempfile.TemporaryDirectory() as tmpdir:
        test_db = Path(tmpdir) / "test_sessions.db"
        test_url = f"sqlite+aiosqlite:///{test_db.as_posix()}"
        engine = create_async_engine(test_url, echo=False)

        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        session_factory = async_sessionmaker(bind=engine, expire_on_commit=False, class_=AsyncSession)

        @asynccontextmanager
        async def session_provider():
            async with session_factory() as sess:
                yield sess
                await sess.commit()

        yield {
            "engine": engine,
            "session_provider": session_provider,
            "repo": ConversationRepository(session_provider=session_provider),
        }

        await engine.dispose()


@pytest.mark.asyncio
async def test_conversation_creation_and_attributes():
    """Verify conversation creation with title, project association, and default metadata."""
    async with create_isolated_conv_repo() as db:
        repo: ConversationRepository = db["repo"]

        conv = await repo.create_conversation(title="Refactor Authentication Service", project_id="proj_123")
        assert conv.id is not None
        assert len(conv.id) == 36  # Standard UUID format
        assert conv.title == "Refactor Authentication Service"
        assert conv.project_id == "proj_123"
        assert conv.created_at is not None


@pytest.mark.asyncio
async def test_conversation_multi_turn_append_and_order():
    """Verify appending multi-turn conversation messages preserves strict chronological ordering."""
    async with create_isolated_conv_repo() as db:
        repo: ConversationRepository = db["repo"]
        conv = await repo.create_conversation(title="Debugging Database Latency")

        # Append alternating turns
        m1 = await repo.add_message(conv.id, "user", "Why is SQLite locking during writes?")
        m2 = await repo.add_message(conv.id, "assistant", "WAL mode needs to be activated: PRAGMA journal_mode=WAL;")
        m3 = await repo.add_message(conv.id, "user", "Does that persist across connection closes?")
        m4 = await repo.add_message(conv.id, "assistant", "Yes, WAL mode is persistent in the database header.")

        messages = await repo.get_messages(conv.id)
        assert len(messages) == 4
        assert [m.id for m in messages] == [m1.id, m2.id, m3.id, m4.id]
        assert [m.role for m in messages] == ["user", "assistant", "user", "assistant"]
        assert "PRAGMA journal_mode=WAL;" in messages[1].content


@pytest.mark.asyncio
async def test_conversation_1based_index_resolution():
    """Verify resolving sessions using 1-based index (e.g. 1st is most recent, 2nd is next)."""
    async with create_isolated_conv_repo() as db:
        repo: ConversationRepository = db["repo"]

        c1 = await repo.create_conversation(title="Task A")
        c2 = await repo.create_conversation(title="Task B")
        c3 = await repo.create_conversation(title="Task C")

        all_convs = await repo.list_conversations()
        assert len(all_convs) == 3

        # Test 1-based resolution logic
        def resolve_by_index(num_str: str, convs: list[Conversation]) -> Conversation | None:
            if num_str.isdigit():
                idx = int(num_str) - 1
                if 0 <= idx < len(convs):
                    return convs[idx]
            return None

        # 1 should point to most recent (Task C)
        first = resolve_by_index("1", all_convs)
        assert first is not None
        assert first.id == c3.id

        # 2 should point to second (Task B)
        second = resolve_by_index("2", all_convs)
        assert second is not None
        assert second.id == c2.id

        # 3 should point to third (Task A)
        third = resolve_by_index("3", all_convs)
        assert third is not None
        assert third.id == c1.id


@pytest.mark.asyncio
async def test_conversation_1based_index_boundaries():
    """Verify 1-based index resolution safely rejects out-of-bounds indices."""
    async with create_isolated_conv_repo() as db:
        repo: ConversationRepository = db["repo"]
        await repo.create_conversation(title="Single Task")
        all_convs = await repo.list_conversations()

        def resolve_by_index(num_str: str, convs: list[Conversation]) -> Conversation | None:
            if num_str.isdigit():
                idx = int(num_str) - 1
                if 0 <= idx < len(convs):
                    return convs[idx]
            return None

        assert resolve_by_index("0", all_convs) is None
        assert resolve_by_index("2", all_convs) is None
        assert resolve_by_index("99", all_convs) is None
        assert resolve_by_index("-1", all_convs) is None
        assert resolve_by_index("abc", all_convs) is None


@pytest.mark.asyncio
async def test_conversation_keyword_search_resolution():
    """Verify title substring search allows resuming by keyword (e.g. 'resume refactor')."""
    async with create_isolated_conv_repo() as db:
        repo: ConversationRepository = db["repo"]
        await repo.create_conversation(title="Implement OAuth2 Google Provider")
        target_conv = await repo.create_conversation(title="Refactor Network Subprocess")
        await repo.create_conversation(title="Benchmark Embedding Speed")

        all_convs = await repo.list_conversations()

        def resolve_by_keyword(query: str, convs: list[Conversation]) -> Conversation | None:
            matches = [c for c in convs if query.lower() in c.title.lower()]
            return matches[0] if matches else None

        found = resolve_by_keyword("refactor", all_convs)
        assert found is not None
        assert found.id == target_conv.id

        found_case_insensitive = resolve_by_keyword("OAUTH", all_convs)
        assert found_case_insensitive is not None
        assert "OAuth2" in found_case_insensitive.title


@pytest.mark.asyncio
async def test_conversation_uuid_prefix_resolution():
    """Verify resolving conversation using short 8-character UUID prefix."""
    async with create_isolated_conv_repo() as db:
        repo: ConversationRepository = db["repo"]
        c = await repo.create_conversation(title="UUID Lookup Target")
        all_convs = await repo.list_conversations()

        short_prefix = c.id[:8]
        prefix_matches = [conv for conv in all_convs if conv.id.startswith(short_prefix)]
        assert len(prefix_matches) == 1
        assert prefix_matches[0].id == c.id


@pytest.mark.asyncio
async def test_conversation_fork_creates_independent_copy():
    """Verify fork_conversation clones history into new conversation with distinct ID."""
    async with create_isolated_conv_repo() as db:
        repo: ConversationRepository = db["repo"]
        orig = await repo.create_conversation(title="Original Architecture Investigation")
        await repo.add_message(orig.id, "user", "Step 1: Check components")
        await repo.add_message(orig.id, "assistant", "Components are operational.")

        forked = await repo.fork_conversation(orig.id, new_title="Exploratory Architecture Branch")
        assert forked is not None
        assert forked.id != orig.id
        assert forked.title == "Exploratory Architecture Branch"

        forked_messages = await repo.get_messages(forked.id)
        assert len(forked_messages) == 2
        assert forked_messages[0].content == "Step 1: Check components"
        assert forked_messages[1].content == "Components are operational."


@pytest.mark.asyncio
async def test_conversation_fork_isolation():
    """Verify additions to forked conversation do not mutate original conversation."""
    async with create_isolated_conv_repo() as db:
        repo: ConversationRepository = db["repo"]
        orig = await repo.create_conversation(title="Parent Session")
        await repo.add_message(orig.id, "user", "Message 1")

        forked = await repo.fork_conversation(orig.id)
        assert forked is not None

        # Add message to fork only
        await repo.add_message(forked.id, "user", "Message 2 in Fork")

        orig_msgs = await repo.get_messages(orig.id)
        fork_msgs = await repo.get_messages(forked.id)

        assert len(orig_msgs) == 1
        assert len(fork_msgs) == 2


@pytest.mark.asyncio
async def test_conversation_rename_title():
    """Verify renaming conversation title persists across queries."""
    async with create_isolated_conv_repo() as db:
        repo: ConversationRepository = db["repo"]
        conv = await repo.create_conversation(title="Initial Title")

        ok = await repo.update_title(conv.id, "Renamed Production Session")
        assert ok is True

        updated = await repo.get_conversation(conv.id)
        assert updated is not None
        assert updated.title == "Renamed Production Session"


@pytest.mark.asyncio
async def test_conversation_markdown_export_format():
    """Verify export_transcript generates Markdown transcript with titles, roles, and times."""
    async with create_isolated_conv_repo() as db:
        repo: ConversationRepository = db["repo"]
        conv = await repo.create_conversation(title="Release 1.0 Milestone Planning")
        await repo.add_message(conv.id, "user", "What are the remaining blockers?")
        await repo.add_message(conv.id, "assistant", "Zero blockers. All test suites are green.")

        transcript = await repo.export_transcript(conv.id)
        assert "# NEMO Task Session: Release 1.0 Milestone Planning" in transcript
        assert f"- **Session ID:** `{conv.id}`" in transcript
        assert "- **Total Messages:** 2" in transcript
        assert "### 👤 Developer" in transcript
        assert "What are the remaining blockers?" in transcript
        assert "### 🤖 NEMO Agent" in transcript
        assert "Zero blockers. All test suites are green." in transcript


@pytest.mark.asyncio
async def test_conversation_empty_export():
    """Verify exporting an empty conversation produces a valid transcript skeleton without crash."""
    async with create_isolated_conv_repo() as db:
        repo: ConversationRepository = db["repo"]
        conv = await repo.create_conversation(title="Fresh Session")

        transcript = await repo.export_transcript(conv.id)
        assert "# NEMO Task Session: Fresh Session" in transcript
        assert "- **Total Messages:** 0" in transcript


@pytest.mark.asyncio
async def test_conversation_cascade_deletion():
    """Verify deleting a conversation cascades and cleans up all related message rows."""
    async with create_isolated_conv_repo() as db:
        repo: ConversationRepository = db["repo"]
        conv = await repo.create_conversation(title="To Be Deleted")
        await repo.add_message(conv.id, "user", "Disposable question")
        await repo.add_message(conv.id, "assistant", "Disposable answer")

        # Ensure messages exist
        msgs_before = await repo.get_messages(conv.id)
        assert len(msgs_before) == 2

        # Delete conversation
        del_ok = await repo.delete_conversation(conv.id)
        assert del_ok is True

        # Conversation should not exist
        assert await repo.get_conversation(conv.id) is None

        # Related messages in table must be gone
        async with db["session_provider"]() as sess:
            stmt = select(ConversationMessage).where(ConversationMessage.conversation_id == conv.id)
            res = await sess.execute(stmt)
            remaining_messages = res.scalars().all()
            assert len(remaining_messages) == 0


@pytest.mark.asyncio
async def test_conversation_large_payload_preservation():
    """Verify multi-kilobyte code blocks and messages retain full integrity in database."""
    async with create_isolated_conv_repo() as db:
        repo: ConversationRepository = db["repo"]
        conv = await repo.create_conversation(title="Large Code Generation")

        large_code = "def process_data(idx: int) -> dict:\n    return {'id': idx}\n" * 200  # ~10KB
        await repo.add_message(conv.id, "assistant", large_code)

        msgs = await repo.get_messages(conv.id)
        assert len(msgs) == 1
        assert msgs[0].content == large_code


@pytest.mark.asyncio
async def test_conversation_project_filtering():
    """Verify list_conversations filters correctly by project_id."""
    async with create_isolated_conv_repo() as db:
        repo: ConversationRepository = db["repo"]
        await repo.create_conversation(title="Global Task", project_id=None)
        await repo.create_conversation(title="Project Alpha Task 1", project_id="proj_alpha")
        await repo.create_conversation(title="Project Alpha Task 2", project_id="proj_alpha")
        await repo.create_conversation(title="Project Beta Task", project_id="proj_beta")

        alpha_convs = await repo.list_conversations(project_id="proj_alpha")
        assert len(alpha_convs) == 2
        assert all(c.project_id == "proj_alpha" for c in alpha_convs)

        beta_convs = await repo.list_conversations(project_id="proj_beta")
        assert len(beta_convs) == 1
        assert beta_convs[0].title == "Project Beta Task"


# 6. Public exports
__all__ = [
    "test_conversation_creation_and_attributes",
    "test_conversation_multi_turn_append_and_order",
    "test_conversation_1based_index_resolution",
    "test_conversation_1based_index_boundaries",
    "test_conversation_keyword_search_resolution",
    "test_conversation_uuid_prefix_resolution",
    "test_conversation_fork_creates_independent_copy",
    "test_conversation_fork_isolation",
    "test_conversation_rename_title",
    "test_conversation_markdown_export_format",
    "test_conversation_empty_export",
    "test_conversation_cascade_deletion",
    "test_conversation_large_payload_preservation",
    "test_conversation_project_filtering",
]
