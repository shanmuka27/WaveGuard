import asyncio
import queue
from datetime import datetime, timedelta, timezone
from math import pi, sin

from backend.database import Database
from backend.schemas import Reading, ReadingSource, Severity
from backend.serial_bridge import SerialBridge
from backend.services.event_service import EventService


class FakeConnections:
    def __init__(self):
        self.messages = []

    async def broadcast(self, payload):
        self.messages.append(payload)


class FakeSerial:
    def __init__(self):
        self.writes = []

    def write(self, data):
        self.writes.append(data)
        return len(data)

    def close(self):
        pass


def test_serial_loop_opens_port_and_stops_cleanly(tmp_path):
    class StreamingSerial(FakeSerial):
        def __init__(self):
            super().__init__()
            self.incoming = queue.Queue()
            self.closed = False

        def readline(self):
            try:
                return self.incoming.get(timeout=0.05)
            except queue.Empty:
                return b""

        def close(self):
            self.closed = True

    async def check():
        database = Database(str(tmp_path / "loop.db"))
        database.initialize()
        service = EventService(database)
        connections = FakeConnections()
        serial = StreamingSerial()
        opened = []

        def factory(port, baud_rate):
            opened.append((port, baud_rate))
            return serial

        bridge = SerialBridge(
            "fake-port", 115200, 20.0, service, connections, serial_factory=factory
        )
        task = asyncio.create_task(bridge.run())
        try:
            serial.incoming.put(b"READING,1790985600,6.0,0.98\n")
            async def received():
                while not connections.messages:
                    await asyncio.sleep(0.01)

            await asyncio.wait_for(received(), timeout=1)
            assert opened == [("fake-port", 115200)]
            assert serial.writes == [b"STATE,SAFE\n"]
            assert connections.messages[0]["reading"]["source"] == "physical"
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        assert serial.closed

    asyncio.run(check())


def test_serial_reading_enters_detector_and_emits_alert_state(tmp_path):
    async def check():
        database = Database(str(tmp_path / "bridge.db"))
        database.initialize()
        service = EventService(database)
        connections = FakeConnections()
        bridge = SerialBridge("fake", 115200, 20.0, service, connections)
        serial = FakeSerial()
        bridge._connection = serial

        for index, level in enumerate((14.0, 14.2, 14.4, 15.8, 17.2, 18.6)):
            distance = 20.0 - level
            await bridge.process_line(
                f"READING,{1790985600 + index},{distance},0.98\n".encode("ascii")
            )

        assert len(database.latest_readings()) == 6
        assert connections.messages[-1]["reading"]["source"] == "physical"
        assert connections.messages[-1]["event"]["severity"] == "watch"
        assert serial.writes == [b"STATE,SAFE\n", b"STATE,WATCH\n"]

    asyncio.run(check())


def test_correlated_warning_and_reset_reach_arduino(tmp_path):
    async def check():
        database = Database(str(tmp_path / "alerts.db"))
        database.initialize()
        service = EventService(database)
        bridge = SerialBridge("fake", 115200, 20.0, service, FakeConnections())
        serial = FakeSerial()
        bridge._connection = serial
        start = datetime(2026, 10, 3, tzinfo=timezone.utc)

        for step in range(12):
            for index, node_id in enumerate(("LUDINGTON-01", "MUSKEGON-02", "HOLLAND-03")):
                service.ingest(
                    Reading(
                        node_id=node_id,
                        timestamp=start + timedelta(seconds=step),
                        water_level_cm=14 + index * 0.3 + 3.5 * sin(step * pi / 3),
                        quality=0.98,
                        source=ReadingSource.SIMULATED,
                    ),
                    detect=False,
                )
        service.detect_event()
        assert service.overall_severity() == Severity.WARNING
        await bridge.send_state(service.overall_severity())

        service.reset_live_state()
        await bridge.send_state(service.overall_severity())
        assert serial.writes == [b"STATE,WARNING\n", b"STATE,SAFE\n"]

    asyncio.run(check())


def test_physical_reading_replaces_simulated_signal_window(tmp_path):
    async def check():
        database = Database(str(tmp_path / "source-change.db"))
        database.initialize()
        service = EventService(database)
        start = datetime(2026, 10, 3, tzinfo=timezone.utc)
        for step in range(12):
            service.ingest(
                Reading(
                    node_id="LUDINGTON-01",
                    timestamp=start + timedelta(seconds=step),
                    water_level_cm=14 + 3.5 * sin(step * pi / 3),
                    quality=0.98,
                    source=ReadingSource.SIMULATED,
                )
            )
        bridge = SerialBridge("fake", 115200, 20.0, service, FakeConnections())
        await bridge.process_line(b"READING,1790985600,6.0,0.98\n")
        assert len(service.histories["LUDINGTON-01"]) == 1
        assert service.nodes()[0].source == ReadingSource.PHYSICAL
        assert service.nodes()[0].severity == Severity.SAFE

    asyncio.run(check())
