"""The Host-header allowlist (api/hosts.py): local names only, plus AA_ALLOWED_HOSTS."""

import pytest
from fastapi.testclient import TestClient

from adaptive_academy.api.app import create_app
from adaptive_academy.api.hosts import allowed_hosts, host_name
from adaptive_academy.settings import settings


@pytest.mark.parametrize("host", ["localhost", "localhost:8000", "127.0.0.1:5173", "[::1]:8000",
                                  "[::1]", "testserver", "LOCALHOST:8000"])
def test_local_names_are_answered(host):
    client = TestClient(create_app())
    assert client.get("/api/health", headers={"host": host}).status_code == 200


@pytest.mark.parametrize("host", ["evil.example", "evil.example:8000", "127.0.0.1.evil.example",
                                  "[::2]:8000", "localhost.evil.example", ""])
def test_other_names_get_a_400(host):
    client = TestClient(create_app())
    r = client.get("/api/health", headers={"host": host})
    assert r.status_code == 400
    assert "AA_ALLOWED_HOSTS" in r.text


def test_extra_names_come_from_the_setting(monkeypatch):
    monkeypatch.setattr(settings, "allowed_hosts", " mybox.local , *.lan ")
    client = TestClient(create_app())
    assert client.get("/api/health", headers={"host": "mybox.local:8000"}).status_code == 200
    assert client.get("/api/health", headers={"host": "pi.lan"}).status_code == 200
    assert client.get("/api/health", headers={"host": "other.local"}).status_code == 400


def test_host_parsing():
    assert host_name("[::1]:8000") == "[::1]"
    assert host_name("Example.COM:80") == "example.com"
    assert allowed_hosts("a.b, ,A.B") == ["localhost", "127.0.0.1", "[::1]", "testserver", "a.b"]
