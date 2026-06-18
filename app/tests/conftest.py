"""Load the unified app's `main` UNAMBIGUOUSLY. Both slice2/api and app/api are named `api`,
so `from api import main` is ambiguous when the full suite runs. We load app/api/main.py by file
path under a unique module name instead."""
import importlib.util
import os
import sys

APP = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if APP not in sys.path:
    sys.path.insert(0, APP)
MAIN_PATH = os.path.join(APP, "api", "main.py")


def load_app_main():
    spec = importlib.util.spec_from_file_location("app_api_main", MAIN_PATH)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["app_api_main"] = mod
    spec.loader.exec_module(mod)               # main.py inserts the slice paths itself
    return mod


import pytest  # noqa: E402


@pytest.fixture
def app_main():
    return load_app_main()
