import json
import os
from datetime import date

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
    "shift_groups": {
        "designation_ids": "JSON DEFAULT '[]'",
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
    "leave_types": {
        "code": "VARCHAR(20)",
        "is_active": "BOOLEAN DEFAULT 1",
    },
    "leave_requests": {
        "manager_approved_by": "INTEGER",
        "manager_approved_at": "DATETIME",
        "hr_verified_by": "INTEGER",
        "hr_verified_at": "DATETIME",
        "verification_notes": "TEXT",
        "final_approved_by": "INTEGER",
        "final_approved_at": "DATETIME",
        "rejected_by": "INTEGER",
        "reject_reason": "TEXT",
        "decided_at": "DATETIME",
        "is_full_day": "BOOLEAN DEFAULT 1",
        "restricted_holiday_id": "INTEGER",
    },
    "comp_offs": {
        "source": "VARCHAR(30) DEFAULT 'manual'",
        "rule": "VARCHAR(80)",
        "extra_hours": "FLOAT DEFAULT 0",
        "extra_hours_balance": "FLOAT DEFAULT 0",
    },
    "payslips": {
        "lop_days": "FLOAT DEFAULT 0",
        "lop_amount": "FLOAT DEFAULT 0",
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


def _has_marker(key: str) -> bool:
    with engine.connect() as connection:
        return connection.execute(
            text("SELECT 1 FROM app_settings WHERE key = :key"), {"key": key}
        ).first() is not None


def _set_marker(key: str, value: str) -> None:
    with engine.begin() as connection:
        connection.execute(text(
            "INSERT INTO app_settings (key, value, updated_at) VALUES (:key, :value, datetime('now')) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = datetime('now')"
        ), {"key": key, "value": value})


def _create_leave_tables() -> None:
    """Create leave quota / restricted-holiday tables on existing installs."""
    statements = [
        """
        CREATE TABLE IF NOT EXISTS leave_quotas (
            id INTEGER PRIMARY KEY,
            scope VARCHAR(20) NOT NULL DEFAULT 'global',
            scope_value VARCHAR(50) NOT NULL DEFAULT 'ALL',
            employee_id INTEGER,
            leave_type_id INTEGER NOT NULL,
            year INTEGER NOT NULL,
            days FLOAT DEFAULT 0,
            updated_by INTEGER,
            updated_at DATETIME,
            CONSTRAINT uq_leave_quota_scope UNIQUE (scope, scope_value, leave_type_id, year),
            FOREIGN KEY(employee_id) REFERENCES employees(id) ON DELETE CASCADE,
            FOREIGN KEY(leave_type_id) REFERENCES leave_types(id) ON DELETE CASCADE,
            FOREIGN KEY(updated_by) REFERENCES users(id) ON DELETE SET NULL
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS restricted_holidays (
            id INTEGER PRIMARY KEY,
            year INTEGER NOT NULL,
            holiday_date DATE NOT NULL,
            name VARCHAR(150) NOT NULL,
            reason TEXT,
            is_active BOOLEAN DEFAULT 1,
            created_by INTEGER,
            created_at DATETIME,
            CONSTRAINT uq_restricted_holiday_date UNIQUE (holiday_date),
            FOREIGN KEY(created_by) REFERENCES users(id) ON DELETE SET NULL
        )
        """,
        "CREATE INDEX IF NOT EXISTS ix_restricted_holidays_year ON restricted_holidays (year)",
        """
        CREATE TABLE IF NOT EXISTS comp_off_accrual_states (
            employee_id INTEGER PRIMARY KEY,
            extra_hours_balance FLOAT DEFAULT 0,
            last_accrual_date DATE,
            updated_at DATETIME,
            FOREIGN KEY(employee_id) REFERENCES employees(id) ON DELETE CASCADE
        )
        """,
    ]
    with engine.begin() as connection:
        for statement in statements:
            connection.execute(text(statement))


def _seed_leave_defaults() -> None:
    """Seed stable leave codes and the statutory yearly quotas without touching requests."""
    key = "leave_workflow_defaults_v1"
    if _has_marker(key):
        return
    with engine.begin() as connection:
        for name, code in (
            ("Casual Leave", "CL"), ("Sick Leave", "SL"), ("Earned Leave", "EL"),
            ("Unpaid Leave", "LOP"), ("Loss of Pay", "LOP"),
        ):
            connection.execute(text(
                "UPDATE leave_types SET code = :code "
                "WHERE lower(trim(name)) = :name AND (code IS NULL OR trim(code) = '') "
                "AND NOT EXISTS (SELECT 1 FROM leave_types other WHERE other.code = :code)"
            ), {"code": code, "name": name.casefold()})

        for name, code, quota, paid, color in (
            ("Restricted Holiday", "RH", 2, 1, "#8b5cf6"),
            ("Loss of Pay", "LOP", 0, 0, "#ef4444"),
        ):
            connection.execute(text(
                "INSERT INTO leave_types (name, code, is_paid, max_days_per_year, color) "
                "SELECT :name, :code, :paid, :quota, :color "
                "WHERE NOT EXISTS (SELECT 1 FROM leave_types "
                "WHERE code = :code OR lower(trim(name)) = lower(:name))"
            ), {"name": name, "code": code, "paid": paid, "quota": quota, "color": color})

        connection.execute(text(
            "UPDATE leave_types SET max_days_per_year = 18 "
            "WHERE code = 'EL' OR lower(trim(name)) = 'earned leave'"
        ))

        year = date.today().year
        for code, quota in (("CL", 12), ("EL", 18), ("RH", 2), ("LOP", 0)):
            row = connection.execute(
                text("SELECT id FROM leave_types WHERE code = :code"), {"code": code}
            ).first()
            if not row:
                continue
            connection.execute(text(
                "INSERT INTO leave_quotas (scope, scope_value, leave_type_id, year, days, updated_at) "
                "VALUES ('global', 'ALL', :leave_type_id, :year, :days, datetime('now')) "
                "ON CONFLICT(scope, scope_value, leave_type_id, year) DO NOTHING"
            ), {"leave_type_id": row.id, "year": year, "days": quota})
    _set_marker(key, date.today().isoformat())


def _retire_sick_leave() -> None:
    """Take Sick Leave out of the active catalogue, keeping historical rows intact."""
    key = "sick_leave_retired_v1"
    if _has_marker(key):
        return
    with engine.begin() as connection:
        connection.execute(text("UPDATE leave_types SET is_active = 1 WHERE is_active IS NULL"))
        connection.execute(text(
            "UPDATE leave_types SET is_active = 0 "
            "WHERE code = 'SL' OR lower(trim(name)) = 'sick leave'"
        ))
        connection.execute(text(
            "DELETE FROM leave_quotas WHERE leave_type_id IN "
            "(SELECT id FROM leave_types WHERE code = 'SL' OR lower(trim(name)) = 'sick leave')"
        ))
    _set_marker(key, date.today().isoformat())


def _grant_leave_permissions() -> None:
    """Give existing installs the staged leave workflow permissions."""
    all_codes = {
        "leave.manager_approve", "leave.verify", "leave.final_approve",
        "leave.quota.manage",
    }
    grants = {
        "admin": all_codes,
        "hr manager": {"leave.verify", "leave.quota.manage"},
        "manager": {"leave.manager_approve"},
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


def _link_demo_manager() -> None:
    key = "leave_demo_manager_links_v1"
    if _has_marker(key):
        return
    with engine.begin() as connection:
        manager = connection.execute(
            text("SELECT id FROM employees WHERE lower(trim(employee_code)) = 'emp008'")
        ).first()
        if manager:
            for code in ("emp001", "emp002", "emp003", "emp004"):
                connection.execute(text(
                    "UPDATE employees SET manager_id = :manager_id "
                    "WHERE lower(trim(employee_code)) = :code AND manager_id IS NULL"
                ), {"manager_id": manager.id, "code": code})
    _set_marker(key, date.today().isoformat())


def _link_demo_manager_user() -> None:
    """Link the demo manager account to EMP008 so it can approve its reports."""
    key = "leave_demo_manager_user_v1"
    if _has_marker(key):
        return
    with engine.begin() as connection:
        manager = connection.execute(
            text("SELECT id FROM employees WHERE lower(trim(employee_code)) = 'emp008'")
        ).first()
        if manager:
            connection.execute(text(
                "UPDATE users SET employee_id = :manager_id "
                "WHERE lower(trim(username)) = 'manager' AND employee_id IS NULL"
            ), {"manager_id": manager.id})
    _set_marker(key, date.today().isoformat())


def _migrate_comp_off_sources() -> None:
    """Allow manual and automatic comp-offs to coexist for the same work date."""
    key = "comp_off_source_v1"
    if _has_marker(key):
        return
    inspector = inspect(engine)
    columns = {column["name"] for column in inspector.get_columns("comp_offs")}
    old_unique = False
    for constraint in inspector.get_unique_constraints("comp_offs"):
        names = {str(name).lower() for name in (constraint.get("column_names") or [])}
        if names == {"employee_id", "work_date"}:
            old_unique = True
    for index in inspector.get_indexes("comp_offs"):
        names = {str(name).lower() for name in (index.get("column_names") or [])}
        if names == {"employee_id", "work_date"} and index.get("unique"):
            old_unique = True

    statements = []
    if old_unique:
        statements += [
            """
            CREATE TABLE comp_offs_new (
                id INTEGER PRIMARY KEY,
                employee_id INTEGER NOT NULL,
                work_date DATE NOT NULL,
                expiry_date DATE,
                days FLOAT DEFAULT 1,
                reason TEXT,
                status VARCHAR(20) DEFAULT 'approved',
                approved_by INTEGER,
                source VARCHAR(30) DEFAULT 'manual',
                rule VARCHAR(80),
                extra_hours FLOAT DEFAULT 0,
                extra_hours_balance FLOAT DEFAULT 0,
                created_at DATETIME,
                CONSTRAINT uq_comp_off_source_date UNIQUE (employee_id, work_date, source),
                FOREIGN KEY(employee_id) REFERENCES employees(id) ON DELETE CASCADE,
                FOREIGN KEY(approved_by) REFERENCES users(id) ON DELETE SET NULL
            )
            """,
            f"""
            INSERT INTO comp_offs_new
                (id, employee_id, work_date, expiry_date, days, reason, status,
                 approved_by, source, rule, extra_hours, extra_hours_balance, created_at)
            SELECT id, employee_id, work_date, expiry_date, days, reason, status,
                   approved_by,
                   {'''(COALESCE(source, 'manual'))''' if 'source' in columns else "'manual'"},
                   {'''rule''' if 'rule' in columns else 'NULL'},
                   {'''COALESCE(extra_hours, 0)''' if 'extra_hours' in columns else '0'},
                   {'''COALESCE(extra_hours_balance, 0)''' if 'extra_hours_balance' in columns else '0'},
                   created_at
            FROM comp_offs
            """,
            "DROP TABLE comp_offs",
            "ALTER TABLE comp_offs_new RENAME TO comp_offs",
            "CREATE INDEX IF NOT EXISTS ix_comp_off_employee_id ON comp_offs (employee_id)",
        ]
    else:
        statements.append(
            "CREATE UNIQUE INDEX IF NOT EXISTS ix_comp_off_source_date "
            "ON comp_offs (employee_id, work_date, source)"
        )
    with engine.begin() as connection:
        for statement in statements:
            connection.execute(text(statement))
    _set_marker(key, date.today().isoformat())


def _normalize_shift_group_designations() -> None:
    """Keep designation mappings readable even on databases created by old code."""
    with engine.begin() as connection:
        rows = connection.execute(
            text("SELECT id, designation_ids FROM shift_groups")
        ).fetchall()
        for row in rows:
            try:
                raw = json.loads(row.designation_ids) if row.designation_ids else []
            except (TypeError, ValueError):
                raw = []
            if not isinstance(raw, list):
                raw = []
            cleaned = []
            for value in raw:
                try:
                    cleaned.append(int(value))
                except (TypeError, ValueError):
                    continue
            cleaned = list(dict.fromkeys(cleaned))
            encoded = json.dumps(cleaned)
            if (row.designation_ids or "[]") != encoded:
                connection.execute(
                    text("UPDATE shift_groups SET designation_ids = :value WHERE id = :id"),
                    {"value": encoded, "id": row.id},
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
    _create_leave_tables()
    _seed_leave_defaults()
    _retire_sick_leave()
    _grant_leave_permissions()
    _link_demo_manager()
    _link_demo_manager_user()
    _migrate_comp_off_sources()
    _normalize_shift_group_designations()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
