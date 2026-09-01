"""SQLAlchemy models — spec §4.2, implemented as written.

`topic_mastery` is a denormalised rollup updated on every answer (§4.2). It feeds the
sampler's `weakness` term and the progress UI; it is never recomputed from `answers` at
query time.

Tables beyond Phase 1's needs are defined here because §4.2 is part of the spec's
contract (sections 0–6), not part of a phase. Defining them once avoids a migration per
phase; nothing outside ingestion is populated yet.
"""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


def _pk() -> Mapped[uuid.UUID]:
    return mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)


def _now() -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class Course(Base):
    __tablename__ = "courses"

    id: Mapped[uuid.UUID] = _pk()
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    code: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = _now()

    # passive_deletes defers to the database's ON DELETE CASCADE. Without it SQLAlchemy
    # first issues UPDATE ... SET course_id = NULL, which violates NOT NULL and makes a
    # course undeletable.
    documents: Mapped[list["Document"]] = relationship(
        back_populates="course", cascade="all, delete-orphan", passive_deletes=True
    )
    topics: Mapped[list["Topic"]] = relationship(
        back_populates="course", cascade="all, delete-orphan", passive_deletes=True
    )


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[uuid.UUID] = _pk()
    course_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("courses.id", ondelete="CASCADE"), nullable=False
    )
    filename: Mapped[str] = mapped_column(String(512), nullable=False)
    page_count: Mapped[int | None] = mapped_column(Integer)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    ingest_status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    ingest_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = _now()

    course: Mapped["Course"] = relationship(back_populates="documents")
    chunks: Mapped[list["Chunk"]] = relationship(
        back_populates="document", cascade="all, delete-orphan", passive_deletes=True
    )

    __table_args__ = (
        CheckConstraint(
            "ingest_status IN ('pending','processing','complete','failed')",
            name="ck_documents_ingest_status",
        ),
        # Idempotency (§9 task 8): re-ingesting an identical file into the same course is
        # a no-op. Scoped per course so two courses may legitimately share a document.
        UniqueConstraint("course_id", "sha256", name="uq_documents_course_sha256"),
    )


class Topic(Base):
    __tablename__ = "topics"

    id: Mapped[uuid.UUID] = _pk()
    course_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("courses.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    section_path: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    parent_topic_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("topics.id", ondelete="SET NULL")
    )
    chunk_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    order_index: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    course: Mapped["Course"] = relationship(back_populates="topics")


class Chunk(Base):
    __tablename__ = "chunks"

    id: Mapped[uuid.UUID] = _pk()
    document_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), nullable=False
    )
    course_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("courses.id", ondelete="CASCADE"), nullable=False
    )
    # Null until Phase 2 builds the topic tree (§10 task 2).
    topic_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("topics.id", ondelete="SET NULL"))
    text: Mapped[str] = mapped_column(Text, nullable=False)
    page_start: Mapped[int] = mapped_column(Integer, nullable=False)
    page_end: Mapped[int] = mapped_column(Integer, nullable=False)
    section_path: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    token_count: Mapped[int] = mapped_column(Integer, nullable=False)
    content_type: Mapped[str] = mapped_column(String(16), nullable=False, default="prose")
    quiz_usage_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    vector_id: Mapped[str | None] = mapped_column(String(64))

    document: Mapped["Document"] = relationship(back_populates="chunks")

    __table_args__ = (
        CheckConstraint(
            "content_type IN ('prose','table','code','figure_caption')",
            name="ck_chunks_content_type",
        ),
        CheckConstraint("page_end >= page_start", name="ck_chunks_page_order"),
        Index("ix_chunks_course_topic", "course_id", "topic_id"),
        Index("ix_chunks_quiz_usage_count", "quiz_usage_count"),
    )


