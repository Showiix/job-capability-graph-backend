from fastapi import Query
from httpx import ASGITransport, AsyncClient

from app.main import app, create_app


async def test_request_id_is_preserved_in_not_found_response() -> None:
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get(
            "/api/v1/testing/not-found",
            headers={"X-Request-ID": "req_test_123"},
        )

    assert response.status_code == 404
    assert response.headers["X-Request-ID"] == "req_test_123"
    assert response.json()["error"] == {
        "code": "NOT_FOUND",
        "message": "资源不存在",
        "request_id": "req_test_123",
        "details": {},
    }


async def test_invalid_request_id_is_replaced() -> None:
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get(
            "/health/live", headers={"X-Request-ID": "contains spaces"}
        )

    assert response.status_code == 200
    assert response.headers["X-Request-ID"].startswith("req_")


async def test_cors_allows_only_configured_frontend_origin() -> None:
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.options(
            "/health/live",
            headers={
                "Origin": "http://localhost:3000",
                "Access-Control-Request-Method": "GET",
            },
        )

    assert response.status_code == 200
    assert response.headers["Access-Control-Allow-Origin"] == "http://localhost:3000"
    assert response.headers["Access-Control-Allow-Credentials"] == "true"


async def test_validation_errors_use_public_error_contract() -> None:
    test_app = create_app()

    @test_app.get("/validated")
    async def validated(limit: int = Query(ge=1)) -> dict[str, int]:
        return {"limit": limit}

    async with AsyncClient(
        transport=ASGITransport(app=test_app), base_url="http://test"
    ) as client:
        response = await client.get(
            "/validated?limit=0", headers={"X-Request-ID": "req_validation"}
        )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_FAILED"
    assert response.json()["error"]["request_id"] == "req_validation"


async def test_unhandled_errors_do_not_expose_exception_text() -> None:
    test_app = create_app()

    @test_app.get("/boom")
    async def boom() -> None:
        raise RuntimeError("database password leaked")

    async with AsyncClient(
        transport=ASGITransport(app=test_app, raise_app_exceptions=False),
        base_url="http://test",
    ) as client:
        response = await client.get("/boom", headers={"X-Request-ID": "req_boom"})

    assert response.status_code == 500
    assert response.json()["error"] == {
        "code": "INTERNAL_ERROR",
        "message": "系统内部错误",
        "request_id": "req_boom",
        "details": {},
    }
    assert "database password leaked" not in response.text
