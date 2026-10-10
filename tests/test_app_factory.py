def test_app_builds_with_default_services(app):
    assert app.title == "DnD DM Server"


def test_create_session_endpoint(client):
    resp = client.post("/api/v1/sessions")
    assert resp.status_code == 201
    body = resp.json()
    assert "session_id" in body
