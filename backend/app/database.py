import os

from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.orm import declarative_base, sessionmaker

from app.config import settings

DATABASE_URL = settings.DATABASE_URL
IS_SQLITE = DATABASE_URL.startswith("sqlite")

if IS_SQLITE:
    db_path = DATABASE_URL.replace("sqlite:///", "", 1)
    directory = os.path.dirname(os.path.abspath(db_path))
    os.makedirs(directory, exist_ok=True)

engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False} if IS_SQLITE else {},
    pool_pre_ping=True,
)

if IS_SQLITE:
    @event.listens_for(engine, "connect")
    def _set_sqlite_pragmas(dbapi_connection, _connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA busy_timeout=5000")
        cursor.close()


SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


# Lightweight, idempotent column migrations for the SQLite database.  This keeps
# existing installations working without losing any attendance/payroll data.
_COLUMN_MIGRATIONS = {
    "employees": {
        "alternate_phone": "VARCHAR(30)",
        "date_of_birth": "DATE",
        "emergency_contact_name": "VARCHAR(100)",
        "emergency_contact_phone": "VARCHAR(30)",
        "emergency_contact_relationship": "VARCHAR(50)",
        "address": "TEXT",
        "location_id": "INTEGER",
    },
    "users": {
        "profile_completed": "BOOLEAN DEFAULT 0 NOT NULL",
    },
    "shifts": {
        "shift_type": "VARCHAR(20) DEFAULT 'fixed'",
        "target_hours": "FLOAT",
        "break_minutes": "INTEGER DEFAULT 0",
        "rotation_group": "VARCHAR(50)",
    },
    "punch_logs": {
        "verify_mode": "VARCHAR(30)",
        "device_serial": "VARCHAR(100)",
    },
    "devices": {
        "serial_number": "VARCHAR(100)",
        "location_id": "INTEGER",
    },
}


def run_migrations() -> None:
    """Add new columns to an existing database without recreating tables."""
    inspector = inspect(engine)
    added_profile_column = False

    for table, columns in _COLUMN_MIGRATIONS.items():
        existing = {column["name"] for column in inspector.get_columns(table)}
        for name, definition in columns.items():
            if name in existing:
                continue
            with engine.begin() as connection:
                connection.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {definition}"))
            existing.add(name)
            if table == "users" and name == "profile_completed":
                added_profile_column = True

    if added_profile_column:
        # Accounts that existed before onboarding was introduced are already
        # considered complete.  Newly created employee-linked accounts start at 0.
        with engine.begin() as connection:
            connection.execute(text(
                "UPDATE users SET profile_completed = 1 "
                "WHERE profile_completed IS NULL OR profile_completed = 0"
            ))
    elif "profile_completed" in _COLUMN_MIGRATIONS["users"]:
        with engine.begin() as connection:
            connection.execute(text(
                "UPDATE users SET profile_completed = 1 WHERE profile_completed IS NULL"
            ))


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
