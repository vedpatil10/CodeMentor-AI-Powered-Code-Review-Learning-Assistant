import asyncio

from httpx import ASGITransport, AsyncClient, Response

from app.config import Settings
from app.db.deliveries import DeliveryStore
from app.main import create_app


async def _request(path: str, application=None) -> Response:
    transport = ASGITransport(app=application or create_app())
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        return await client.get(path)


def get(path: str, application=None) -> Response:
    return asyncio.run(_request(path, application))


def test_liveness_endpoint_reports_process_alive() -> None:
    response = get("/health/live")

    assert response.status_code == 200
    assert response.json() == {"status": "alive"}


def test_readiness_endpoint_reports_current_application_checks(tmp_path) -> None:
    database_path = tmp_path / "health.sqlite3"
    application = create_app(
        settings=Settings(database_path=database_path),
        delivery_store=DeliveryStore(database_path),
    )
    response = get("/health/ready", application)

    assert response.status_code == 200
    assert response.json() == {
        "status": "ready",
        "checks": {"application": "ready", "delivery_store": "ready"},
    }


def test_readiness_fails_when_delivery_store_is_unavailable(tmp_path) -> None:
    blocking_file = tmp_path / "not-a-directory"
    blocking_file.write_text("block database parent", encoding="utf-8")
    database_path = blocking_file / "health.sqlite3"
    application = create_app(
        settings=Settings(database_path=database_path),
        delivery_store=DeliveryStore(database_path),
    )

    response = get("/health/ready", application)

    assert response.status_code == 503
    assert response.json() == {"detail": "delivery store unavailable"}


def test_unknown_health_route_is_not_registered() -> None:
    response = get("/health/ping")

    assert response.status_code == 404