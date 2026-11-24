import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.generate_sample_data import SAMPLE_END, SAMPLE_START, create_sample_db  # noqa: E402


def sample_db():
    """Return (engine, sessionmaker) with fresh realistic attendance data."""
    return create_sample_db()
