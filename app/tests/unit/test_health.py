from unittest.mock import patch

from fastapi.testclient import TestClient


def test_health_check_returns_ok_and_security_headers(client: TestClient) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}

    # Verify security headers
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["X-Frame-Options"] == "DENY"
    assert response.headers["Referrer-Policy"] == "no-referrer"
    assert "X-Request-ID" in response.headers


def test_request_id_preserved_when_valid(client: TestClient) -> None:
    custom_id = "custom-valid-req-id-12345"
    response = client.get("/health", headers={"X-Request-ID": custom_id})
    assert response.status_code == 200
    assert response.headers["X-Request-ID"] == custom_id


def test_request_id_regenerated_when_invalid(client: TestClient) -> None:
    invalid_id = "short"  # < 8 chars
    response = client.get("/health", headers={"X-Request-ID": invalid_id})
    assert response.status_code == 200
    assert response.headers["X-Request-ID"] != invalid_id
    assert len(response.headers["X-Request-ID"]) >= 8


def test_ready_check_database_available(client: TestClient) -> None:
    with patch("app.main.check_database_health", return_value=True):
        response = client.get("/ready")
        assert response.status_code == 200
        assert response.json() == {"status": "ready"}


def test_ready_check_database_unavailable_returns_503(client: TestClient) -> None:
    with patch("app.main.check_database_health", return_value=False):
        response = client.get("/ready")
        assert response.status_code == 503
        data = response.json()
        assert data["error"]["code"] == "service_unavailable"
        assert "La base de données est injoignable" in data["error"]["message"]
        assert "request_id" in data["error"]
