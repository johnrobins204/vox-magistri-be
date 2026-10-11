import asyncio

import pytest
from fastapi.testclient import TestClient

from app.factory import create_app
from app.services.build_services import build_services
from app.services.repos import InMemorySessionStore, make_default_repos
from tests.session_helpers import make_stub_service


@pytest.fixture
def app():
    repos = make_default_repos()
    services = build_services(repos, enable_tool_discovery=False)
    return create_app(services=services)


@pytest.fixture
def client(app):
    with TestClient(app) as c:
        yield c


@pytest.fixture
def stub_svc(monkeypatch):
    svc = make_stub_service()
    monkeypatch.setattr(svc.client, "generate", lambda prompt, **kw: "stub reply")
    yield svc
    asyncio.run(svc.shutdown())


@pytest.fixture
def session_store():
    return InMemorySessionStore()


@pytest.fixture
def stub_client(stub_svc, session_store):
    app = create_app(services={"inference": stub_svc, "session": session_store})
    with TestClient(app) as c:
        yield c
