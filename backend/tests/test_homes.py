"""Retired property API must remain unavailable while historical data is preserved."""
import pytest

from app.models import Home


@pytest.mark.parametrize("method,path,payload", [
    ("post", "/homes", {"name": "New home", "city": "New city"}),
    ("get", "/homes", None),
    ("get", "/homes/1", None),
    ("put", "/homes/1", {"name": "Changed home", "city": "Changed city"}),
    ("delete", "/homes/1", None),
])
def test_retired_homes_routes_preserve_stored_rows(client, anonymous, file_env, method, path, payload):
    sessions, _ = file_env
    with sessions() as db:
        db.add(Home(id=1, name="Preserved home", city="Preserved city"))
        db.commit()

    for caller in (client, anonymous):
        options = {"json": payload} if payload is not None else {}
        assert getattr(caller, method)(path, **options).status_code == 404

    with sessions() as db:
        rows = db.query(Home).all()
        assert len(rows) == 1
        assert (rows[0].id, rows[0].name, rows[0].city) == (1, "Preserved home", "Preserved city")


def test_retired_homes_routes_and_schemas_are_absent_from_openapi(anonymous):
    response = anonymous.get("/openapi.json")
    assert response.status_code == 200
    schema = response.json()
    assert not any(path == "/homes" or path.startswith("/homes/") for path in schema["paths"])
    assert {"HomeCreate", "HomeRead"}.isdisjoint(schema.get("components", {}).get("schemas", {}))
