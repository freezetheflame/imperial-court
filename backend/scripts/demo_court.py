#!/usr/bin/env python3
"""Real end-to-end demo: the court comes alive with real LLM agents.

Flow: emperor issues an edict → chancery agent (LLM) decomposes + dispatches
→ executor agent (LLM) runs + reports → chancery summarizes → memorial to
emperor. Uses the real DeepSeek API (backend/.env).

Usage:
    cd backend
    .venv/bin/python -m scripts.demo_court
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from imperial.agent.llm_client import LLMClient  # noqa: E402
from imperial.agent.loop import AgentLoop  # noqa: E402
from imperial.agent.scheduler import AgentScheduler  # noqa: E402
from imperial.agent.tools import build_tools  # noqa: E402
from imperial.api.bootstrap import build_context  # noqa: E402
from imperial.api.env import load_env  # noqa: E402
from imperial.bus import Message  # noqa: E402

load_env()

DEMO_DB = Path(__file__).resolve().parent.parent / "demo.db"


def make_llm(model: str | None = None) -> LLMClient:
    return LLMClient(model=model, max_tokens=1024, temperature=0.2)


async def main() -> None:
    print("═" * 60)
    print("朝堂 · 真实 agent 端到端演示")
    print("═" * 60)

    ctx = build_context(db_path=DEMO_DB, seed_posts=True)
    loops: dict[str, AgentLoop] = {}

    def loop_factory(post_id: str) -> AgentLoop:
        if post_id not in loops:
            post = ctx.institution.post(post_id)
            loops[post_id] = AgentLoop(
                institution=ctx.institution,
                tools=ctx.tools,
                llm=make_llm(post.model),
                engine=ctx.engine,
                max_turns=10,
            )
        return loops[post_id]

    scheduler = AgentScheduler(
        institution=ctx.institution,
        bus=ctx.bus,
        memorials=ctx.memorials,
        loop_factory=loop_factory,
    )
    await scheduler.start()

    # ── 1. emperor issues an edict ────────────────────────
    from imperial.court.edicts import EdictForm

    form = EdictForm(
        title="整理第三季度业绩报告",
        task_type="report_compile",
        description="收集各部门 Q3 数据，汇总成一份简洁的季度业绩报告，重点标注增长与下滑部门。",
        target="finance",
    )
    edict = await ctx.edicts.issue(form)
    print(f"\n🏛️  皇帝下旨：{form.title}")
    print(f"   {edict['formal_text']}")
    print(f"   (edict: {edict['id']})")

    # ── 2. drive the scheduler until a memorial reaches the emperor ──
    print("\n⏳ 朝堂运转中……（agent 正在用 DeepSeek 思考与行动）")

    # keep pumping until the chancery delivers a memorial that reflects the
    # executor's report (a chancery agent that only says "waiting" isn't final)
    final_memorial: dict | None = None
    for tick in range(120):  # up to 120 * 0.5s ≈ 60s
        await scheduler.pump_once()
        memorials = ctx.memorials.list()
        if memorials:
            full = ctx.memorials.get(memorials[0]["id"])
            if full and "等待" not in full["content"][:60]:
                final_memorial = memorials[0]
                break
        await asyncio.sleep(0.5)

    # give the executor's report time to land even if the chancery already
    # memorialized — let the agent network settle (finance needs a full
    # agent cycle: receive → run_task → report_result)
    for _ in range(40):
        await scheduler.pump_once()
        await asyncio.sleep(0.3)

    # ── 2b. audit the executor's activity ─────────────────
    fin_events = ctx.storage.get_events(post_id="finance", limit=30)
    fin_tools = [e for e in fin_events if e["kind"] == "tool_call"]
    print(f"\n📊 执行岗活动：{len(fin_events)} 条事件，{len(fin_tools)} 次工具调用")
    for e in fin_tools:
        print(f"   tool_call: {e['detail'].get('tool')} allowed={e['detail'].get('decision', {}).get('allowed')}")

    # ── 3. report ─────────────────────────────────────────
    memorials = ctx.memorials.list()
    if not memorials:
        print("\n⚠️  超时：未收到奏折。查看上方日志排查。")
        sys.exit(1)

    print("\n📜 皇帝收到奏折：")
    for m in memorials:
        full = ctx.memorials.get(m["id"])
        print(f"   ── {m['from_post']} 谨奏 ({m['status']}) ──")
        if full:
            print(f"   {full['content'][:500]}")

    # ── 4. emperor verdicts ───────────────────────────────
    m = memorials[0]
    decided = await ctx.memorials.verdict(m["id"], "approved", comment="准奏，办得不错。")
    print(f"\n✍️  皇帝批红：{decided['verdict']} → 状态 {decided['status']}")

    print("\n✅ 演示完成。事件流水：")
    for e in ctx.storage.get_events(limit=12):
        print(f"   [{e['kind']}] {e.get('post_id') or '-'} {str(e.get('detail'))[:80]}")

    # clean up demo db
    if DEMO_DB.exists():
        DEMO_DB.unlink()


if __name__ == "__main__":
    asyncio.run(main())
