"""Projects → shoot templates → shoots, and preferences at every level."""

import httpx
import pytest

from aperture_ally.app import create_app
from aperture_ally.domain.models import Project, Session, ShootTemplate


@pytest.fixture
async def api(make_harness):
    h = await make_harness(project_preferences="Soft backgrounds.")
    app = create_app(h.app.settings, coach=h.app)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1") as c:
        yield c, h


async def test_first_start_seeds_the_running_blog_with_both_starter_templates(api):
    c, _h = api
    (p,) = (await c.get("/api/projects")).json()
    assert p["name"] == "Running blog" and p["preferences"] == "Soft backgrounds."    # seeded from the .env value
    names = {t["name"]: t for t in p["templates"]}
    assert set(names) == {"Shoe review", "Apparel"}
    assert names["Shoe review"]["shot_count"] == 6 and names["Apparel"]["shot_count"] == 8
    assert "Hero (3/4 lateral)" in names["Shoe review"]["shot_titles"]


async def test_a_shoot_copies_its_template_and_editing_it_leaves_the_template_alone(api):
    c, h = api
    (p,) = (await c.get("/api/projects")).json()
    shoe = next(t for t in p["templates"] if t["name"] == "Shoe review")
    s = (await c.post("/api/sessions", json={"name": "Pegasus 42", "template_id": shoe["id"],
                                             "shoot_preferences": "Outdoors, no backdrop."})).json()
    assert s["project_id"] == p["id"] and s["template_id"] == shoe["id"] and s["template_version"] == 1
    shots = await h.app.store.shots(s["id"])
    assert len(shots) == 6 and any(c.text.startswith("Background is clean") for c in shots[0].criteria)
    await h.app.update_shot(shots[0].id, {"title": "Hero, low angle"})
    assert (await c.get(f"/api/templates/{shoe['id']}")).json()["shots"][0]["title"] == "Hero (3/4 lateral)"
    # Save to template: the template takes the shoot's list and bumps its version.
    t = (await c.post(f"/api/sessions/{s['id']}/save-to-template", json={})).json()
    assert t["version"] == 2 and t["shots"][0]["title"] == "Hero, low angle"
    assert (await h.app.store.get(Session, s["id"])).template_version == 2


async def test_duplicate_a_template_for_a_new_product_type_and_save_a_shoot_as_a_new_template(api):
    c, _h = api
    (p,) = (await c.get("/api/projects")).json()
    apparel = next(t for t in p["templates"] if t["name"] == "Apparel")
    tights = (await c.post(f"/api/projects/{p['id']}/templates",
                           json={"name": "Half tights", "copy_from": apparel["id"],
                                 "preferences": "Show the leg length on body."})).json()
    assert len(tights["shots"]) == 8 and tights["preferences"] == "Show the leg length on body."
    s = (await c.post("/api/sessions", json={"name": "Tights A", "template_id": tights["id"]})).json()
    hat = (await c.post(f"/api/sessions/{s['id']}/save-to-template", json={"new_name": "Hat"})).json()
    assert hat["name"] == "Hat" and hat["id"] != tights["id"] and len(hat["shots"]) == 8
    assert (await c.get(f"/api/templates/{tights['id']}")).json()["version"] == 1   # untouched
    assert (await c.post(f"/api/projects/{p['id']}/templates", json={"name": "  "})).status_code == 422
    assert (await c.patch("/api/templates/nope", json={"name": "x"})).status_code == 404


async def test_the_coach_gets_every_preference_level_most_general_first(api):
    c, h = api
    (p,) = (await c.get("/api/projects")).json()
    shoe = next(t for t in p["templates"] if t["name"] == "Shoe review")
    await c.patch("/api/prefs", json={"my_preferences": "I edit in Lightroom."})
    await c.patch(f"/api/templates/{shoe['id']}", json={"preferences": "Laces tidy."})
    await c.patch(f"/api/projects/{p['id']}", json={"preferences": "Soft backgrounds, warm light."})
    s = (await c.post("/api/sessions", json={"name": "x", "template_id": shoe["id"],
                                             "shoot_preferences": "Overcast today."})).json()
    session = await h.app.store.get(Session, s["id"])
    assert await h.app.coaching.preferences_for(session) == {
        "yours": "I edit in Lightroom.", "project": "Soft backgrounds, warm light.",
        "template": "Laces tidy.", "shoot": "Overcast today."}
    r = await c.patch(f"/api/sessions/{s['id']}", json={"shoot_preferences": "Sunny now."})
    assert r.json()["shoot_preferences"] == "Sunny now."


async def test_shoots_from_before_projects_are_attached_on_start(make_harness, tmp_path):
    from aperture_ally.persistence.db import Store

    data = tmp_path / "old"
    store = Store(data / "aperture_ally.sqlite3")
    store.put(Session(name="old shoe", output_folder="x", template="running_shoe"))
    store.put(Session(name="old blank", output_folder="y", template="empty"))
    store.close()
    h = await make_harness(data_dir=data)
    shoe = next(t for t in await h.app.store.query(ShootTemplate) if t.source == "running_shoe")
    (proj,) = await h.app.store.query(Project)
    by_name = {s.name: s for s in await h.app.store.list_sessions()}
    assert by_name["old shoe"].template_id == shoe.id and by_name["old shoe"].project_id == proj.id
    assert by_name["old blank"].template_id is None and by_name["old blank"].project_id == proj.id


