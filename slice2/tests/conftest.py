import os
import sqlite3
import sys

import pytest

SLICE2 = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SLICE1 = os.path.join(os.path.dirname(SLICE2), "slice1")
SLICE0 = os.path.join(os.path.dirname(SLICE2), "slice0")
for p in (SLICE2, SLICE1, SLICE0):
    sys.path.insert(0, p)

from wko_ingest import loader as s0_loader, validator as s0_validator  # noqa: E402
from wko_metrics import metrics, detectors                              # noqa: E402

EXPORTS_DIR = r"C:\Users\mkarl\OneDrive\Documents\Training Coach\WKO5 Exports"


@pytest.fixture(scope="session")
def m(tmp_path_factory):
    path = str(tmp_path_factory.mktemp("wko") / "wko.db")
    s0_loader.build_database(path, EXPORTS_DIR, loaded_at="2026-06-10T00:00:00")
    s0_validator.run(path, EXPORTS_DIR)
    return metrics.Metrics(sqlite3.connect(path))


@pytest.fixture(scope="session")
def findings(m):
    return detectors.run_all(m)
