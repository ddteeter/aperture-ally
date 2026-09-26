"""HTTP surface: CRUD semantics, security restrictions, state endpoint, websocket origin check."""

import asyncio

import httpx
import pytest
from fastapi.testclient import TestClient

from aperture_ally.app import create_app

from .conftest import fast_settings


@pytest.fixture
async def api(make_harness, fx):
    h = await make_harness(import_roots=[fx])
    app = create_app(h.app.settings, coach=h.app)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1") as c:
        yield c, h, app


async def test_session_lifecycle_and_setup_revisions(api):
    c, _h, _ = api
    r = await c.post("/api/sessions", json={"name": "Shoe A", "product": "Trainer", "simulated": True,
                                            "setup": {"light": "continuous"}})
    assert r.status_code == 201
    sid = r.json()["id"]
    st = (await c.get(f"/api/sessions/{sid}")).json()
    assert len(st["shots"]) == 6 and st["session"]["simulated"] and st["setup"]["revision"] == 1
    assert st["session"]["active_shot_id"] == st["shots"][0]["id"]
    r = await c.patch(f"/api/sessions/{sid}/setup", json={"support": "tripod"})
    assert r.json()["revision"] == 2 and r.json()["light"] == "continuous"  # revision carries forward
    assert (await c.patch(f"/api/sessions/{sid}/setup", json={"flux_capacitor": 1})).status_code == 422
    assert (await c.patch(f"/api/sessions/{sid}/setup", json={"light": "lasers"})).status_code == 422
    shot = st["shots"][1]["id"]
    r = await c.patch(f"/api/sessions/{sid}/shots/{shot}", json={"criteria": [{"id": "c1", "text": "a"}, {"id": "c1", "text": "b"}]})
    assert r.status_code == 422
    assert (await c.patch(f"/api/sessions/{sid}/active-shot", json={"shot_id": "nope"})).status_code == 404
    assert (await c.get("/api/sessions/does-not-exist")).status_code == 404


async def test_import_restricted_to_roots_and_images_served_by_id(api, fx):
    c, h, _ = api
    sid = (await c.post("/api/sessions", json={"name": "x"})).json()["id"]
    assert (await c.post(f"/api/sessions/{sid}/imports", json={"paths": ["/etc/passwd"]})).status_code == 403
    r = await c.post(f"/api/sessions/{sid}/imports", json={"paths": [str(fx / "P9260001.JPG")]})
    (cid,) = r.json()["capture_ids"]
    await h.settled()
    for kind in ("overview", "thumb", "original", "crop_auto1"):
        img = await c.get(f"/api/captures/{cid}/image/{kind}")
        assert img.status_code == 200 and img.headers["content-type"] == "image/jpeg", kind
    assert (await c.get(f"/api/captures/{cid}/image/..%2F..%2Fetc%2Fpasswd")).status_code == 404
    view = (await c.get(f"/api/captures/{cid}")).json()
    assert "jpeg_path" in view and "path" not in str(view["evidence"]["crops"])


async def test_upload_and_keeper_endpoints(api, fx):
    c, h, _ = api
    sid = (await c.post("/api/sessions", json={"name": "x"})).json()["id"]
    st = (await c.get(f"/api/sessions/{sid}")).json()
    shot = st["shots"][0]["id"]
    files = [("files", ("P9260001.JPG", (fx / "P9260001.JPG").read_bytes(), "image/jpeg"))]
    r = await c.post(f"/api/sessions/{sid}/uploads", files=files, data={"shot_id": shot})
    (cid,) = r.json()["capture_ids"]
    bad = [("files", ("evil.sh", b"#!/bin/sh", "text/plain"))]
    assert (await c.post(f"/api/sessions/{sid}/uploads", files=bad)).status_code == 422
    await h.settled()
    assert (await c.post(f"/api/shots/{shot}/keeper", json={"capture_id": cid})).status_code == 201
    cov = (await c.get(f"/api/sessions/{sid}/coverage")).json()
    assert cov["resolved"] == 1
    assert (await c.delete(f"/api/shots/{shot}/keeper")).json()["revoked"]
    ex = (await c.post(f"/api/sessions/{sid}/exports")).json()
    assert set(ex) >= {"json", "markdown", "contact_sheet", "timing_json", "timing_markdown"}


async def test_voice_endpoints_and_diagnostics(api):
    c, h, _ = api
    await c.post("/api/sessions", json={"name": "x"})
    await c.post("/api/diagnostics/mock-transcript", json={"text": "next shot"})
    r = await c.post("/api/voice/start", json={})
    assert "turn_id" in r.json()
    assert (await c.post("/api/voice/start", json={})).json() == {"ignored": "already listening"}
    await asyncio.sleep(0.3)
    await c.post("/api/voice/stop", json={})
    await h.wait(lambda: h.app.voice.state.value == "idle", 5)
    d = (await c.get("/api/diagnostics")).json()
    assert {"checks", "config", "keys", "timing", "providers"} <= set(d)
    assert "openai_api_key" not in str(d["config"]) and "gemini_api_key" not in str(d["config"])
    schema = (await c.get("/api/schema/assessment")).json()
    assert schema["additionalProperties"] is False
    eq = (await c.get("/api/exposure/equivalent", params={"old_s": 1 / 125, "old_f": 2.8, "old_iso": 200, "new_f": 8})).json()
    assert eq["rounded_label"] == "1/15 s"


def test_foreign_host_and_origin_rejected(tmp_path):
    settings = fast_settings(tmp_path / "d")
    app = create_app(settings)
    with TestClient(app, base_url="http://127.0.0.1") as client:
        assert client.get("/api/health").status_code == 200
        assert client.get("/api/health", headers={"host": "evil.example"}).status_code == 400
        r = client.get("/api/health", headers={"origin": "http://evil.example"})
        assert "access-control-allow-origin" not in r.headers
        with client.websocket_connect("/api/events", headers={"origin": "http://127.0.0.1:5173"}) as ws:
            assert ws.receive_json()["type"] == "hello"
        from starlette.websockets import WebSocketDisconnect

        with pytest.raises(WebSocketDisconnect), client.websocket_connect(
                "/api/events", headers={"origin": "http://evil.example"}) as ws:
            ws.receive_json()
