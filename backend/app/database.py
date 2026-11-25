import json
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
        "nominee_name": "VARCHAR(100)",
        "nominee_relationship": "VARCHAR(50)",
        "location_id": "INTEGER",
        "shift_group_id": "INTEGER",
        "identity_key": "VARCHAR(64)",
    },
    "users": {
        "profile_completed": "BOOLEAN DEFAULT 0 NOT NULL",
        "identity_key": "VARCHAR(64)",
    },
    "shifts": {
        "shift_type": "VARCHAR(20) DEFAULT 'fixed'",
        "target_hours": "FLOAT",
        "break_minutes": "INTEGER DEFAULT 0",
        "rotation_group": "VARCHAR(50)",
        "shift_group_id": "INTEGER",
    },
    "punch_logs": {
        "verify_mode": "VARCHAR(30)",
        "device_serial": "VARCHAR(100)",
    },
    "devices": {
        "serial_number": "VARCHAR(100)",
        "location_id": "INTEGER",
    },
    "device_sync_jobs": {
        "full_history": "BOOLEAN DEFAULT 0",
    },
}


def _migrate_identity_reservations() -> None:
    """Make employee codes, device UIDs and user links permanent identities."""
    statements = [
        "UPDATE employees SET identity_key = lower(hex(randomblob(16))) "
        "WHERE identity_key IS NULL OR identity_key = ''",
        "UPDATE users SET identity_key = lower(hex(randomblob(16))) "
        "WHERE identity_key IS NULL OR identity_key = ''",
        """
        CREATE TABLE IF NOT EXISTS identifier_reservations (
            id INTEGER PRIMARY KEY,
            kind VARCHAR(40) NOT NULL,
            value VARCHAR(100) NOT NULL,
            owner_key VARCHAR(64) NOT NULL,
            employee_id INTEGER,
            user_id INTEGER,
            created_at DATETIME NOT NULL,
            CONSTRAINT uq_identifier_reservation UNIQUE (kind, value)
        )
        """,
        "CREATE INDEX IF NOT EXISTS ix_identifier_reservations_owner "
        "ON identifier_reservations (owner_key)",
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_employees_identity_key "
        "ON employees (identity_key)",
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_users_identity_key "
        "ON users (identity_key)",
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_users_employee_id "
        "ON users (employee_id) WHERE employee_id IS NOT NULL",
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_employees_employee_code_ci "
        "ON employees (lower(trim(employee_code)))",
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_employees_device_user_id_ci "
        "ON employees (lower(trim(device_user_id))) "
        "WHERE device_user_id IS NOT NULL AND trim(device_user_id) <> ''",
        """
        INSERT OR IGNORE INTO identifier_reservations
            (kind, value, owner_key, employee_id, created_at)
        SELECT 'employee_code', lower(trim(employee_code)), identity_key,
               id, datetime('now')
        FROM employees
        WHERE employee_code IS NOT NULL AND trim(employee_code) <> ''
          AND identity_key IS NOT NULL AND identity_key <> ''
        """,
        """
        INSERT OR IGNORE INTO identifier_reservations
            (kind, value, owner_key, employee_id, created_at)
        SELECT 'device_user_id', lower(trim(device_user_id)), identity_key,
               id, datetime('now')
        FROM employees
        WHERE device_user_id IS NOT NULL AND trim(device_user_id) <> ''
          AND identity_key IS NOT NULL AND identity_key <> ''
        """,
        """
        INSERT OR IGNORE INTO identifier_reservations
            (kind, value, owner_key, employee_id, user_id, created_at)
        SELECT 'user_employee', e.identity_key, u.identity_key,
               e.id, u.id, datetime('now')
        FROM users u JOIN employees e ON e.id = u.employee_id
        WHERE u.employee_id IS NOT NULL
          AND e.identity_key IS NOT NULL AND e.identity_key <> ''
          AND u.identity_key IS NOT NULL AND u.identity_key <> ''
        """,
    ]
    with engine.begin() as connection:
        for statement in statements:
            connection.execute(text(statement))


def _grant_document_permissions() -> None:
    """Give existing installs the new employee-document permissions."""
    grants = {
        "admin": {"document.view", "document.manage", "document.hr"},
        "hr manager": {"document.view", "document.manage", "document.hr"},
        "employee": {"document.view"},
    }
    with engine.begin() as connection:
        rows = connection.execute(text("SELECT id, name, permissions FROM roles")).fetchall()
        for row in rows:
            wanted = grants.get((row.name or "").strip().casefold())
            if not wanted:
                continue
            try:
                permissions = json.loads(row.permissions or "[]")
            except (TypeError, ValueError):
                permissions = []
            updated = list(permissions)
            for code in sorted(wanted):
                if code not in updated:
                    updated.append(code)
            if updated != permissions:
                connection.execute(
                    text("UPDATE roles SET permissions = :permissions WHERE id = :id"),
                    {"permissions": json.dumps(updated), "id": row.id},
                )


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

    _migrate_identity_reservations()
    _grant_document_permissions()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
