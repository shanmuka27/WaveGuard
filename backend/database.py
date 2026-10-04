from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Optional

from backend.schemas import Event, Reading


class Database:
    storage = "sqlite"

    def __init__(self, path: str) -> None:
        self.path = path

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        return connection

    def initialize(self) -> None:
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS readings (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    node_id TEXT NOT NULL,
                    timestamp TEXT NOT NULL,
                    payload TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_readings_node_time
                    ON readings(node_id, timestamp DESC);

                CREATE TABLE IF NOT EXISTS events (
                    event_id TEXT PRIMARY KEY,
                    detected_at TEXT NOT NULL,
                    payload TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_events_time
                    ON events(detected_at DESC);

                CREATE TABLE IF NOT EXISTS event_readings (
                    event_id TEXT NOT NULL,
                    node_id TEXT NOT NULL,
                    timestamp TEXT NOT NULL,
                    payload TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_event_readings_event_time
                    ON event_readings(event_id, timestamp);
                """
            )

    def save_reading(self, reading: Reading) -> None:
        with self.connect() as connection:
            connection.execute(
                "INSERT INTO readings(node_id, timestamp, payload) VALUES (?, ?, ?)",
                (reading.node_id, reading.timestamp.isoformat(), reading.model_dump_json()),
            )

    def save_readings(self, readings: list[Reading]) -> None:
        with self.connect() as connection:
            connection.executemany(
                "INSERT INTO readings(node_id, timestamp, payload) VALUES (?, ?, ?)",
                [(r.node_id, r.timestamp.isoformat(), r.model_dump_json()) for r in readings],
            )

    def save_event(self, event: Event) -> None:
        self.save_event_with_readings(event, [])

    def save_event_with_readings(self, event: Event, readings: list[Reading]) -> None:
        with self.connect() as connection:
            connection.execute(
                "INSERT OR REPLACE INTO events(event_id, detected_at, payload) VALUES (?, ?, ?)",
                (event.event_id, event.detected_at.isoformat(), event.model_dump_json()),
            )
            connection.execute("DELETE FROM event_readings WHERE event_id = ?", (event.event_id,))
            connection.executemany(
                "INSERT INTO event_readings(event_id, node_id, timestamp, payload) VALUES (?, ?, ?, ?)",
                [
                    (event.event_id, reading.node_id, reading.timestamp.isoformat(), reading.model_dump_json())
                    for reading in readings
                ],
            )

    def event_readings(self, event_id: str) -> list[Reading]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT payload FROM event_readings WHERE event_id = ? ORDER BY timestamp, node_id",
                (event_id,),
            ).fetchall()
        return [Reading.model_validate(json.loads(row["payload"])) for row in rows]

    def latest_readings(self, limit: int = 100) -> list[Reading]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT payload FROM readings ORDER BY timestamp DESC LIMIT ?", (limit,)
            ).fetchall()
        return [Reading.model_validate(json.loads(row["payload"])) for row in rows]

    def events(self, limit: int = 50) -> list[Event]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT payload FROM events ORDER BY detected_at DESC LIMIT ?", (limit,)
            ).fetchall()
        return [Event.model_validate(json.loads(row["payload"])) for row in rows]

    def event(self, event_id: str) -> Optional[Event]:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT payload FROM events WHERE event_id = ?", (event_id,)
            ).fetchone()
        return Event.model_validate(json.loads(row["payload"])) if row else None
