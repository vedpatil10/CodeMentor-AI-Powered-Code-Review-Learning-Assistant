import asyncio

from httpx import ASGITransport, AsyncClient, Response

from app.main import create_app


async def _request(path: str) -> Response:
    transport = ASGITransport(app=create_app())
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        return await client.get(path)


def get(path: str) -> Response:
    return asyncio.run(_request(path))


def test_liveness_endpoint_reports_process_alive() -> None:
    response = get("/health/live")

    assert response.status_code == 200
    assert response.json() == {"status": "alive"}


def test_readiness_endpoint_reports_current_application_checks() -> None:
    response = get("/health/ready")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ready",
        "checks": {"application": "ready"},
    }


def test_unknown_health_route_is_not_registered() -> None:
    response = get("/health/ping")

    assert response.status_code == 404