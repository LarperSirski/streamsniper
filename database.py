"""SQLite access. Existing channel and history tables are retained unchanged."""
import sqlite3
from config import DB_PATH


def connect():
    connection = sqlite3.connect(DB_PATH, timeout=30)
    connection.execute("PRAGMA journal_mode=WAL")
    return connection


def initialize():
    with connect() as con:
        con.execute("""CREATE TABLE IF NOT EXISTS channels (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            url TEXT UNIQUE NOT NULL,
            label TEXT NOT NULL,
            enabled INTEGER NOT NULL DEFAULT 1,
            auto_record INTEGER NOT NULL DEFAULT 1
        )""")
        channel_columns = {row[1] for row in con.execute("PRAGMA table_info(channels)")}
        if "auto_record" not in channel_columns:
            con.execute(
                "ALTER TABLE channels ADD COLUMN auto_record INTEGER NOT NULL DEFAULT 1"
            )
        con.execute("""CREATE TABLE IF NOT EXISTS seen (
            video_id TEXT PRIMARY KEY,
            channel_url TEXT,
            title TEXT,
            kind TEXT
        )""")


def list_channels():
    with connect() as con:
        return con.execute(
            "SELECT id, url, label, enabled, auto_record FROM channels ORDER BY label COLLATE NOCASE"
        ).fetchall()


def add_channel(url: str, label: str):
    with connect() as con:
        con.execute(
            "INSERT INTO channels(url, label, enabled) VALUES (?, ?, 1)",
            (url, label),
        )


def remove_channel(channel_id: int):
    with connect() as con:
        con.execute("DELETE FROM channels WHERE id=?", (channel_id,))


def toggle_channel(channel_id: int):
    with connect() as con:
        con.execute("UPDATE channels SET enabled=1-enabled WHERE id=?", (channel_id,))


def set_channel_auto_record(channel_id: int, enabled: bool):
    with connect() as con:
        con.execute(
            "UPDATE channels SET auto_record=? WHERE id=?",
            (int(enabled), channel_id),
        )


def dashboard_counts():
    with connect() as con:
        total = con.execute("SELECT COUNT(*) FROM channels").fetchone()[0]
        enabled = con.execute("SELECT COUNT(*) FROM channels WHERE enabled=1").fetchone()[0]
        uploads = con.execute("SELECT COUNT(*) FROM seen WHERE kind='upload'").fetchone()[0]
    return total, enabled, uploads


def mark_seen(video_id: str, channel_url: str, title: str, kind: str) -> bool:
    with connect() as con:
        cursor = con.execute(
            "INSERT OR IGNORE INTO seen(video_id, channel_url, title, kind) VALUES (?, ?, ?, ?)",
            (video_id, channel_url, title, kind),
        )
        return cursor.rowcount == 1
