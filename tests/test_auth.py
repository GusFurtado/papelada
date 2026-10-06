import pytest
from fastapi.testclient import TestClient

from app import auth as auth_module
from app.auth import AuthConfigError, Throttle, load_credentials_from_env
from app.main import create_app
from app.storage import Library

from .conftest import JPEG


@pytest.fixture
def client(lib: Library) -> TestClient:
    return TestClient(create_app(lib, credentials=("alice", "s3cret")))


def login(client, username="alice", password="s3cret"):
    return client.post("/api/login", json={"username": username, "password": password})


def test_no_login_when_credentials_are_not_set(lib):
    client = TestClient(create_app(lib))
    assert client.get("/api/session").json() == {"login_required": False, "authenticated": True}
    assert client.get("/api/sections").status_code == 200


def test_every_api_route_needs_a_session(client):
    assert client.get("/api/health").json() == {"ok": True}
    assert client.get("/api/session").json() == {"login_required": True, "authenticated": False}
    for method, url in [
        ("get", "/api/sections"), ("get", "/api/settings"), ("get", "/api/docs"),
        ("get", "/api/openapi.json"), ("post", "/api/scan"), ("get", "/api/documents/x/pages/y/content"),
        ("post", "/api/documents/download"),
    ]:
        res = getattr(client, method)(url)
        assert (res.status_code, res.json()) == (401, {"detail": "login_required"}), url
    # The frontend itself stays reachable, so the login screen can load.
    assert client.get("/").status_code == 200


def test_login_gives_a_session_and_logout_ends_it(client):
    res = login(client)
    assert res.status_code == 200
    cookie = res.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=strict" in cookie and "path=" not in cookie
    assert "secure" not in cookie  # plain http here
    assert client.get("/api/session").json() == {"login_required": True, "authenticated": True}
    assert client.get("/api/sections").status_code == 200
    assert client.get("/api/docs").status_code == 200

    assert client.post("/api/logout").status_code == 200
    assert client.get("/api/sections").status_code == 401


def test_cookie_is_secure_behind_an_https_proxy(client):
    res = client.post("/api/login", json={"username": "alice", "password": "s3cret"},
                      headers={"X-Forwarded-Proto": "https"})
    assert "secure" in res.headers["set-cookie"].lower()


@pytest.mark.parametrize("username,password", [("alice", "nope"), ("bob", "s3cret"), ("", ""), ("ALICE", "s3cret")])
def test_wrong_credentials(client, username, password):
    res = login(client, username, password)
    assert (res.status_code, res.json()) == (401, {"detail": "invalid_credentials"})
    assert "set-cookie" not in res.headers
    assert client.get("/api/sections").status_code == 401


def test_forged_and_expired_sessions_are_rejected(client, lib):
    for token in ["", "x", "a.b", "1.zz", "99999999999.00"]:
        client.cookies.set("papelada_session", token)
        assert client.get("/api/sections").status_code == 401

    other = TestClient(create_app(lib, credentials=("alice", "s3cret")))
    login(other)
    client.cookies.set("papelada_session", other.cookies["papelada_session"])  # signed by another process's key
    assert client.get("/api/sections").status_code == 401

    auth = client.app.state.auth
    assert not auth.valid_session("\u00e9.\u00e9")
    token = auth.new_session(now=0)
    assert auth.valid_session(token, now=auth_module.SESSION_SECONDS - 1)
    assert not auth.valid_session(token, now=auth_module.SESSION_SECONDS + 1)


def test_failed_attempts_are_throttled(client):
    for _ in range(auth_module.MAX_FAILURES_PER_CLIENT):
        assert login(client, password="wrong").status_code == 401
    res = login(client, password="wrong")
    assert res.status_code == 429
    assert res.json()["detail"] == "too_many_attempts" and res.json()["retry_after"] > 0
    assert res.headers["retry-after"] == str(res.json()["retry_after"])
    # Even the right password is refused while locked out.
    assert login(client).status_code == 429
    assert client.get("/api/sections").status_code == 401


def test_throttle_window_and_reset():
    t = Throttle(window=100)
    for i in range(5):
        t.fail("a", now=i)
    assert t.retry_after("a", now=5) == 96  # the oldest failure (t=0) leaves the window at t=100
    assert t.retry_after("b", now=5) == 0
    assert t.retry_after("a", now=101) == 0  # four failures left in the window, below the limit
    t.fail("a", now=200)
    t.succeed("a")
    assert "a" not in t.failures


def test_total_failures_lock_every_client():
    t = Throttle(window=100)
    for i in range(auth_module.MAX_FAILURES_TOTAL):
        t.fail(f"client{i}", now=i)
    assert t.retry_after("someone-new", now=60) > 0
    assert t.retry_after("someone-new", now=200) == 0


def test_a_successful_login_clears_that_clients_failures(client):
    for _ in range(auth_module.MAX_FAILURES_PER_CLIENT - 1):
        login(client, password="wrong")
    assert login(client).status_code == 200
    for _ in range(auth_module.MAX_FAILURES_PER_CLIENT - 1):
        assert login(client, password="wrong").status_code == 401


def test_upload_works_with_a_session(client, tmp_path):
    login(client)
    section = client.post("/api/sections", json={"name": "S", "icon": "folder"}).json()
    res = client.post("/api/documents", data={"section": section["id"], "title": "D", "date": "2026-01-01"},
                      files=[("files", ("a.jpg", JPEG, "image/jpeg"))])
    assert res.status_code == 200


# --- configuration ---------------------------------------------------------------------


@pytest.fixture
def env(monkeypatch):
    for name in ("USERNAME", "PASSWORD", "PASSWORD_FILE"):
        monkeypatch.delenv(name, raising=False)
    return monkeypatch


def test_credentials_from_env(env, tmp_path):
    assert load_credentials_from_env() is None
    env.setenv("USERNAME", "  ")
    env.setenv("PASSWORD", "")
    assert load_credentials_from_env() is None

    env.setenv("USERNAME", "alice")
    env.setenv("PASSWORD", " pa ss ")
    assert load_credentials_from_env() == ("alice", " pa ss ")


def test_password_from_a_secret_file(env, tmp_path):
    secret = tmp_path / "password"
    secret.write_text("from-file\n")
    env.setenv("USERNAME", "alice")
    env.setenv("PASSWORD_FILE", str(secret))
    assert load_credentials_from_env() == ("alice", "from-file")
    env.setenv("PASSWORD", "from-env")  # the variable wins, like ENCRYPTION_KEY
    assert load_credentials_from_env() == ("alice", "from-env")


@pytest.mark.parametrize("variables", [{"USERNAME": "alice"}, {"PASSWORD": "x"}])
def test_only_one_of_username_and_password_refuses_to_start(env, lib, variables):
    for name, value in variables.items():
        env.setenv(name, value)
    with pytest.raises(AuthConfigError):
        create_app(lib)
