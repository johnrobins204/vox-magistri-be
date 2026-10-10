import pytest
from fastapi.testclient import TestClient

from app.factory import create_app
from app.services.build_services import build_services
from app.services.repos import make_default_repos


@pytest.fixture
def app():
    repos = make_default_repos()
    services = build_services(repos, enable_tool_discovery=False)
    return create_app(services=services)


@pytest.fixture
def client(app):
    with TestClient(app) as c:
        yield c
