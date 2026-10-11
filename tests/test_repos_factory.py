"""`database.url` parsing and demo seeding for make_default_repos (SPEC-0005 WP-4)."""

import pytest

from app.services.repos import SqliteSessionStore, make_default_repos, seed_sample_data


def test_make_default_repos_defaults_to_independent_memory_stores(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    first = make_default_repos()
    second = make_default_repos()
    try:
        assert isinstance(first["session"], SqliteSessionStore)
        assert isinstance(second["session"], SqliteSessionStore)

        first["session"].create_session("s")
        assert second["session"].get_session("s") is None
    finally:
        first["session"].close()
        second["session"].close()

    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("kind", ["relative", "absolute"])
def test_make_default_repos_honours_file_urls(tmp_path, monkeypatch, kind):
    monkeypatch.chdir(tmp_path)
    if kind == "relative":
        url = "sqlite:///./x.db"
        expected = tmp_path / "x.db"
    else:
        expected = tmp_path / "y.db"
        url = f"sqlite:///{tmp_path}/y.db"

    store = make_default_repos(url)["session"]
    store.create_session("s")
    store.create_message("s", "m1", {"role": "user", "content": "hi"})
    store.close()

    assert expected.exists()
    reopened = SqliteSessionStore(str(expected))
    try:
        assert [m["id"] for m in reopened.list_messages("s")] == ["m1"]
    finally:
        reopened.close()


def test_make_default_repos_memory_url_creates_no_file(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    store = make_default_repos("sqlite:///:memory:")["session"]
    try:
        store.create_session("s")
    finally:
        store.close()

    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize(
    "url",
    [
        "postgresql://user:" "secret" "@h/db",
        "mysql://h/db",
        "sqlite://",
        "sqlite:///",
        "http://x",
        "",
    ],
)
def test_make_default_repos_rejects_unsupported_urls(url):
    with pytest.raises(ValueError) as excinfo:
        make_default_repos(url)

    assert "secret" not in str(excinfo.value)


def test_seed_sample_data_is_idempotent(tmp_path):
    path = tmp_path / "seed.db"
    repos = make_default_repos(f"sqlite:///{path}")
    try:
        seed_sample_data(repos)
        seed_sample_data(repos)

        msgs = repos["session"].list_messages("demo")
        assert len(msgs) == 1
        assert msgs[0]["id"] == "msg-1"
        assert msgs[0]["content"] == "Hello world!"
    finally:
        repos["session"].close()

    reopened = {"session": SqliteSessionStore(str(path))}
    try:
        seed_sample_data(reopened)
        assert len(reopened["session"].list_messages("demo")) == 1
    finally:
        reopened["session"].close()
