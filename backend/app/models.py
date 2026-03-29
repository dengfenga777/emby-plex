from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import BigInteger, DateTime, Enum, ForeignKey, Integer, String, Text, event, insert
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base
from .enums import MediaType, RequestStatus, UserRole


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    tg_user_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True)
    username: Mapped[str | None] = mapped_column(String(64), nullable=True)
    nickname: Mapped[str] = mapped_column(String(128))
    role: Mapped[UserRole] = mapped_column(Enum(UserRole), default=UserRole.user, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)

    requests: Mapped[list["Request"]] = relationship(back_populates="user")


class Request(Base):
    __tablename__ = "requests"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    public_id: Mapped[int | None] = mapped_column(Integer, unique=True, index=True, nullable=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True, nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    media_type: Mapped[MediaType] = mapped_column(Enum(MediaType), nullable=False)
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    source_id: Mapped[str] = mapped_column(String(128), nullable=False)
    overview: Mapped[str | None] = mapped_column(Text, nullable=True)
    poster_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[RequestStatus] = mapped_column(
        Enum(RequestStatus),
        default=RequestStatus.pending,
        nullable=False,
        index=True,
    )
    moviepilot_task_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    admin_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    notification_chat_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    notification_message_thread_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_notified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    user: Mapped[User] = relationship(back_populates="requests")
    logs: Mapped[list["RequestLog"]] = relationship(
        back_populates="request",
        cascade="all, delete-orphan",
        order_by=lambda: RequestLog.created_at.desc(),
    )


class RequestSequence(Base):
    __tablename__ = "request_sequences"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)


class RequestLog(Base):
    __tablename__ = "request_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    request_id: Mapped[str] = mapped_column(ForeignKey("requests.id"), index=True, nullable=False)
    from_status: Mapped[RequestStatus | None] = mapped_column(Enum(RequestStatus), nullable=True)
    to_status: Mapped[RequestStatus] = mapped_column(Enum(RequestStatus), nullable=False)
    operator: Mapped[str] = mapped_column(String(64), nullable=False)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)

    request: Mapped[Request] = relationship(back_populates="logs")


@event.listens_for(Request, "before_insert")
def assign_request_public_id(mapper, connection, target: Request) -> None:  # noqa: ANN001
    del mapper

    if not target.id:
        target.id = str(uuid.uuid4())

    if target.public_id is not None:
        return

    result = connection.execute(insert(RequestSequence))
    target.public_id = int(result.inserted_primary_key[0])
