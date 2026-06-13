import os, sqlite3, sys
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SLICE4 = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for p in (SLICE4, os.path.join(ROOT, "slice1")):
    if p not in sys.path:
        sys.path.insert(0, p)
import pytest
from wko_metrics import metrics

WKO_DB = os.path.join(ROOT, "slice0", "wko.db")

@pytest.fixture(scope="session")
def m():
    return metrics.Metrics(sqlite3.connect(WKO_DB))

@pytest.fixture(scope="session")
def as_of(m):
    return m.daily.index.max().strftime("%Y-%m-%d")
