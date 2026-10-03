from backend.schemas import Severity
from backend.serial_reader import parse_reading_line, state_command


def test_parse_serial_reading_converts_distance_to_level() -> None:
    reading = parse_reading_line("READING,1791043200,7.5,0.9", "LUDINGTON-01", 20.0)
    assert reading.water_level_cm == 12.5
    assert reading.quality == 0.9


def test_warning_command_matches_hardware_contract() -> None:
    assert state_command(Severity.WARNING) == "STATE,WARNING\n"
