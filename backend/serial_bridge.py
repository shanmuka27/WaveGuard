"""Connect the physical Arduino to the detector and alert state."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any, Callable, Optional

from backend.serial_reader import parse_reading_line, state_command
from backend.services.event_service import EventService
from backend.schemas import Severity

if TYPE_CHECKING:
    from backend.realtime import ConnectionManager


logger = logging.getLogger(__name__)


def open_serial(port: str, baud_rate: int) -> Any:
    import serial

    return serial.Serial(port, baud_rate, timeout=1, write_timeout=1)


class SerialBridge:
    def __init__(
        self,
        port: str,
        baud_rate: int,
        reference_distance_cm: float,
        event_service: EventService,
        connections: ConnectionManager,
        node_id: str = "LUDINGTON-01",
        serial_factory: Callable[[str, int], Any] = open_serial,
    ) -> None:
        self.port = port
        self.baud_rate = baud_rate
        self.reference_distance_cm = reference_distance_cm
        self.event_service = event_service
        self.connections = connections
        self.node_id = node_id
        self.serial_factory = serial_factory
        self._connection: Optional[Any] = None
        self._last_sent: Optional[Severity] = None
        self._write_lock = asyncio.Lock()

    async def run(self) -> None:
        """Reconnect after an unplug or read failure until the app shuts down."""
        while True:
            connection = None
            try:
                connection = await asyncio.to_thread(
                    self.serial_factory, self.port, self.baud_rate
                )
                self._connection = connection
                self._last_sent = None
                logger.info("Arduino connected on %s", self.port)
                await self.send_state(self.event_service.overall_severity())

                while True:
                    raw = await asyncio.to_thread(connection.readline)
                    if not raw:
                        continue
                    try:
                        await self.process_line(raw)
                    except (UnicodeError, ValueError) as error:
                        logger.warning("Ignoring invalid Arduino reading: %s", error)
            except asyncio.CancelledError:
                raise
            except Exception as error:
                logger.warning("Arduino unavailable on %s: %s", self.port, error)
                await asyncio.sleep(2)
            finally:
                self._connection = None
                self._last_sent = None
                if connection is not None:
                    try:
                        connection.close()
                    except Exception as error:
                        logger.warning("Could not close Arduino port: %s", error)

    async def process_line(self, raw: bytes) -> None:
        reading = parse_reading_line(
            raw.decode("ascii"), self.node_id, self.reference_distance_cm
        )
        event = self.event_service.ingest(reading)
        await self.connections.broadcast(
            {
                "type": "reading",
                "reading": reading.model_dump(mode="json"),
                "event": event.model_dump(mode="json") if event else None,
            }
        )
        await self.send_state(self.event_service.overall_severity())

    async def send_state(self, severity: Severity) -> None:
        async with self._write_lock:
            connection = self._connection
            if connection is None or severity == self._last_sent:
                return
            try:
                await asyncio.to_thread(
                    connection.write, state_command(severity).encode("ascii")
                )
                self._last_sent = severity
            except (OSError, ValueError) as error:
                logger.warning("Could not send Arduino state: %s", error)
                self._last_sent = None
                try:
                    connection.close()
                except Exception as close_error:
                    logger.warning("Could not close Arduino port: %s", close_error)
