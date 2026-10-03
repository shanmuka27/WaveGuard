from backend.config import settings
from backend.database import Database
from backend.realtime import ConnectionManager
from backend.services.event_service import EventService

database = Database(settings.database_path)
event_service = EventService(database)
connections = ConnectionManager()
