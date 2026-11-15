import hashlib
import hmac
import json
import os
import re
import secrets
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Iterator


DEFAULT_DATABASE_PATH = Path(__file__).resolve().parents[1] / ".nexus.sqlite3"
PASSWORD_SCRYPT_N = 2**14
PASSWORD_SCRYPT_R = 8
PASSWORD_SCRYPT_P = 1
SESSION_LIFETIME = timedelta(days=14)
PROPOSAL_LIFETIME = timedelta(hours=24)
EVENT_DURATION_MINUTES = 15
MAX_EVENT_DURATION_MINUTES = 24 * 60
SERIES_HORIZON_DAYS = 365


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _database_path() -> Path:
    return Path(os.getenv("NEXUS_DATABASE_PATH", str(DEFAULT_DATABASE_PATH)))


def _files_root() -> Path:
    return Path(
        os.getenv(
            "NEXUS_FILES_PATH",
            str(DEFAULT_DATABASE_PATH.parent / ".nexus-files"),
        )
    )


def user_files_directory(user_id: str) -> Path:
    """Return the private on-disk directory for one authenticated user."""

    directory = _files_root() / user_id
    directory.mkdir(parents=True, exist_ok=True)
    return directory


@contextmanager
def connection() -> Iterator[sqlite3.Connection]:
    path = _database_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    database = sqlite3.connect(path, timeout=10)
    try:
        database.row_factory = sqlite3.Row
        database.execute("PRAGMA foreign_keys = ON")
        database.execute("PRAGMA busy_timeout = 10000")
        _initialize_schema(database)
        yield database
        database.commit()
    except Exception:
        database.rollback()
        raise
    finally:
        database.close()


def _initialize_schema(database: sqlite3.Connection) -> None:
    database.executescript(
        """
        CREATE TABLE IF NOT EXISTS users (
            id TEXT PRIMARY KEY,
            email TEXT NOT NULL UNIQUE,
            display_name TEXT NOT NULL,
            password_hash TEXT NOT NULL,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS sessions (
            token_hash TEXT PRIMARY KEY,
            user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            expires_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS sessions_user_idx ON sessions(user_id);

        CREATE TABLE IF NOT EXISTS event_series (
            id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            title TEXT NOT NULL,
            start_date TEXT NOT NULL,
            time TEXT NOT NULL,
            duration_minutes INTEGER NOT NULL,
            type TEXT NOT NULL CHECK (type IN ('appointment', 'reminder')),
            notes TEXT NOT NULL DEFAULT '',
            frequency TEXT NOT NULL
                CHECK (frequency IN ('daily', 'weekly', 'monthly', 'yearly')),
            recurrence_interval INTEGER NOT NULL,
            weekdays TEXT NOT NULL DEFAULT '[]',
            end_date TEXT,
            generation_through TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS event_series_user_idx ON event_series(user_id);

        CREATE TABLE IF NOT EXISTS events (
            id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            title TEXT NOT NULL,
            date TEXT NOT NULL,
            time TEXT NOT NULL,
            type TEXT NOT NULL CHECK (type IN ('appointment', 'reminder')),
            notes TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            duration_minutes INTEGER NOT NULL DEFAULT 15,
            completed INTEGER NOT NULL DEFAULT 0,
            series_id TEXT REFERENCES event_series(id) ON DELETE CASCADE,
            occurrence_date TEXT,
            is_exception INTEGER NOT NULL DEFAULT 0
        );
        CREATE INDEX IF NOT EXISTS events_user_date_time_idx
            ON events(user_id, date, time);

        CREATE TABLE IF NOT EXISTS pending_calendar_actions (
            id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            payload TEXT NOT NULL,
            conflict_ids TEXT NOT NULL,
            created_at TEXT NOT NULL,
            expires_at TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending'
                CHECK (status IN ('pending', 'resolved', 'rejected', 'expired'))
        );
        CREATE INDEX IF NOT EXISTS pending_actions_user_idx
            ON pending_calendar_actions(user_id, status, expires_at);

        CREATE TABLE IF NOT EXISTS documents (
            id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            original_filename TEXT NOT NULL,
            stored_filename TEXT NOT NULL,
            content_type TEXT NOT NULL,
            size_bytes INTEGER NOT NULL,
            sha256 TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS documents_user_created_idx
            ON documents(user_id, created_at DESC);

        CREATE TABLE IF NOT EXISTS document_chunks (
            id TEXT PRIMARY KEY,
            document_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
            user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            chunk_index INTEGER NOT NULL,
            content TEXT NOT NULL,
            embedding TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS document_chunks_user_idx
            ON document_chunks(user_id, document_id);
        """
    )
    event_columns = {
        row["name"]
        for row in database.execute("PRAGMA table_info(events)").fetchall()
    }
    if "duration_minutes" not in event_columns:
        database.execute(
            "ALTER TABLE events ADD COLUMN duration_minutes INTEGER NOT NULL DEFAULT 15"
        )
    if "series_id" not in event_columns:
        database.execute(
            "ALTER TABLE events ADD COLUMN series_id TEXT REFERENCES event_series(id) ON DELETE CASCADE"
        )
    if "occurrence_date" not in event_columns:
        database.execute("ALTER TABLE events ADD COLUMN occurrence_date TEXT")
    if "is_exception" not in event_columns:
        database.execute(
            "ALTER TABLE events ADD COLUMN is_exception INTEGER NOT NULL DEFAULT 0"
        )
    if "completed" not in event_columns:
        database.execute(
            "ALTER TABLE events ADD COLUMN completed INTEGER NOT NULL DEFAULT 0"
        )
    database.execute(
        "CREATE INDEX IF NOT EXISTS events_series_idx ON events(series_id, occurrence_date)"
    )
    database.execute(
        """CREATE UNIQUE INDEX IF NOT EXISTS events_series_occurrence_idx
           ON events(series_id, occurrence_date) WHERE series_id IS NOT NULL"""
    )


