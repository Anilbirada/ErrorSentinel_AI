from fastapi.testclient import TestClient

from app.main import app


def test_login_page_does_not_require_request_query_parameter() -> None:
    response = TestClient(app).get("/login")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert 'href="/auth/google/login"' in response.text
