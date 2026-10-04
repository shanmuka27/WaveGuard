from backend.config import settings
from backend.database import Database
from backend.realtime import ConnectionManager
from backend.serial_bridge import SerialBridge
from backend.services.event_service import EventService

database = Database(settings.database_path)
event_service = EventService(database)
connections = ConnectionManager()
serial_bridge = SerialBridge(
    settings.serial_port,
    settings.serial_baud_rate,
    settings.reference_distance_cm,
    event_service,
    connections,
)