def create_document(
    user_id: str,
    original_filename: str,
    stored_filename: str,
    content_type: str,
    size_bytes: int,
    sha256: str,
    chunks: list[tuple[str, list[float]]],
) -> dict[str, object]:
    document_id = str(uuid.uuid4())
    created_at = _now().isoformat()
    with connection() as database:
        database.execute(
            """INSERT INTO documents
               (id, user_id, original_filename, stored_filename, content_type,
                size_bytes, sha256, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                document_id,
                user_id,
                original_filename,
                stored_filename,
                content_type,
                size_bytes,
                sha256,
                created_at,
            ),
        )
        database.executemany(
            """INSERT INTO document_chunks
               (id, document_id, user_id, chunk_index, content, embedding, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            [
                (
                    str(uuid.uuid4()),
                    document_id,
                    user_id,
                    index,
                    content,
                    json.dumps(embedding),
                    created_at,
                )
                for index, (content, embedding) in enumerate(chunks)
            ],
        )
    return {
        "id": document_id,
        "user_id": user_id,
        "name": original_filename,
        "content_type": content_type,
        "size_bytes": size_bytes,
        "created_at": created_at,
    }


def list_documents(user_id: str) -> list[dict[str, object]]:
    with connection() as database:
        rows = database.execute(
            """SELECT d.id, d.original_filename, d.content_type, d.size_bytes,
                      d.created_at, COUNT(c.id) AS chunk_count
               FROM documents d
               LEFT JOIN document_chunks c ON c.document_id = d.id
               WHERE d.user_id = ?
               GROUP BY d.id
               ORDER BY d.created_at DESC""",
            (user_id,),
        ).fetchall()
    return [
        {
            "id": row["id"],
            "name": row["original_filename"],
            "content_type": row["content_type"],
            "size_bytes": row["size_bytes"],
            "created_at": row["created_at"],
            "chunk_count": row["chunk_count"],
        }
        for row in rows
    ]


def document_exists(user_id: str) -> bool:
    with connection() as database:
        row = database.execute(
            "SELECT 1 FROM documents WHERE user_id = ? LIMIT 1",
            (user_id,),
        ).fetchone()
    return row is not None


def search_document_chunks(
    user_id: str,
    query_embedding: list[float],
    top_k: int = 5,
) -> list[dict[str, object]]:
    with connection() as database:
        rows = database.execute(
            """SELECT c.id, c.document_id, c.content, c.embedding,
                      d.original_filename
               FROM document_chunks c
               JOIN documents d ON d.id = c.document_id
               WHERE c.user_id = ?""",
            (user_id,),
        ).fetchall()

    def cosine(left: list[float], right: list[float]) -> float:
        if not left or len(left) != len(right):
            return 0.0
        dot = sum(a * b for a, b in zip(left, right))
        left_norm = sum(value * value for value in left) ** 0.5
        right_norm = sum(value * value for value in right) ** 0.5
        if not left_norm or not right_norm:
            return 0.0
        return dot / (left_norm * right_norm)

    matches = [
        {
            "id": row["id"],
            "document_id": row["document_id"],
            "name": row["original_filename"],
            "content": row["content"],
            "score": cosine(query_embedding, json.loads(row["embedding"])),
        }
        for row in rows
    ]
    matches.sort(key=lambda item: item["score"], reverse=True)
    return matches[:top_k]


def delete_document(user_id: str, document_id: str) -> dict[str, object] | None:
    with connection() as database:
        row = database.execute(
            """SELECT original_filename, stored_filename
               FROM documents WHERE id = ? AND user_id = ?""",
            (document_id, user_id),
        ).fetchone()
        if not row:
            return None
        database.execute(
            "DELETE FROM documents WHERE id = ? AND user_id = ?",
            (document_id, user_id),
        )
    path = user_files_directory(user_id) / row["stored_filename"]
    if path.exists():
        path.unlink()
    return {"id": document_id, "name": row["original_filename"]}


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(
        password.encode("utf-8"),
        salt=salt,
        n=PASSWORD_SCRYPT_N,
        r=PASSWORD_SCRYPT_R,
        p=PASSWORD_SCRYPT_P,
        dklen=32,
    )
    return f"scrypt${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored_hash: str) -> bool:
    try:
        scheme, salt_hex, digest_hex = stored_hash.split("$")
        if scheme != "scrypt":
            return False
        salt = bytes.fromhex(salt_hex)
        expected_digest = bytes.fromhex(digest_hex)
    except (ValueError, TypeError):
        return False
    if len(salt) != 16 or len(expected_digest) != 32:
        return False

    actual_digest = hashlib.scrypt(
        password.encode("utf-8"),
        salt=salt,
        n=PASSWORD_SCRYPT_N,
        r=PASSWORD_SCRYPT_R,
        p=PASSWORD_SCRYPT_P,
        dklen=len(expected_digest),
    )
    return hmac.compare_digest(actual_digest, expected_digest)


def create_user(email: str, display_name: str, password: str) -> dict[str, str]:
    user = {
        "id": str(uuid.uuid4()),
        "email": email,
        "display_name": display_name,
        "password_hash": hash_password(password),
        "created_at": _now().isoformat(),
    }
    with connection() as database:
        database.execute(
            """INSERT INTO users (id, email, display_name, password_hash, created_at)
               VALUES (:id, :email, :display_name, :password_hash, :created_at)""",
            user,
        )
    return {key: user[key] for key in ("id", "email", "display_name")}


def get_user_by_email(email: str) -> dict[str, str] | None:
    with connection() as database:
        row = database.execute(
            "SELECT id, email, display_name, password_hash FROM users WHERE email = ?",
            (email,),
        ).fetchone()
    return dict(row) if row else None


def create_session(user_id: str) -> str:
    token = secrets.token_urlsafe(32)
    expires_at = (_now() + SESSION_LIFETIME).isoformat()
    with connection() as database:
        database.execute(
            "INSERT INTO sessions (token_hash, user_id, expires_at) VALUES (?, ?, ?)",
            (hashlib.sha256(token.encode("utf-8")).hexdigest(), user_id, expires_at),
        )
        database.execute("DELETE FROM sessions WHERE expires_at <= ?", (_now().isoformat(),))
    return token


def get_user_for_session(token: str) -> dict[str, str] | None:
    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    with connection() as database:
        row = database.execute(
            """SELECT users.id, users.email, users.display_name
               FROM sessions
               JOIN users ON users.id = sessions.user_id
               WHERE sessions.token_hash = ? AND sessions.expires_at > ?""",
            (token_hash, _now().isoformat()),
        ).fetchone()
    return dict(row) if row else None


def delete_session(token: str) -> None:
    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    with connection() as database:
        database.execute("DELETE FROM sessions WHERE token_hash = ?", (token_hash,))


def _event_from_row(row: sqlite3.Row) -> dict[str, object]:
    event = {
        key: row[key]
        for key in (
            "id",
            "title",
            "date",
            "time",
            "type",
            "notes",
            "duration_minutes",
            "completed",
            "series_id",
            "occurrence_date",
            "series_start_date",
        )
    }
    event["recurrence"] = (
        {
            "frequency": row["frequency"],
            "interval": row["recurrence_interval"],
            "weekdays": json.loads(row["weekdays"]),
        }
        if row["series_id"]
        else None
    )
    return event


def _occurs_on(day: date, series: dict[str, object]) -> bool:
    start = date.fromisoformat(str(series["start_date"]))
    if day < start:
        return False
    frequency = str(series["frequency"])
    interval = int(series["recurrence_interval"])
    if frequency == "daily":
        return (day - start).days % interval == 0
    if frequency == "weekly":
        start_week = start - timedelta(days=start.weekday())
        day_week = day - timedelta(days=day.weekday())
        week_index = (day_week - start_week).days // 7
        weekdays = json.loads(str(series["weekdays"]))
        return week_index % interval == 0 and day.weekday() in weekdays
    if frequency == "monthly":
        month_index = (day.year - start.year) * 12 + day.month - start.month
        return month_index % interval == 0 and day.day == start.day
    year_index = day.year - start.year
    return year_index % interval == 0 and (day.month, day.day) == (start.month, start.day)


def _extend_recurring_events(
    database: sqlite3.Connection,
    user_id: str,
    requested_through: str | None = None,
) -> None:
    horizon = max(
        date.today() + timedelta(days=SERIES_HORIZON_DAYS),
        date.fromisoformat(requested_through) if requested_through else date.min,
    )
    series_rows = database.execute(
        "SELECT * FROM event_series WHERE user_id = ?",
        (user_id,),
    ).fetchall()
    for row in series_rows:
        series = dict(row)
        cursor = date.fromisoformat(series["generation_through"])
        start = date.fromisoformat(series["start_date"])
        through = horizon
        if series["end_date"]:
            through = min(through, date.fromisoformat(series["end_date"]))
        if through <= cursor:
            continue
        day = max(start, cursor + timedelta(days=1))
        while day <= through:
            if _occurs_on(day, series):
                database.execute(
                    """INSERT OR IGNORE INTO events
                       (id, user_id, title, date, time, type, notes, created_at,
                        duration_minutes, series_id, occurrence_date, is_exception)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0)""",
                    (
                        str(uuid.uuid4()),
                        user_id,
                        series["title"],
                        day.isoformat(),
                        series["time"],
                        series["type"],
                        series["notes"],
                        _now().isoformat(),
                        series["duration_minutes"],
                        series["id"],
                        day.isoformat(),
                    ),
                )
            day += timedelta(days=1)
        database.execute(
            "UPDATE event_series SET generation_through = ? WHERE id = ?",
            (through.isoformat(), series["id"]),
        )


def _select_events(
    database: sqlite3.Connection,
    user_id: str,
    date_from: str | None = None,
    date_to: str | None = None,
) -> list[dict[str, object]]:
    conditions = ["e.user_id = ?"]
    values: list[str] = [user_id]
    if date_from:
        conditions.append("e.date >= ?")
        values.append(date_from)
    if date_to:
        conditions.append("e.date <= ?")
        values.append(date_to)
    rows = database.execute(
        f"""SELECT e.id, e.title, e.date, e.time, e.type, e.notes,
                   e.duration_minutes, e.completed, e.series_id, e.occurrence_date,
                   s.start_date AS series_start_date,
                   s.frequency, s.recurrence_interval, s.weekdays
            FROM events e LEFT JOIN event_series s ON s.id = e.series_id
            WHERE {' AND '.join(conditions)}
            ORDER BY e.date, e.time, e.title""",
        values,
    ).fetchall()
    return [_event_from_row(row) for row in rows]


def list_events(
    user_id: str,
    date_from: str | None = None,
    date_to: str | None = None,
) -> list[dict[str, object]]:
    with connection() as database:
        _extend_recurring_events(database, user_id, date_to)
        return _select_events(database, user_id, date_from, date_to)


def get_event(user_id: str, event_id: str) -> dict[str, object] | None:
    with connection() as database:
        row = database.execute(
            """SELECT e.id, e.title, e.date, e.time, e.type, e.notes,
                      e.duration_minutes, e.completed, e.series_id, e.occurrence_date,
                      s.start_date AS series_start_date,
                      s.frequency, s.recurrence_interval, s.weekdays
               FROM events e LEFT JOIN event_series s ON s.id = e.series_id
               WHERE e.user_id = ? AND e.id = ?""",
            (user_id, event_id),
        ).fetchone()
    return _event_from_row(row) if row else None


def delete_event(user_id: str, event_id: str, scope: str = "this_occurrence") -> bool:
    with connection() as database:
        database.execute("BEGIN IMMEDIATE")
        row = database.execute(
            """SELECT id, series_id, occurrence_date
               FROM events WHERE user_id = ? AND id = ?""",
            (user_id, event_id),
        ).fetchone()
        if not row:
            return False
        if not row["series_id"] or scope == "this_occurrence":
            database.execute("DELETE FROM events WHERE id = ?", (event_id,))
        elif scope == "series":
            database.execute(
                "DELETE FROM event_series WHERE user_id = ? AND id = ?",
                (user_id, row["series_id"]),
            )
        elif scope == "following":
            series = database.execute(
                "SELECT start_date FROM event_series WHERE id = ? AND user_id = ?",
                (row["series_id"], user_id),
            ).fetchone()
            occurrence_date = date.fromisoformat(row["occurrence_date"])
            start_date = date.fromisoformat(series["start_date"])
            if occurrence_date <= start_date:
                database.execute(
                    "DELETE FROM event_series WHERE user_id = ? AND id = ?",
                    (user_id, row["series_id"]),
                )
            else:
                end_date = (occurrence_date - timedelta(days=1)).isoformat()
                database.execute(
                    """UPDATE event_series
                       SET end_date = ?, generation_through = MIN(generation_through, ?)
                       WHERE id = ? AND user_id = ?""",
                    (end_date, end_date, row["series_id"], user_id),
                )
                database.execute(
                    """DELETE FROM events
                       WHERE series_id = ? AND occurrence_date >= ?""",
                    (row["series_id"], occurrence_date.isoformat()),
                )
        else:
            raise ValueError("Unsupported recurring event scope.")
    return True


def set_event_completed(
    user_id: str,
    event_id: str,
    completed: bool,
) -> dict[str, object] | None:
    with connection() as database:
        database.execute(
            "UPDATE events SET completed = ? WHERE user_id = ? AND id = ?",
            (int(completed), user_id, event_id),
        )
        row = database.execute(
            """SELECT e.id, e.title, e.date, e.time, e.type, e.notes,
                      e.duration_minutes, e.completed, e.series_id, e.occurrence_date,
                      s.start_date AS series_start_date,
                      s.frequency, s.recurrence_interval, s.weekdays
               FROM events e LEFT JOIN event_series s ON s.id = e.series_id
               WHERE e.user_id = ? AND e.id = ?""",
            (user_id, event_id),
        ).fetchone()
    return _event_from_row(row) if row else None


def _event_start(event: dict[str, object]) -> datetime:
    return datetime.combine(
        date.fromisoformat(str(event["date"])),
        time.fromisoformat(str(event["time"])),
    )


def _event_overlaps(first: dict[str, object], second: dict[str, object]) -> bool:
    first_start = _event_start(first)
    second_start = _event_start(second)
    first_end = first_start + timedelta(minutes=int(first["duration_minutes"]))
    second_end = second_start + timedelta(minutes=int(second["duration_minutes"]))
    return first_start < second_end and second_start < first_end


def _event_fields(event: dict[str, object]) -> dict[str, object]:
    return {
        "title": event["title"],
        "date": event["date"],
        "time": event["time"],
        "type": event["type"],
        "notes": event.get("notes", ""),
        "duration_minutes": event.get("duration_minutes", EVENT_DURATION_MINUTES),
        "completed": int(bool(event.get("completed", False))),
    }


def _insert_event(
    database: sqlite3.Connection,
    user_id: str,
    event: dict[str, object],
    *,
    series_id: str | None = None,
    occurrence_date: str | None = None,
    is_exception: bool = False,
) -> dict[str, object]:
    saved = {
        **_event_fields(event),
        "id": str(uuid.uuid4()),
        "user_id": user_id,
        "created_at": _now().isoformat(),
        "series_id": series_id,
        "occurrence_date": occurrence_date,
        "is_exception": int(is_exception),
    }
    database.execute(
        """INSERT INTO events
           (id, user_id, title, date, time, type, notes, created_at,
            duration_minutes, completed, series_id, occurrence_date, is_exception)
           VALUES (:id, :user_id, :title, :date, :time, :type, :notes, :created_at,
                   :duration_minutes, :completed, :series_id, :occurrence_date,
                   :is_exception)""",
        saved,
    )
    return {key: saved[key] for key in (
        "id", "title", "date", "time", "type", "notes", "duration_minutes", "completed",
        "series_id", "occurrence_date",
    )}


def _update_event(
    database: sqlite3.Connection,
    user_id: str,
    event_id: str,
    event: dict[str, object],
) -> dict[str, object]:
    row = database.execute(
        "SELECT series_id, occurrence_date FROM events WHERE user_id = ? AND id = ?",
        (user_id, event_id),
    ).fetchone()
    if not row:
        raise ValueError("Event not found.")
    database.execute(
        """UPDATE events
           SET title = ?, date = ?, time = ?, type = ?, notes = ?,
               duration_minutes = ?, is_exception = ?
           WHERE user_id = ? AND id = ?""",
        (
            event["title"],
            event["date"],
            event["time"],
            event["type"],
            event["notes"],
            event["duration_minutes"],
            int(bool(row["series_id"])),
            user_id,
            event_id,
        ),
    )
    return {
        "id": event_id,
        **_event_fields(event),
        "series_id": row["series_id"],
        "occurrence_date": row["occurrence_date"],
    }


def _build_series(
    event: dict[str, object],
    recurrence: dict[str, object],
    series_id: str | None = None,
) -> dict[str, object]:
    start = date.fromisoformat(str(event["date"]))
    frequency = str(recurrence["frequency"])
    weekdays = sorted(set(int(day) for day in recurrence.get("weekdays", [])))
    if frequency == "weekly" and not weekdays:
        weekdays = [start.weekday()]
    if frequency != "weekly":
        weekdays = []
    return {
        "id": series_id or str(uuid.uuid4()),
        **_event_fields(event),
        "start_date": start.isoformat(),
        "frequency": frequency,
        "recurrence_interval": int(recurrence.get("interval", 1)),
        "weekdays": json.dumps(weekdays),
        "end_date": None,
        "generation_through": (start - timedelta(days=1)).isoformat(),
        "created_at": _now().isoformat(),
    }


def _generate_series_events(
    series: dict[str, object],
    through: date,
) -> list[dict[str, object]]:
    start = date.fromisoformat(str(series["start_date"]))
    result: list[dict[str, object]] = []
    current = start
    while current <= through:
        if _occurs_on(current, series):
            result.append(
                {
                    "title": series["title"],
                    "date": current.isoformat(),
                    "time": series["time"],
                    "type": series["type"],
                    "notes": series["notes"],
                    "duration_minutes": series["duration_minutes"],
                    "series_id": series["id"],
                    "occurrence_date": current.isoformat(),
                }
            )
        current += timedelta(days=1)
    return result


def _create_series_operation(
    event: dict[str, object],
    recurrence: dict[str, object],
    series_id: str | None = None,
) -> dict[str, object]:
    series = _build_series(event, recurrence, series_id)
    start = date.fromisoformat(str(series["start_date"]))
    through = max(
        date.today() + timedelta(days=SERIES_HORIZON_DAYS),
        start + timedelta(days=SERIES_HORIZON_DAYS),
    )
    series["generation_through"] = through.isoformat()
    return {
        "kind": "create_series" if series_id is None else "update_series",
        "series": series,
        "occurrences": _generate_series_events(series, through),
        "exclude": {"ids": [], "all_series": [], "series_from": []},
    }


def _is_excluded(
    event: dict[str, object],
    excluded: dict[str, object],
) -> bool:
    if event["id"] in excluded.get("ids", []):
        return True
    if event["series_id"] in excluded.get("all_series", []):
        return True
    return any(
        event["series_id"] == item["id"]
        and event["occurrence_date"]
        and event["occurrence_date"] >= item["date"]
        for item in excluded.get("series_from", [])
    )


def _find_conflicts(
    database: sqlite3.Connection,
    user_id: str,
    occurrences: list[dict[str, object]],
    excluded: dict[str, object],
) -> list[dict[str, object]]:
    existing = _select_events(database, user_id)
    conflicts: dict[str, dict[str, object]] = {}
    for proposed in occurrences:
        for event in existing:
            if not _is_excluded(event, excluded) and _event_overlaps(proposed, event):
                conflicts[str(event["id"])] = event
    return sorted(
        conflicts.values(),
        key=lambda event: (str(event["date"]), str(event["time"]), str(event["title"])),
    )


def _operation_occurrences(operation: dict[str, object]) -> list[dict[str, object]]:
    return operation.get("occurrences") or [operation["event"]]


def _create_proposal(
    database: sqlite3.Connection,
    user_id: str,
    operation: dict[str, object],
    conflicts: list[dict[str, object]],
) -> dict[str, object]:
    proposal_id = str(uuid.uuid4())
    created_at = _now()
    event = _operation_occurrences(operation)[0]
    database.execute(
        """INSERT INTO pending_calendar_actions
           (id, user_id, payload, conflict_ids, created_at, expires_at)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (
            proposal_id,
            user_id,
            json.dumps({"operation": operation}),
            json.dumps([item["id"] for item in conflicts]),
            created_at.isoformat(),
            (created_at + PROPOSAL_LIFETIME).isoformat(),
        ),
    )
    return {
        "status": "conflict",
        "proposal_id": proposal_id,
        "event": event,
        "conflicts": conflicts[:10],
        "conflict_count": len(conflicts),
        "occurrence_count": len(_operation_occurrences(operation)),
    }


def _store_series(database: sqlite3.Connection, user_id: str, series: dict[str, object]) -> None:
    values = {
        key: series[key]
        for key in (
            "id", "title", "start_date", "time", "duration_minutes", "type",
            "notes", "frequency", "recurrence_interval", "weekdays", "end_date",
            "generation_through", "created_at",
        )
    }
    database.execute(
        """INSERT INTO event_series
           (id, user_id, title, start_date, time, duration_minutes, type, notes,
            frequency, recurrence_interval, weekdays, end_date, generation_through, created_at)
           VALUES (:id, :user_id, :title, :start_date, :time, :duration_minutes,
                   :type, :notes, :frequency, :recurrence_interval, :weekdays,
                   :end_date, :generation_through, :created_at)""",
        {"user_id": user_id, **values},
    )


def _apply_operation(
    database: sqlite3.Connection,
    user_id: str,
    operation: dict[str, object],
) -> dict[str, object]:
    kind = operation["kind"]
    if kind == "create_event":
        return _insert_event(database, user_id, operation["event"])
    if kind == "update_event":
        return _update_event(database, user_id, operation["target_id"], operation["event"])

    series = operation["series"]
    if kind == "update_series":
        database.execute(
            "DELETE FROM events WHERE user_id = ? AND series_id = ?",
            (user_id, series["id"]),
        )
        database.execute(
            """UPDATE event_series
               SET title = ?, start_date = ?, time = ?, duration_minutes = ?,
                   type = ?, notes = ?, frequency = ?, recurrence_interval = ?,
                   weekdays = ?, end_date = NULL, generation_through = ?
               WHERE user_id = ? AND id = ?""",
            (
                series["title"], series["start_date"], series["time"],
                series["duration_minutes"], series["type"], series["notes"],
                series["frequency"], series["recurrence_interval"], series["weekdays"],
                series["generation_through"], user_id, series["id"],
            ),
        )
    elif kind == "split_series":
        cutoff = operation["cutoff"]
        end_date = (date.fromisoformat(cutoff) - timedelta(days=1)).isoformat()
        database.execute(
            """UPDATE event_series
               SET end_date = ?, generation_through = MIN(generation_through, ?)
               WHERE user_id = ? AND id = ?""",
            (end_date, end_date, user_id, operation["old_series_id"]),
        )
        database.execute(
            """DELETE FROM events
               WHERE user_id = ? AND series_id = ? AND occurrence_date >= ?""",
            (user_id, operation["old_series_id"], cutoff),
        )
        _store_series(database, user_id, series)
    elif kind == "create_series":
        _store_series(database, user_id, series)
    else:
        raise ValueError("Unsupported calendar operation.")

    first_saved: dict[str, object] | None = None
    for occurrence in operation["occurrences"]:
        saved = _insert_event(
            database,
            user_id,
            occurrence,
            series_id=str(series["id"]),
            occurrence_date=str(occurrence["occurrence_date"]),
        )
        if first_saved is None:
            first_saved = saved
    if not first_saved:
        raise ValueError("A recurring series must contain at least one occurrence.")
    first_saved["recurrence"] = {
        "frequency": series["frequency"],
        "interval": series["recurrence_interval"],
        "weekdays": json.loads(str(series["weekdays"])),
    }
    return first_saved


def create_or_propose_event(
    user_id: str,
    event: dict[str, object],
    target_id: str | None = None,
    scope: str = "this_occurrence",
) -> dict[str, object]:
    with connection() as database:
        database.execute("BEGIN IMMEDIATE")
        target = None
        if target_id:
            target = database.execute(
                """SELECT id, series_id, occurrence_date, date
                   FROM events WHERE user_id = ? AND id = ?""",
                (user_id, target_id),
            ).fetchone()
            if not target:
                return {"status": "not_found"}

        recurrence = event.get("recurrence")
        if not target_id and recurrence:
            operation = _create_series_operation(event, recurrence)
        elif target_id and recurrence and not target["series_id"]:
            operation = _create_series_operation(event, recurrence)
            operation["kind"] = "replace_series"
            operation["exclude"] = {"ids": [target_id], "all_series": [], "series_from": []}
        elif target_id and target["series_id"] and scope in {"series", "following"}:
            existing_series = database.execute(
                """SELECT frequency, recurrence_interval, weekdays
                   FROM event_series WHERE user_id = ? AND id = ?""",
                (user_id, target["series_id"]),
            ).fetchone()
            if not existing_series:
                return {"status": "not_found"}
            if not recurrence:
                recurrence = {
                    "frequency": existing_series["frequency"],
                    "interval": existing_series["recurrence_interval"],
                    "weekdays": json.loads(existing_series["weekdays"]),
                }
            operation = _create_series_operation(
                event,
                recurrence or {},
                target["series_id"] if scope == "series" else None,
            )
            if scope == "series":
                operation["exclude"]["all_series"] = [target["series_id"]]
            else:
                cutoff = target["occurrence_date"]
                operation["kind"] = "split_series"
                operation["old_series_id"] = target["series_id"]
                operation["cutoff"] = cutoff
                operation["exclude"]["series_from"] = [
                    {"id": target["series_id"], "date": cutoff}
                ]
        else:
            if target_id and not target["series_id"] and scope != "this_occurrence":
                return {"status": "invalid_scope"}
            if target_id and target["series_id"] and scope != "this_occurrence":
                return {"status": "not_found"}
            operation = {
                "kind": "update_event" if target_id else "create_event",
                "event": _event_fields(event),
                "target_id": target_id,
                "exclude": {
                    "ids": [target_id] if target_id else [],
                    "all_series": [],
                    "series_from": [],
                },
            }

        if operation["kind"] == "replace_series":
            operation["exclude"]["ids"] = [target_id]
            operation["kind"] = "create_series"
            operation["replace_id"] = target_id
        occurrences = _operation_occurrences(operation)
        conflicts = _find_conflicts(
            database,
            user_id,
            occurrences,
            operation["exclude"],
        )
        if conflicts:
            return _create_proposal(database, user_id, operation, conflicts)
        if operation.get("replace_id"):
            database.execute(
                "DELETE FROM events WHERE user_id = ? AND id = ?",
                (user_id, operation["replace_id"]),
            )
        saved = _apply_operation(database, user_id, operation)
        return {
            "status": "saved",
            "event": saved,
            "occurrence_count": len(occurrences),
        }


def resolve_calendar_action(
    user_id: str,
    proposal_id: str,
    resolution: str,
) -> dict[str, object]:
    if resolution not in {"override", "overlap", "reject"}:
        raise ValueError("Unsupported conflict resolution.")

    with connection() as database:
        database.execute("BEGIN IMMEDIATE")
        proposal = database.execute(
            """SELECT payload, conflict_ids, expires_at, status
               FROM pending_calendar_actions WHERE id = ? AND user_id = ?""",
            (proposal_id, user_id),
        ).fetchone()
        if not proposal:
            return {"status": "not_found"}
        if proposal["status"] != "pending":
            return {"status": "already_resolved"}
        if proposal["expires_at"] <= _now().isoformat():
            database.execute(
                "UPDATE pending_calendar_actions SET status = 'expired' WHERE id = ?",
                (proposal_id,),
            )
            return {"status": "expired"}

        operation = json.loads(proposal["payload"])["operation"]
        if operation["kind"] == "update_event" and not database.execute(
            "SELECT 1 FROM events WHERE user_id = ? AND id = ?",
            (user_id, operation["target_id"]),
        ).fetchone():
            return {"status": "not_found"}
        required_series_id = (
            operation["series"]["id"]
            if operation["kind"] == "update_series"
            else operation.get("old_series_id")
        )
        if required_series_id and not database.execute(
            "SELECT 1 FROM event_series WHERE user_id = ? AND id = ?",
            (user_id, required_series_id),
        ).fetchone():
            return {"status": "not_found"}
        if operation.get("replace_id") and not database.execute(
            "SELECT 1 FROM events WHERE user_id = ? AND id = ?",
            (user_id, operation["replace_id"]),
        ).fetchone():
            return {"status": "not_found"}
        current_conflicts = _find_conflicts(
            database,
            user_id,
            _operation_occurrences(operation),
            operation["exclude"],
        )
        original_conflict_ids = set(json.loads(proposal["conflict_ids"]))
        new_conflicts = [
            item for item in current_conflicts if item["id"] not in original_conflict_ids
        ]
        if new_conflicts:
            stale = _create_proposal(database, user_id, operation, current_conflicts)
            database.execute(
                "UPDATE pending_calendar_actions SET status = 'expired' WHERE id = ?",
                (proposal_id,),
            )
            return stale

        if resolution == "reject":
            database.execute(
                "UPDATE pending_calendar_actions SET status = 'rejected' WHERE id = ?",
                (proposal_id,),
            )
            return {"status": "rejected"}

        if resolution == "override":
            for conflict in current_conflicts:
                database.execute(
                    "DELETE FROM events WHERE user_id = ? AND id = ?",
                    (user_id, conflict["id"]),
                )

        if operation.get("replace_id"):
            database.execute(
                "DELETE FROM events WHERE user_id = ? AND id = ?",
                (user_id, operation["replace_id"]),
            )
        saved = _apply_operation(database, user_id, operation)
        database.execute(
            "UPDATE pending_calendar_actions SET status = 'resolved' WHERE id = ?",
            (proposal_id,),
        )
        return {
            "status": "saved",
            "resolution": resolution,
            "event": saved,
            "occurrence_count": len(_operation_occurrences(operation)),
        }


def find_related_events(
    user_id: str,
    query: str,
    date_from: str | None = None,
    date_to: str | None = None,
) -> list[dict[str, str]]:
    tokens = {
        token
        for token in re.findall(r"[a-z0-9]+", query.casefold())
        if len(token) > 1
    }
    if not tokens:
        return []

    candidates = list_events(user_id, date_from, date_to)
    ranked: list[tuple[int, dict[str, str]]] = []
    for event in candidates:
        title = event["title"].casefold()
        notes = event["notes"].casefold()
        matched_title = sum(token in title for token in tokens)
        matched_notes = sum(token in notes for token in tokens)
        score = matched_title * 3 + matched_notes
        if score:
            ranked.append((score, event))
    ranked.sort(key=lambda item: (-item[0], item[1]["date"], item[1]["time"]))
    return [event for _, event in ranked[:5]]
