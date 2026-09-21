import os
import pytest
from fastapi.testclient import TestClient

from app.main import app as fastapi_app

@pytest.fixture(scope="session")
def client():
    return TestClient(fastapi_app)

def pytest_collection_modifyitems(config, items):
    # Tests d'intégration DB: exige RUN_INTEGRATION=1
    if os.getenv("RUN_INTEGRATION") != "1":
        skip = pytest.mark.skip(reason="Set RUN_INTEGRATION=1 to run DB integration tests.")
        for item in items:
            if "integration" in item.keywords:
                item.add_marker(skip)
