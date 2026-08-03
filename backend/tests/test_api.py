"""API layer tests — real HTTP requests against the FastAPI app.

Uses a temp DB per test; no network, no LLM.
"""
import asyncio

import pytest
from fastapi.testclient import TestClient

from imperial.api.main import create_app


@pytest.fixture
def client(tmp_path):
    app = create_app(db_path=tmp_path / "api.db", seed_posts=True, load_env_file=False)
    return TestClient(app)


def test_health(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    data = r.json()
    assert data["institution"] == "sanguan-jiuqing"
    assert data["posts"] == 8
    assert "scheduler" in data  # agent-network flag present (off in tests: no LLM key)


def test_posts_seeded(client):
    r = client.get("/api/posts")
    assert r.status_code == 200
    posts = r.json()
    assert len(posts) == 8
    titles = {p["title"] for p in posts}
    assert {"丞相", "御史大夫", "治粟内史"} <= titles


def test_create_edict_flow(client):
    r = client.post("/api/edicts", json={
        "title": "整理季度报告",
        "task_type": "report_compile",
        "description": "汇总 Q3 数据",
        "target": "finance",
    })
    assert r.status_code == 201
    edict = r.json()
    assert edict["id"].startswith("edict_")
    assert "奉天承运皇帝" in edict["formal_text"]

    # list + detail
    assert len(client.get("/api/edicts").json()) == 1
    detail = client.get(f"/api/edicts/{edict['id']}")
    assert detail.status_code == 200
    assert detail.json()["status"] == "pending"


def test_create_edict_missing_fields_400(client):
    # pydantic validation rejects missing required fields (422)
    r = client.post("/api/edicts", json={"title": "缺字段"})
    assert r.status_code == 422


def test_memorial_verdict_roundtrip(client):
    # seed a memorial directly via context
    ctx = client.app.state.ctx
    loop = asyncio.new_event_loop()
    try:
        m = loop.run_until_complete(ctx.memorials.submit(frm="chancery", content="谨奏"))
    finally:
        loop.close()

    r = client.get("/api/memorials")
    assert r.status_code == 200
    assert len(r.json()) == 1

    v = client.post(f"/api/memorials/{m['id']}/verdict", json={"verdict": "approved", "comment": "准"})
    assert v.status_code == 200
    assert v.json()["status"] == "approved"


def test_memorial_invalid_verdict_400(client):
    ctx = client.app.state.ctx
    loop = asyncio.new_event_loop()
    try:
        m = loop.run_until_complete(ctx.memorials.submit(frm="chancery", content="奏"))
    finally:
        loop.close()
    r = client.post(f"/api/memorials/{m['id']}/verdict", json={"verdict": "banish"})
    assert r.status_code == 400


def test_impeachment_verdict_flow(client):
    ctx = client.app.state.ctx
    loop = asyncio.new_event_loop()
    try:
        imp = loop.run_until_complete(
            ctx.impeachments.open(target_post="justice", evidence="越权", type_="tool_violation")
        )
        imp = loop.run_until_complete(
            ctx.impeachments.submit_recommendation(imp["id"], recommendation="removal", brief="证据确凿")
        )
    finally:
        loop.close()

    r = client.get("/api/impeachments")
    assert r.status_code == 200
    assert len(r.json()) == 1

    v = client.post(f"/api/impeachments/{imp['id']}/verdict", json={"verdict": "approve"})
    assert v.status_code == 200
    assert v.json()["status"] == "verdict_done"

    # post became vacant
    posts = client.get("/api/posts").json()
    justice = [p for p in posts if p["id"] == "justice"][0]
    assert justice["status"] == "vacant"


def test_appoint_vacant_post(client):
    ctx = client.app.state.ctx
    ctx.appointments.remove("finance", reason="test")
    r = client.post("/api/posts/finance/appoint", json={"agent": "agent_fin_2"})
    assert r.status_code == 200
    assert r.json()["status"] == "active"
    assert r.json()["current_agent"] == "agent_fin_2"


def test_censorate_overview(client):
    r = client.get("/api/censorate/overview")
    assert r.status_code == 200
    data = r.json()
    assert set(data) == {"pending_impeachments", "pending_verdicts", "recent_violations",
                         "warnings_issued", "removals"}


def test_events_query(client):
    r = client.get("/api/events?kind=edict")
    assert r.status_code == 200
    assert isinstance(r.json(), list)


def test_imperial_db_env_override(tmp_path, monkeypatch):
    """$IMPERIAL_DB env var must control the default DB path."""
    import imperial.api.bootstrap as b
    from imperial.api.main import create_app

    db_file = tmp_path / "env.db"
    monkeypatch.setenv("IMPERIAL_DB", str(db_file))
    app = create_app(seed_posts=False)
    assert app.state.ctx.storage.path == db_file
    # a write lands in the env-specified file
    app.state.ctx.storage.insert_event("test", None)
    assert db_file.exists()
