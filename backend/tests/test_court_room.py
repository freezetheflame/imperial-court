"""朝房集议（court room playground）tests — service, bus fan-out, fuse, API."""
import pytest
from fastapi.testclient import TestClient

from imperial.api.main import create_app
from imperial.bus import Bus
from imperial.court.discussion import CourtRoomError, CourtRoomService
from imperial.rule_engine import RuleEngine


@pytest.fixture
def room(institution, storage):
    engine = RuleEngine(institution)
    bus = Bus(institution, storage, engine)
    service = CourtRoomService(storage=storage, bus=bus, institution=institution)
    return {"service": service, "bus": bus, "storage": storage, "institution": institution}


# ── service behavior ─────────────────────────────────────
async def test_open_and_speak_persists(room):
    svc = room["service"]
    thread = await svc.open_thread(topic="是否加征盐铁税", opened_by="emperor")
    assert thread["id"].startswith("ct_")
    assert thread["status"] == "open"

    msg = await svc.speak(thread_id=thread["id"], frm="finance", content="臣以为不可，民力已竭。")
    assert msg["delivered"] is True
    assert msg["turn"] == 1

    full = svc.get_thread(thread["id"])
    assert full is not None
    assert len(full["messages"]) == 1
    assert full["messages"][0]["frm"] == "finance"
    assert full["turns"] == 1


async def test_speak_fans_out_to_participants_except_speaker(room):
    svc, bus = room["service"], room["bus"]
    # subscribe inboxes for two participants
    got: dict[str, list] = {"justice": [], "censor": []}
    for pid in got:
        await bus.subscribe(pid, lambda m, pid=pid: got[pid].append(m))  # type: ignore[misc]

    thread = await svc.open_thread(topic="军备整饬", opened_by="grand_commandant")
    await svc.speak(thread_id=thread["id"], frm="grand_commandant", content="北疆骑兵需添马三千。")

    # raw fan-out already queued the copies (no pump needed for queue arrival)
    assert bus._inboxes["justice"].qsize() == 1
    assert bus._inboxes["censor"].qsize() == 1
    # speaker does NOT receive their own speech
    assert bus._inboxes.get("grand_commandant") is None or bus._inboxes["grand_commandant"].qsize() == 0
    msg = bus._inboxes["justice"].get_nowait()
    assert msg.type == "discuss"
    assert msg.payload["topic"] == "军备整饬"
    assert msg.payload["speaker"] == "grand_commandant"


async def test_non_participant_rejected(room):
    svc = room["service"]
    thread = await svc.open_thread(topic="宫禁守卫", opened_by="emperor")
    with pytest.raises(CourtRoomError, match="不在朝房参与者之列"):
        await svc.speak(thread_id=thread["id"], frm="censor_assistant", content="我也想议。")
    with pytest.raises(CourtRoomError, match="不在朝房参与者之列"):
        await svc.open_thread(topic="越俎代庖", opened_by="censor_assistant")


async def test_turn_budget_fuse_closes_thread(room):
    svc = room["service"]
    assert svc.max_turns == 24  # from sanguan-jiuqing.yaml
    thread = await svc.open_thread(topic="持久战议题", opened_by="emperor")
    for i in range(24):
        msg = await svc.speak(thread_id=thread["id"], frm="chancery", content=f"第{i + 1}轮。")
    assert msg["thread_closed"] is True
    closed = svc.get_thread(thread["id"])
    assert closed is not None and closed["status"] == "closed"
    assert closed["closed_at"] is not None
    # closed thread rejects further speech
    with pytest.raises(CourtRoomError, match="议题已闭"):
        await svc.speak(thread_id=thread["id"], frm="justice", content="还有话说。")


async def test_disabled_room_rejects(room, monkeypatch):
    monkeypatch.setenv("IMPERIAL_COURT_ROOM", "0")
    svc = room["service"]
    assert svc.enabled is False
    with pytest.raises(CourtRoomError, match="朝房已闭"):
        await svc.open_thread(topic="开不了", opened_by="emperor")


