import os
import sqlite3
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from wko_ingest import loader, validator  # noqa: E402

EXPORTS_DIR = r"C:\Users\mkarl\OneDrive\Documents\Training Coach\WKO5 Exports"


@pytest.fixture(scope="session")
def db_path(tmp_path_factory):
    """Build the real dataset once and run the validator (so data_flags are stamped)."""
    path = str(tmp_path_factory.mktemp("wko") / "wko.db")
    loader.build_database(path, EXPORTS_DIR, loaded_at="2026-06-10T00:00:00")
    validator.run(path, EXPORTS_DIR)
    return path


@pytest.fixture(scope="session")
def conn(db_path):
    c = sqlite3.connect(db_path)
    yield c
    c.close()
