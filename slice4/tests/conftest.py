import os, sqlite3, sys
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SLICE4 = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for p in (SLICE4, os.path.join(ROOT, "slice1"), os.path.join(ROOT, "slice0")):
    if p not in sys.path:
        sys.path.insert(0, p)
import pytest
from wko_ingest import loader as s0_loader
from wko_metrics import metrics

# Build the fixture from the IMMUTABLE WKO5 exports (not slice0/wko.db, which the app now repurposes
# for Strava-sourced data). Mirrors the slice2 conftest so the generator tests run on stable data.
EXPORTS_DIR = os.path.join(ROOT, "WKO5 Exports")


@pytest.fixture(scope="session")
def m(tmp_path_factory):
    path = str(tmp_path_factory.mktemp("wko") / "wko.db")
    s0_loader.build_database(path, EXPORTS_DIR, loaded_at="2026-06-10T00:00:00")
    return metrics.Metrics(sqlite3.connect(path))


@pytest.fixture(scope="session")
def as_of(m):
    return m.daily.index.max().strftime("%Y-%m-%d")