async def test_bus_post_to_room_blocked_sender_forwards_violation(room):
    """非白名单发言者 → 总线拦截 + 违制记录上报御史台。"""
    bus, storage = room["bus"], room["storage"]
    # censor_assistant is NOT in the court_room comm whitelist
    ok, decision = await bus.post_to_room(
        "censor_assistant", "court_room", "discuss",
        {"content": "x"}, recipients=["censor"],
    )
    assert ok is False
    assert decision is not None and not decision.allowed
    blocked = storage.get_events(kind="message_blocked", post_id="censor_assistant")
    assert len(blocked) == 1


# ── scheduler cascade: agents react to room speeches ─────
async def test_discuss_cascades_through_scheduler(institution, storage):
    """朝房发言 → fan-out → 参与者 agent 被唤醒并回应 → 轮次递增。

    FakeLLM 让 finance 回一言、justice 默然（不调用工具）；
    验证 discuss 消息确实驱动 agent 网络，且 thread_id 透传。
    """
    from imperial.agent.loop import AgentLoop
    from imperial.agent.scheduler import AgentScheduler
    from imperial.agent.tools import build_tools
    from imperial.agent.tracker import TaskTracker
    from imperial.court.appointments import AppointmentService
    from imperial.court.memorials import MemorialService
    from tests.fake_llm import FakeLLM

    engine = RuleEngine(institution)
    bus = Bus(institution, storage, engine)
    appointments = AppointmentService(storage)
    memorials = MemorialService(storage, bus, institution, engine)
    court = CourtRoomService(storage=storage, bus=bus, institution=institution)
    tools = build_tools(
        bus=bus, storage=storage, memorials=memorials, appointments=appointments,
        tracker=TaskTracker(), court=court,
    )

    fake_llms: dict[str, FakeLLM] = {}

    def loop_factory(post_id: str) -> AgentLoop:
        fake = fake_llms.setdefault(post_id, FakeLLM(script=[{"content": "臣无异议。"}]))
        return AgentLoop(institution=institution, tools=tools, llm=fake, engine=engine, max_turns=3)  # type: ignore[arg-type]

    scheduler = AgentScheduler(
        institution=institution, bus=bus, memorials=memorials,
        loop_factory=loop_factory, tracker=TaskTracker(),
    )
    await scheduler.start()

    thread = await court.open_thread(topic="河工银两", opened_by="emperor")

    # finance 有话要说（回一言后收尾）；其他岗位默认剧本不进言
    fake_llms["finance"] = FakeLLM(script=[
        {"tool_calls": [{"name": "speak_in_court", "arguments": {"thread_id": thread["id"], "content": "臣请拨内帑三万。"}}]},
        {"content": "已进言。"},
    ])
    # 重开 scheduler 的 loop 缓存：loop_factory 按需取 fake_llms，无需处理

    # 皇帝御言 → fan-out → 百官被唤醒（finance 回言 → 再 fan-out → 再唤醒……）
    await court.speak(thread_id=thread["id"], frm="emperor", content="河工银两，众卿何见？")
    await scheduler.pump_once()

    full = court.get_thread(thread["id"])
    assert full is not None
    frms = [m["frm"] for m in full["messages"]]
    assert "emperor" in frms
    # finance 的回应已进议题（轮次 > 1 证明级联发生）
    assert full["turns"] > 1
    assert "finance" in frms

    # 轮次始终受熔断约束（自由讨论但不会失控）
    assert full["turns"] <= court.max_turns


# ── API ──────────────────────────────────────────────────
@pytest.fixture
def client(tmp_path):
    app = create_app(db_path=tmp_path / "api.db", seed_posts=True, load_env_file=False)
    return TestClient(app)


def test_api_court_room_flow(client):
    r = client.get("/api/court")
    assert r.status_code == 200
    state = r.json()
    assert state["enabled"] is True
    assert "chancery" in state["participants"]
    assert "censor_assistant" not in state["participants"]

    r = client.post("/api/court/threads", json={"topic": "边关军粮调配"})
    assert r.status_code == 201
    thread = r.json()
    assert thread["opened_by"] == "emperor"

    r = client.post(f"/api/court/threads/{thread['id']}/speak", json={"content": "众卿以为如何？"})
    assert r.status_code == 200
    assert r.json()["delivered"] is True

    r = client.get(f"/api/court/threads/{thread['id']}")
    assert r.status_code == 200
    msgs = r.json()["messages"]
    assert len(msgs) == 1 and msgs[0]["frm"] == "emperor"

    # unknown thread → 404
    assert client.get("/api/court/threads/ct_nope").status_code == 404