async def test_what_the_coach_saw_returns_the_stored_request_without_local_paths(api, fx):
    c, h = api
    s = await h.session()
    await h.use_shot(s, "Upper", "mesh")
    h.drop(s, fx / "P9260002.JPG")
    await h.n_captures(s, 1)
    await h.settled(15)
    (a,) = await h.app.store.assessments(s.id)
    calls = (await c.get(f"/api/assessments/{a.id}/calls")).json()
    assert len(calls) == 1 and calls[0]["purpose"] == "assess" and calls[0]["prompt_version"] == a.prompt_version
    req = calls[0]["request"]
    assert "Craft, on every shot" in req["instructions"] and req["context"]["preferences"]["project"]
    assert req["images"] and all("path" not in im for im in req["images"])
    assert calls[0]["response_text"]
    assert (await c.get("/api/assessments/nope/calls")).status_code == 404


async def test_templates_keep_a_version_history_and_shoots_know_how_they_differ(api):
    c, h = api
    (p,) = (await c.get("/api/projects")).json()
    shoe = next(t for t in p["templates"] if t["name"] == "Shoe review")
    assert shoe["history"][-1]["summary"] == "Built-in starter" and shoe["shoot_count"] == 0
    s = (await c.post("/api/sessions", json={"name": "Pegasus 42", "template_id": shoe["id"]})).json()
    st = (await c.get(f"/api/sessions/{s['id']}")).json()
    assert st["origin"]["template_name"] == "Shoe review" and st["origin"]["changes"] == []

    shots = await h.app.store.shots(s["id"])
    heel = shots[3]
    await h.app.update_shot(heel.id, {"criteria": [*[c.model_dump() for c in heel.criteria],
                                                   {"id": "pull_tab_straight", "text": "Pull tab straight, not folded"}]})
    await c.post(f"/api/sessions/{s['id']}/shots", json={"title": "Laces detail", "framing": "Top-down"})
    changes = (await c.get(f"/api/sessions/{s['id']}")).json()["origin"]["changes"]
    assert [x["g"] for x in changes] == ["~", "+"]
    assert changes[0]["title"] == f"4 · {heel.title}" and "Pull tab straight" in changes[0]["detail"]
    assert changes[1]["title"] == "7 · Laces detail" and "Top-down" in changes[1]["detail"]
    row = next(x for x in (await c.get("/api/sessions")).json() if x["id"] == s["id"])
    assert row["origin"]["changes"] == 2 and row["origin"]["template_name"] == "Shoe review"

    t = (await c.post(f"/api/sessions/{s['id']}/save-to-template", json={})).json()
    assert t["version"] == 2
    last = t["history"][-1]
    assert last["how"] == "from_shoot" and last["session_name"] == "Pegasus 42" and "+1 more" in last["summary"]
    st = (await c.get(f"/api/sessions/{s['id']}")).json()
    assert st["origin"]["changes"] == [] and st["origin"]["saved"]["version"] == 2
    (p,) = (await c.get("/api/projects")).json()
    shoe = next(x for x in p["templates"] if x["name"] == "Shoe review")
    assert shoe["shoot_count"] == 1 and shoe["last_used"] and p["shoot_count"] >= 1


async def test_editing_a_templates_shots_in_the_library_is_a_new_version(api):
    c, _h = api
    (p,) = (await c.get("/api/projects")).json()
    apparel = next(t for t in p["templates"] if t["name"] == "Apparel")
    full = (await c.get(f"/api/templates/{apparel['id']}")).json()
    shots = full["shots"]
    shots[0]["framing"] = "On a hanger, front"
    t = (await c.patch(f"/api/templates/{apparel['id']}", json={"shots": shots})).json()
    assert t["version"] == 2 and t["history"][-1]["how"] == "edited" and "Framing changed" in t["history"][-1]["summary"]
    same = (await c.patch(f"/api/templates/{apparel['id']}", json={"shots": t["shots"]})).json()
    assert same["version"] == 2   # no changes, no new version
    dup = (await c.post(f"/api/projects/{p['id']}/templates", json={"name": "Shorts", "copy_from": apparel["id"]})).json()
    assert dup["history"][0]["how"] == "duplicated" and "Apparel v2" in dup["history"][0]["summary"]


async def test_archived_projects_are_listed_but_their_templates_are_not(api):
    c, _h = api
    q = (await c.post("/api/projects", json={"name": "Race photos 2025"})).json()
    await c.post(f"/api/projects/{q['id']}/templates", json={"name": "Finish line"})
    await c.patch(f"/api/projects/{q['id']}", json={"archived": True})
    archived = next(x for x in (await c.get("/api/projects")).json() if x["id"] == q["id"])
    assert archived["archived"] is True and archived["templates"] == []
