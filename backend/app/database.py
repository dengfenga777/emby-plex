from __future__ import annotations

from collections.abc import Generator

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker


class Base(DeclarativeBase):
    pass


engine: Engine | None = None
SessionLocal: sessionmaker[Session] | None = None


def configure_database(database_url: str) -> None:
    global engine, SessionLocal

    connect_args = {"check_same_thread": False} if database_url.startswith("sqlite") else {}
    engine = create_engine(database_url, connect_args=connect_args)
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


def init_database() -> None:
    if engine is None:
        raise RuntimeError("Database engine is not configured.")
    Base.metadata.create_all(bind=engine)
    apply_schema_patches()


def get_db() -> Generator[Session, None, None]:
    if SessionLocal is None:
        raise RuntimeError("Session factory is not configured.")

    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


def apply_schema_patches() -> None:
    if engine is None:
        raise RuntimeError("Database engine is not configured.")

    inspector = inspect(engine)
    if "requests" not in inspector.get_table_names():
        return

    request_columns = {column["name"] for column in inspector.get_columns("requests")}
    statements: list[str] = []

    if "notification_chat_id" not in request_columns:
        statements.append("ALTER TABLE requests ADD COLUMN notification_chat_id BIGINT")
    if "notification_message_id" not in request_columns:
        statements.append("ALTER TABLE requests ADD COLUMN notification_message_id INTEGER")
    if "notification_message_thread_id" not in request_columns:
        statements.append("ALTER TABLE requests ADD COLUMN notification_message_thread_id INTEGER")
    if "finished_notified_at" not in request_columns:
        statements.append("ALTER TABLE requests ADD COLUMN finished_notified_at DATETIME")
    if "requester_finished_notified_at" not in request_columns:
        statements.append("ALTER TABLE requests ADD COLUMN requester_finished_notified_at DATETIME")
    if "chat_finished_notified_at" not in request_columns:
        statements.append("ALTER TABLE requests ADD COLUMN chat_finished_notified_at DATETIME")
    if "public_id" not in request_columns:
        statements.append("ALTER TABLE requests ADD COLUMN public_id INTEGER")

    with engine.begin() as connection:
        for statement in statements:
            connection.execute(text(statement))

        connection.execute(
            text("CREATE TABLE IF NOT EXISTS request_sequences (id INTEGER PRIMARY KEY AUTOINCREMENT)")
        )

        pending_request_ids = connection.execute(
            text(
                """
                SELECT id
                FROM requests
                WHERE public_id IS NULL
                ORDER BY created_at ASC, id ASC
                """
            )
        ).scalars()
        for request_id in pending_request_ids:
            next_public_id = connection.execute(text("INSERT INTO request_sequences DEFAULT VALUES")).lastrowid
            connection.execute(
                text("UPDATE requests SET public_id = :public_id WHERE id = :request_id"),
                {"public_id": next_public_id, "request_id": request_id},
            )

        max_request_public_id = connection.execute(
            text("SELECT COALESCE(MAX(public_id), 0) FROM requests")
        ).scalar_one()
        max_sequence_id = connection.execute(
            text("SELECT COALESCE(MAX(id), 0) FROM request_sequences")
        ).scalar_one()

        for _ in range(max(0, int(max_request_public_id) - int(max_sequence_id))):
            connection.execute(text("INSERT INTO request_sequences DEFAULT VALUES"))

        connection.execute(
            text("CREATE UNIQUE INDEX IF NOT EXISTS ix_requests_public_id ON requests (public_id)")
        )
