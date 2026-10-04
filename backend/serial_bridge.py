"""Connect the physical Arduino to the detector and alert state."""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Callable, Optional

from backend.serial_reader import parse_reading_line, state_command
from backend.services.event_service import EventService
from backend.schemas import EventClassification, Severity

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
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.port = port
        self.baud_rate = baud_rate
        self.reference_distance_cm = reference_distance_cm
        self.event_service = event_service
        self.connections = connections
        self.node_id = node_id
        self.serial_factory = serial_factory
        self.clock = clock
        self._connection: Optional[Any] = None
        self._last_sent: Optional[str] = None  # last STATE command written
        # Location whose status the LEDs show; None = whole network. Each shoreline
        # site has its own board, so by default it shows its own node.
        self.board_node: Optional[str] = node_id
        self._time_sent = False
        # True while a demo scenario plays the physical station's data; the live
        # sensor only feeds the detector in manual mode.
        self._physical_paused = False
        self._write_lock = asyncio.Lock()

    def holding(self) -> bool:
        """True while a demo scenario, not the live sensor, drives the physical station."""
        return self._physical_paused

    def pause_physical(self, paused: bool) -> None:
        self._physical_paused = paused

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
                self._time_sent = False
                logger.info("Arduino connected on %s", self.port)
                await self.sync_state()

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
                self._time_sent = False
                if connection is not None:
                    try:
                        connection.close()
                    except Exception as error:
                        logger.warning("Could not close Arduino port: %s", error)

    async def process_line(self, raw: bytes) -> None:
        if self._physical_paused:
            return
        reading = parse_reading_line(
            raw.decode("ascii"), self.node_id, self.reference_distance_cm
        )
        received_at = datetime.fromtimestamp(self.clock(), tz=timezone.utc)
        if abs((received_at - reading.timestamp).total_seconds()) > 30:
            reading = reading.model_copy(update={"timestamp": received_at})
        await self.send_time()
        event = self.event_service.ingest(reading)
        await self.connections.broadcast(
            {
                "type": "reading",
                "reading": reading.model_dump(mode="json"),
                "event": event.model_dump(mode="json") if event else None,
            }
        )
        await self.sync_state()

    async def sync_state(self) -> None:
        """Show the board location's current alert on the LEDs."""
        severity, classification = self.event_service.alert_for(self.board_node)
        await self.send_state(severity, classification)

    async def set_board_node(self, node_id: Optional[str]) -> None:
        self.board_node = node_id
        await self.sync_state()

    async def send_time(self) -> None:
        async with self._write_lock:
            connection = self._connection
            if connection is None or self._time_sent:
                return
            try:
                command = f"TIME,{int(self.clock())}\n".encode("ascii")
                await asyncio.to_thread(connection.write, command)
                self._time_sent = True
            except (OSError, ValueError) as error:
                logger.warning("Could not sync Arduino clock: %s", error)
                try:
                    connection.close()
                except Exception as close_error:
                    logger.warning("Could not close Arduino port: %s", close_error)

    async def send_state(
        self, severity: Severity, classification: Optional[EventClassification] = None
    ) -> None:
        async with self._write_lock:
            connection = self._connection
            command = state_command(severity, classification)
            if connection is None or command == self._last_sent:
                return
            try:
                await asyncio.to_thread(connection.write, command.encode("ascii"))
                self._last_sent = command
            except (OSError, ValueError) as error:
                logger.warning("Could not send Arduino state: %s", error)
                self._last_sent = None
                try:
                    connection.close()
                except Exception as close_error:
                    logger.warning("Could not close Arduino port: %s", close_error)
