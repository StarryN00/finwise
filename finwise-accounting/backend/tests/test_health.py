from fastapi.testclient import TestClient

from app.main import create_app


def test_health_endpoint_returns_ok():
    client = TestClient(create_app(init_db_on_startup=False))

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
