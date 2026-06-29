import os

import pytest


def _admin_credentials():
    # Defaults work for local docker-compose (fresh DB)
    user = os.getenv("E2E_ADMIN_USER", "admin")
    password = os.getenv("E2E_ADMIN_PASSWORD", "admin123")
    return user, password


def test_health_is_ok(client):
    r = client.get("/health")
    assert r.status_code == 200
    payload = r.json()
    assert payload.get("status") == "healthy"


def test_protected_route_redirects_when_not_logged_in(client):
    r = client.get("/estudo")
    assert r.status_code == 303
    assert r.headers.get("location") == "/login"


def test_admin_can_login_and_open_admin_materials(client):
    admin_user, admin_password = _admin_credentials()

    login_resp = client.post(
        "/login",
        data={"username": admin_user, "password": admin_password},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    assert login_resp.status_code == 303

    r = client.get("/admin/materials")
    assert r.status_code == 200
    assert "Gestão de materiais" in r.text


@pytest.mark.parametrize(
    "path",
    [
        "/api/session/materials",
        "/api/jobs/does-not-exist",
    ],
)
def test_api_requires_authentication(client, path):
    r = client.get(path)
    assert r.status_code in (401, 404)
    if r.status_code == 401:
        assert r.json().get("detail")


def test_roleplay_api_requires_authentication(client):
    r = client.post(
        "/api/roleplay",
        data={"message": "Atue como um cliente difícil e me teste na venda de um firewall"},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    assert r.status_code == 401
    assert r.json().get("detail")


def test_roleplay_evaluate_api_requires_authentication(client):
    r = client.post(
        "/api/roleplay/evaluate",
        data={"history": "[]"},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    assert r.status_code == 401
    assert r.json().get("detail")
