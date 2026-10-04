from backend.config import settings
from backend.database import Database
from backend.tiger_database import TigerDatabase
from backend.realtime import ConnectionManager
from backend.serial_bridge import SerialBridge
from backend.services.event_service import EventService

database = TigerDatabase(settings.tiger_database_url) if settings.tiger_database_url else Database(settings.database_path)
# Remote storage gets batched background writes; local SQLite stays synchronous.
event_service = EventService(database, batch_writes=database.storage == "tiger_data")
connections = ConnectionManager()
serial_bridge = SerialBridge(
    settings.serial_port,
    settings.serial_baud_rate,
    settings.reference_distance_cm,
    event_service,
    connections,
)
