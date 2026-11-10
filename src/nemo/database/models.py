"""SQLAlchemy 2.0 database models for NEMO core entities."""

# 1. Standard library imports
from datetime import datetime, timezone
from typing import Any
import uuid

# 2. Third-party imports
from sqlalchemy import DateTime, Float, ForeignKey, Integer, JSON, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

# 3. Local / internal imports
# (None)

# 4. Types, Protocols, Schemas
class Base(DeclarativeBase):
    """Base declarative class for all SQLAlchemy entities."""
    pass


def generate_uuid() -> str:
    """Generate canonical UUID4 string."""
    return str(uuid.uuid4())


class UserProfile(Base):
    """User preferences and runtime environment profile."""
    __tablename__ = "user_profiles"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    name: Mapped[str] = mapped_column(String(100), default="Developer")
    preferences: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    timezone: Mapped[str] = mapped_column(String(50), default="UTC")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )


class Project(Base):
    """Registered developer workspace or codebase."""
    __tablename__ = "projects"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    name: Mapped[str] = mapped_column(String(200), index=True)
    root_path: Mapped[str] = mapped_column(String(1024), unique=True, index=True)
    status: Mapped[str] = mapped_column(String(50), default="active")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc)
    )

    memories: Mapped[list["MemoryItem"]] = relationship("MemoryItem", back_populates="project", cascade="all, delete-orphan")
    conversations: Mapped[list["Conversation"]] = relationship("Conversation", back_populates="project", cascade="all, delete-orphan")


class MemoryItem(Base):
    """Canonical memory record (facts, preferences, technical decisions)."""
    __tablename__ = "memory_items"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    scope: Mapped[str] = mapped_column(String(50), default="project", index=True)  # "global" | "project"
    project_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=True, index=True)
    type: Mapped[str] = mapped_column(String(50), default="fact", index=True)      # "fact" | "decision" | "preference"
    subject: Mapped[str | None] = mapped_column(String(200), nullable=True, index=True)
    predicate: Mapped[str | None] = mapped_column(String(100), nullable=True)
    object: Mapped[str | None] = mapped_column(String(200), nullable=True)
    content: Mapped[str] = mapped_column(Text)
    importance: Mapped[float] = mapped_column(Float, default=1.0)
    confidence: Mapped[float] = mapped_column(Float, default=1.0)
    status: Mapped[str] = mapped_column(String(50), default="active", index=True)  # "active" | "superseded" | "archived"
    metadata_: Mapped[dict[str, Any]] = mapped_column("metadata", JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc)
    )

    project: Mapped[Project | None] = relationship("Project", back_populates="memories")


class Conversation(Base):
    """Developer interaction sessions."""
    __tablename__ = "conversations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    project_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=True, index=True)
    title: Mapped[str] = mapped_column(String(255), default="Untitled Conversation")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    project: Mapped[Project | None] = relationship("Project", back_populates="conversations")
    messages: Mapped[list["ConversationMessage"]] = relationship("ConversationMessage", back_populates="conversation", cascade="all, delete-orphan")


class ConversationMessage(Base):
    """Individual message in conversation history."""
    __tablename__ = "conversation_messages"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    conversation_id: Mapped[str] = mapped_column(String(36), ForeignKey("conversations.id", ondelete="CASCADE"), index=True)
    role: Mapped[str] = mapped_column(String(20))  # "system" | "user" | "assistant"
    content: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    conversation: Mapped[Conversation] = relationship("Conversation", back_populates="messages")


class AgentTask(Base):
    """Autonomous agent task execution record."""
    __tablename__ = "agent_tasks"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    thread_id: Mapped[str] = mapped_column(String(100), index=True)
    objective: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(50), default="pending", index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc)
    )

# 5. Core logic / classes / functions
# (None)

# 6. Public exports
__all__ = [
    "Base",
    "UserProfile",
    "Project",
    "MemoryItem",
    "Conversation",
    "ConversationMessage",
    "AgentTask",
]

