from fastapi.testclient import TestClient

from adaptive_academy.api.app import create_app
from adaptive_academy.settings import settings


def _spa_client(tmp_path, monkeypatch) -> TestClient:
    (tmp_path / "index.html").write_text("<html>SPA SHELL</html>")
    assets = tmp_path / "_app"
    assets.mkdir()
    (assets / "bundle.js").write_text("console.log('hi')")
    monkeypatch.setattr(settings, "frontend_dist", str(tmp_path))
    return TestClient(create_app())


def test_root_serves_index(tmp_path, monkeypatch):
    client = _spa_client(tmp_path, monkeypatch)
    resp = client.get("/")
    assert resp.status_code == 200
    assert "SPA SHELL" in resp.text


def test_deep_client_route_falls_back_to_index(tmp_path, monkeypatch):
    client = _spa_client(tmp_path, monkeypatch)
    resp = client.get("/topics/3/tutor")
    assert resp.status_code == 200
    assert "SPA SHELL" in resp.text


def test_real_asset_served_directly(tmp_path, monkeypatch):
    client = _spa_client(tmp_path, monkeypatch)
    resp = client.get("/_app/bundle.js")
    assert resp.status_code == 200
    assert "console.log" in resp.text


def test_api_routes_still_win(tmp_path, monkeypatch):
    client = _spa_client(tmp_path, monkeypatch)
    resp = client.get("/api/health")
    assert resp.json() == {"status": "ok"}


def test_unknown_api_path_is_404_not_index(tmp_path, monkeypatch):
    client = _spa_client(tmp_path, monkeypatch)
    resp = client.get("/api/nope")
    assert resp.status_code == 404


def test_path_traversal_does_not_escape_dist(tmp_path, monkeypatch):
    secret = tmp_path.parent / "secret.txt"
    secret.write_text("s3cret")
    client = _spa_client(tmp_path, monkeypatch)
    resp = client.get("/../secret.txt")
    assert "s3cret" not in resp.text


def test_no_dist_dir_means_no_spa_route(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "frontend_dist", str(tmp_path / "missing"))
    client = TestClient(create_app())
    resp = client.get("/")
    assert resp.status_code == 404