class Quiz(Base):
    __tablename__ = "quizzes"

    id: Mapped[uuid.UUID] = _pk()
    course_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("courses.id", ondelete="CASCADE"), nullable=False
    )
    scope: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    question_count: Mapped[int] = mapped_column(Integer, nullable=False)
    difficulty: Mapped[str | None] = mapped_column(String(32))
    created_at: Mapped[datetime] = _now()
    generation_meta: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)


class Question(Base):
    __tablename__ = "questions"

    id: Mapped[uuid.UUID] = _pk()
    quiz_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("quizzes.id", ondelete="CASCADE"), nullable=False
    )
    topic_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("topics.id", ondelete="SET NULL"))
    stem: Mapped[str] = mapped_column(Text, nullable=False)
    options: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False)
    explanation: Mapped[str] = mapped_column(Text, nullable=False)
    # I1 — groundedness. Non-empty is enforced in the pipeline; content that cannot cite
    # its source is never persisted.
    source_chunk_ids: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    page_refs: Mapped[list[int]] = mapped_column(JSONB, nullable=False)
    difficulty: Mapped[str | None] = mapped_column(String(32))
    validator_report: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    order_index: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class Attempt(Base):
    __tablename__ = "attempts"

    id: Mapped[uuid.UUID] = _pk()
    quiz_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("quizzes.id", ondelete="CASCADE"), nullable=False
    )
    started_at: Mapped[datetime] = _now()
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    score: Mapped[float | None] = mapped_column(Float)


class Answer(Base):
    __tablename__ = "answers"

    id: Mapped[uuid.UUID] = _pk()
    attempt_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("attempts.id", ondelete="CASCADE"), nullable=False
    )
    question_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("questions.id", ondelete="CASCADE"), nullable=False
    )
    selected_option_id: Mapped[str | None] = mapped_column(String(4))
    is_correct: Mapped[bool] = mapped_column(Boolean, nullable=False)
    time_taken_ms: Mapped[int | None] = mapped_column(Integer)
    viewed_explanation: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class Flashcard(Base):
    __tablename__ = "flashcards"

    id: Mapped[uuid.UUID] = _pk()
    course_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("courses.id", ondelete="CASCADE"), nullable=False
    )
    topic_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("topics.id", ondelete="SET NULL"))
    front: Mapped[str] = mapped_column(Text, nullable=False)
    back: Mapped[str] = mapped_column(Text, nullable=False)
    source_chunk_ids: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    page_refs: Mapped[list[int]] = mapped_column(JSONB, nullable=False)
    origin: Mapped[str] = mapped_column(String(24), nullable=False, default="generated")
    created_at: Mapped[datetime] = _now()

    __table_args__ = (
        CheckConstraint("origin IN ('generated','missed_question')", name="ck_flashcards_origin"),
    )


class Review(Base):
    __tablename__ = "reviews"

    id: Mapped[uuid.UUID] = _pk()
    flashcard_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("flashcards.id", ondelete="CASCADE"), nullable=False
    )
    rating: Mapped[int] = mapped_column(Integer, nullable=False)
    reviewed_at: Mapped[datetime] = _now()
    stability: Mapped[float | None] = mapped_column(Float)
    difficulty: Mapped[float | None] = mapped_column(Float)
    due_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    state: Mapped[str] = mapped_column(String(16), nullable=False, default="new")
    lapses: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    __table_args__ = (
        CheckConstraint("rating BETWEEN 1 AND 4", name="ck_reviews_rating"),
        CheckConstraint(
            "state IN ('new','learning','review','relearning')", name="ck_reviews_state"
        ),
    )


class TopicMastery(Base):
    __tablename__ = "topic_mastery"

    id: Mapped[uuid.UUID] = _pk()
    course_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("courses.id", ondelete="CASCADE"), nullable=False
    )
    topic_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("topics.id", ondelete="CASCADE"), nullable=False
    )
    attempts_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    correct_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    accuracy: Mapped[float | None] = mapped_column(Float)
    last_practiced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (UniqueConstraint("course_id", "topic_id", name="uq_topic_mastery"),)
