from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    APP_NAME: str = "HRMS"
    APP_VERSION: str = "1.0.0"
    SECRET_KEY: str = "please-change-this-secret-key-in-production"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 1440

    # SQLite by default (persisted through a docker volume).
    DATABASE_URL: str = "sqlite:///./data/hrms.db"

    # Biometric device configuration.
    # DEVICE_MODE: "simulate" (generates demo punches) or "live" (talks to the device).
    DEVICE_MODE: str = "simulate"
    DEVICE_IP: str = "192.168.20.90"
    DEVICE_PORT: int = 4370
    DEVICE_TIMEOUT: int = 5
    DEVICE_SYNC_INTERVAL_MINUTES: int = 10
    AUTO_CREATE_DEVICE_USERS: bool = True
    DEFAULT_SHIFT_NAME: str = "General Shift"

    PDF_DIR: str = "./data/pdfs"
    DOCUMENT_DIR: str = "./data/documents"
    CORS_ORIGINS: str = "*"

    # Attendance/punch logs are kept for at least this many days.  There is no
    # automatic purge inside the window; historical data is never deleted by
    # the normal sync or recompute flows.
    LOG_RETENTION_DAYS: int = 365

    # Advanced attendance engine defaults.  These can be overridden at runtime
    # from the Attendance → Advanced reports → Engine settings panel.
    PAIRING_MODE: str = "strict"  # strict | first_last
    PUNCH_DEBOUNCE_MINUTES: int = 2
    HALF_DAY_HOURS: float = 4.5
    FULL_DAY_HOURS: float = 8.0
    OT_MIN_MINUTES: int = 30
    OT_ROUND_MINUTES: int = 15
    OT_MULTIPLIER: float = 1.5
    HOLIDAY_OT_MULTIPLIER: float = 2.0
    WEEKOFF_OT_MULTIPLIER: float = 2.0
    COMP_OFF_HOURS_PER_DAY: float = 8.0
    SANDWICH_RULE: bool = False
    CONTINUOUS_ABSENCE_DAYS: int = 3
    LATE_PENALTY_INSTANCES: int = 3
    LATE_PENALTY_DAYS: float = 0.5

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()
