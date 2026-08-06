import sys
import os

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
os.environ["MONGO_URI"] = "mongodb://localhost:27017"

from app import app  # noqa: E402


@pytest.fixture
def client():
    with TestClient(app) as client:
        yield client