import os
import pytest
from fastapi.testclient import TestClient

import cloud_app
from groww_adapter import GrowwAdapter, GrowwNotConfigured


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("DASHBOARD_USERNAME", "admin")
    monkeypatch.setenv("DASHBOARD_PASSWORD", "test-password")
    return TestClient(cloud_app.app)


def test_groww_status_does_not_expose_credentials(client, monkeypatch):
    monkeypatch.setenv("GROWW_API_KEY", "sample-key")
    monkeypatch.setenv("GROWW_API_SECRET", "sample-secret")
    response = client.get("/api/groww/status", auth=("admin", "test-password"))
    assert response.status_code == 200
    payload = response.json()
    assert payload["configured"] is True
    assert payload["live_orders_enabled"] is False
    assert "sample-key" not in response.text
    assert "sample-secret" not in response.text


def test_groww_routes_require_dashboard_auth(client):
    response = client.get("/api/groww/status")
    assert response.status_code == 401


def test_profile_route_uses_read_only_profile_function(client, monkeypatch):
    monkeypatch.setattr("groww_portfolio.get_profile", lambda: {"nse_enabled": True, "bse_enabled": True})
    response = client.get("/api/groww/profile", auth=("admin", "test-password"))
    assert response.status_code == 200
    assert response.json()["profile"]["nse_enabled"] is True
    assert response.json()["live_orders_enabled"] is False


def test_adapter_requires_both_credentials(monkeypatch):
    monkeypatch.delenv("GROWW_API_KEY", raising=False)
    monkeypatch.delenv("GROWW_API_SECRET", raising=False)
    with pytest.raises(GrowwNotConfigured):
        GrowwAdapter()


def test_live_order_methods_are_hard_disabled():
    adapter = object.__new__(GrowwAdapter)
    with pytest.raises(PermissionError):
        adapter.place_order(trading_symbol="RELIANCE")
    with pytest.raises(PermissionError):
        adapter.modify_order(groww_order_id="x")
    with pytest.raises(PermissionError):
        adapter.cancel_order(groww_order_id="x")


def test_invalid_symbol_rejected_before_sdk_call():
    with pytest.raises(ValueError):
        GrowwAdapter._symbol("RELIANCE;DROP")
