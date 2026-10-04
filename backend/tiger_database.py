"""Tiger Data storage for live time-series readings and immutable incident evidence."""

from __future__ import annotations

from typing import Optional

from backend.schemas import Event, Reading


class TigerDatabase:
    storage = "tiger_data"

    def __init__(self, url: str) -> None:
        # Import only when Tiger is selected; SQLite remains usable without the driver.
        from psycopg_pool import ConnectionPool

        self.pool = ConnectionPool(url, min_size=1, max_size=4, open=False)

    def initialize(self) -> None:
        self.pool.open(wait=True)
        with self.pool.connection() as connection:
            connection.execute("CREATE EXTENSION IF NOT EXISTS timescaledb")
            connection.execute(
                """CREATE TABLE IF NOT EXISTS readings (
                    timestamp TIMESTAMPTZ NOT NULL,
                    node_id TEXT NOT NULL,
                    water_level_cm DOUBLE PRECISION NOT NULL,
                    quality DOUBLE PRECISION NOT NULL,
                    source TEXT NOT NULL
                ) WITH (tsdb.hypertable)"""
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_readings_node_time ON readings(node_id, timestamp DESC)"
            )
            connection.execute(
                """CREATE TABLE IF NOT EXISTS events (
                    event_id TEXT PRIMARY KEY,
                    detected_at TIMESTAMPTZ NOT NULL,
                    payload JSONB NOT NULL
                )"""
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_events_time ON events(detected_at DESC)"
            )
            connection.execute(
                """CREATE TABLE IF NOT EXISTS event_readings (
                    event_id TEXT NOT NULL REFERENCES events(event_id) ON DELETE CASCADE,
                    node_id TEXT NOT NULL,
                    timestamp TIMESTAMPTZ NOT NULL,
                    payload JSONB NOT NULL
                )"""
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_event_readings_event_time ON event_readings(event_id, timestamp)"
            )
            # Fail at startup if a plain PostgreSQL table was supplied instead.
            row = connection.execute(
                "SELECT 1 FROM timescaledb_information.hypertables WHERE hypertable_name = 'readings'"
            ).fetchone()
            if row is None:
                raise RuntimeError("Tiger Data readings table is not a hypertable")

    def close(self) -> None:
        self.pool.close()

    def save_reading(self, reading: Reading) -> None:
        with self.pool.connection() as connection:
            connection.execute(
                "INSERT INTO readings(timestamp, node_id, water_level_cm, quality, source) VALUES (%s, %s, %s, %s, %s)",
                (reading.timestamp, reading.node_id, reading.water_level_cm, reading.quality, reading.source.value),
            )

    def save_event(self, event: Event) -> None:
        self.save_event_with_readings(event, [])

    def save_event_with_readings(self, event: Event, readings: list[Reading]) -> None:
        # The event and the exact detector input window commit together.
        with self.pool.connection() as connection:
            connection.execute(
                """INSERT INTO events(event_id, detected_at, payload) VALUES (%s, %s, %s::jsonb)
                ON CONFLICT (event_id) DO UPDATE SET detected_at = EXCLUDED.detected_at, payload = EXCLUDED.payload""",
                (event.event_id, event.detected_at, event.model_dump_json()),
            )
            connection.execute("DELETE FROM event_readings WHERE event_id = %s", (event.event_id,))
            with connection.cursor() as cursor:
                cursor.executemany(
                    "INSERT INTO event_readings(event_id, node_id, timestamp, payload) VALUES (%s, %s, %s, %s::jsonb)",
                    [
                        (event.event_id, reading.node_id, reading.timestamp, reading.model_dump_json())
                        for reading in readings
                    ],
                )

    def event_readings(self, event_id: str) -> list[Reading]:
        with self.pool.connection() as connection:
            rows = connection.execute(
                "SELECT payload FROM event_readings WHERE event_id = %s ORDER BY timestamp, node_id",
                (event_id,),
            ).fetchall()
        return [Reading.model_validate(row[0]) for row in rows]

    def latest_readings(self, limit: int = 100) -> list[Reading]:
        with self.pool.connection() as connection:
            rows = connection.execute(
                """SELECT node_id, timestamp, water_level_cm, quality, source
                FROM readings ORDER BY timestamp DESC LIMIT %s""",
                (limit,),
            ).fetchall()
        return [
            Reading(node_id=row[0], timestamp=row[1], water_level_cm=row[2], quality=row[3], source=row[4])
            for row in rows
        ]

    def events(self, limit: int = 50) -> list[Event]:
        with self.pool.connection() as connection:
            rows = connection.execute(
                "SELECT payload FROM events ORDER BY detected_at DESC LIMIT %s", (limit,)
            ).fetchall()
        return [Event.model_validate(row[0]) for row in rows]

    def event(self, event_id: str) -> Optional[Event]:
        with self.pool.connection() as connection:
            row = connection.execute(
                "SELECT payload FROM events WHERE event_id = %s", (event_id,)
            ).fetchone()
        return Event.model_validate(row[0]) if row else None
