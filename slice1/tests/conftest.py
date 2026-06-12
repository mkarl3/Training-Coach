import os
import sqlite3
import sys

import pytest

SLICE1 = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SLICE0 = os.path.join(os.path.dirname(SLICE1), "slice0")
sys.path.insert(0, SLICE1)
sys.path.insert(0, SLICE0)

from wko_ingest import loader as s0_loader, validator as s0_validator  # noqa: E402

EXPORTS_DIR = r"C:\Users\mkarl\OneDrive\Documents\Training Coach\WKO5 Exports"


@pytest.fixture(scope="session")
def conn(tmp_path_factory):
    """Rebuild the slice-0 dataset into a temp DB (with data_flags stamped) and connect."""
    path = str(tmp_path_factory.mktemp("wko") / "wko.db")
    s0_loader.build_database(path, EXPORTS_DIR, loaded_at="2026-06-10T00:00:00")
    s0_validator.run(path, EXPORTS_DIR)
    c = sqlite3.connect(path)
    yield c
    c.close()
