from fastapi import APIRouter

from app.api.transactions import transactional_route
from ..models.database import SafeSession
from app.db.session import begin_writer
from app.db.schema import initialize_schema, NOTES_TABLE

from app.services import safe_log
router = APIRouter()


@router.post("/use-dev-db")
@transactional_route
async def use_dev_db():
    safe_log.log_event("INFO", "dev.database_switched", database="test")
    SafeSession.use_memory_db()

    with begin_writer() as connection:
        initialize_schema(connection.raw_connection)
        connection.execute(f"DELETE FROM {NOTES_TABLE}", ())
        safe_log.log_event("INFO", "dev.notes_cleared")

    return {"status": "ok"}


@router.post("/use-file-db")
@transactional_route
async def use_file_db():
    safe_log.log_event("INFO", "dev.database_switched", database="file")
    SafeSession.use_file_db()
    return {"status": "ok"}
