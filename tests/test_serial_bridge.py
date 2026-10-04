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
            "fake-port", 115200, 20.0, service, connections,
            serial_factory=factory, clock=lambda: 1790985600,
        )
        task = asyncio.create_task(bridge.run())
        try:
            serial.incoming.put(b"READING,1790985600,6.0,0.98\n")
            async def received():
                while not connections.messages:
                    await asyncio.sleep(0.01)

            await asyncio.wait_for(received(), timeout=1)
            assert opened == [("fake-port", 115200)]
            assert serial.writes == [b"STATE,SAFE\n", b"TIME,1790985600\n"]
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
        bridge = SerialBridge(
            "fake", 115200, 20.0, service, connections,
            clock=lambda: 1790985600,
        )
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
        assert serial.writes == [
            b"TIME,1790985600\n", b"STATE,SAFE\n", b"STATE,WATCH\n"
        ]

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
        await bridge.sync_state()

        service.reset_live_state()
        await bridge.sync_state()
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


def test_unsynced_arduino_time_uses_server_receive_time(tmp_path):
    async def check():
        database = Database(str(tmp_path / "clock.db"))
        database.initialize()
        service = EventService(database)
        serial = FakeSerial()
        bridge = SerialBridge(
            "fake", 115200, 20.0, service, FakeConnections(),
            clock=lambda: 1791046800,
        )
        bridge._connection = serial
        await bridge.process_line(b"READING,1791043200,6.0,0.95\n")

        assert database.latest_readings()[0].timestamp.timestamp() == 1791046800
        assert serial.writes == [b"TIME,1791046800\n", b"STATE,SAFE\n"]

    asyncio.run(check())


def test_warning_demo_holds_physical_ingestion_then_resumes(tmp_path):
    async def check():
        database = Database(str(tmp_path / "hold.db"))
        database.initialize()
        service = EventService(database)
        connections = FakeConnections()
        bridge = SerialBridge(
            "fake", 115200, 20.0, service, connections,
            clock=lambda: 1791043200,
        )
        bridge._connection = FakeSerial()
        bridge.pause_physical(True)
        await bridge.process_line(b"READING,1791043200,6.0,0.95\n")
        assert database.latest_readings() == []
        assert connections.messages == []

        bridge.pause_physical(False)
        await bridge.process_line(b"READING,1791043201,6.0,0.95\n")
        assert len(database.latest_readings()) == 1
        assert connections.messages[0]["reading"]["source"] == "physical"

    asyncio.run(check())


def test_physical_readings_pause_only_outside_manual_mode(tmp_path):
    database = Database(str(tmp_path / "pause.db"))
    database.initialize()
    bridge = SerialBridge("fake", 115200, 20.0, EventService(database), FakeConnections())

    assert not bridge.holding()  # starts in manual: the live sensor feeds the detector
    bridge.pause_physical(True)
    assert bridge.holding()
    bridge.pause_physical(False)
    assert not bridge.holding()


def test_surge_warning_sends_surge_then_seiche_sends_warning(tmp_path):
    from backend.schemas import Event

    async def check():
        database = Database(str(tmp_path / "surge.db"))
        database.initialize()
        service = EventService(database)
        bridge = SerialBridge("fake", 115200, 20.0, service, FakeConnections())
        serial = FakeSerial()
        bridge._connection = serial

        def event(classification):
            return Event(
                event_id=f"evt-{classification}", classification=classification,
                severity="warning", confidence=0.9,
                affected_nodes=["LUDINGTON-01", "MUSKEGON-02", "HOLLAND-03"],
                amplitude_cm=8.0, correlation_score=0.9,
            )

        service.current_event = event("sudden_surge")
        await bridge.sync_state()
        await bridge.sync_state()  # unchanged: not resent
        service.current_event = event("seiche_like")
        await bridge.sync_state()

        assert serial.writes == [b"STATE,SURGE\n", b"STATE,WARNING\n"]

    asyncio.run(check())


def test_board_shows_its_own_location_not_the_whole_network(tmp_path):
    from backend.schemas import Event

    async def check():
        database = Database(str(tmp_path / "board.db"))
        database.initialize()
        service = EventService(database)
        bridge = SerialBridge("fake", 115200, 20.0, service, FakeConnections())
        serial = FakeSerial()
        bridge._connection = serial
        service.current_event = Event(
            event_id="evt-holland-surge", classification="sudden_surge", severity="warning",
            confidence=0.9, affected_nodes=["HOLLAND-03", "GRANDHAVEN-04", "SOUTHHAVEN-05"],
            amplitude_cm=8.0, correlation_score=1.0,
        )

        await bridge.sync_state()                     # Ludington's board: not in the event
        await bridge.set_board_node("HOLLAND-03")     # switch the board to Holland
        await bridge.set_board_node("LUDINGTON-01")   # and back
        await bridge.set_board_node(None)             # whole network

        assert serial.writes == [
            b"STATE,SAFE\n", b"STATE,SURGE\n", b"STATE,SAFE\n", b"STATE,SURGE\n"
        ]

    asyncio.run(check())
