"""AgentScheduler — turns the bus into a living agent network.

Each post has an agent worker that subscribes to its inbox. When a message
arrives, the worker hands it to AgentLoop as a task; the loop's tool calls
(dispatch/report) flow back through the bus to other posts' inboxes, so a
single edict fans out into a full court process.

Design notes:
- Workers are single-flight per post: while a post's agent is running, new
  messages queue in its inbox and are processed on the next pump.
- The scheduler is async and driven by an explicit `pump()`; tests drive it
  with pump_once(), production with a background task.
- Messages that are *results of the agent's own tools* are not re-fed to the
  same agent (the loop already saw the tool result inline).
"""
from __future__ import annotations

import asyncio
from typing import Any

from imperial.agent.loop import AgentLoop
from imperial.agent.prompts import build_system_prompt
from imperial.bus import Bus, Message
from imperial.court.memorials import MemorialService
from imperial.institution import Institution


class AgentScheduler:
    """Runs agent workers per post, driven by bus messages."""

    def __init__(
        self,
        *,
        institution: Institution,
        bus: Bus,
        memorials: MemorialService,
        loop_factory: Any,  # (post_id) -> AgentLoop, injected for testability
        posts: list[str] | None = None,
        tracker: Any | None = None,  # TaskTracker shared with tools
        edicts: Any | None = None,  # EdictService — persists completion
    ):
        self.institution = institution
        self.bus = bus
        self.memorials = memorials
        self.loop_factory = loop_factory
        self.edicts = edicts
        self._running: set[str] = set()
        self._system_prompts = {
            p.id: build_system_prompt(p.id, institution) for p in institution.posts
        }
        self._posts = posts or [p.id for p in institution.posts]
        # multi-task aggregation: when an edict's subtasks all complete,
        # drive the chancery to produce ONE aggregate memorial
        from imperial.agent.tracker import TaskTracker

        self.tracker = tracker or TaskTracker(on_all_complete=self._on_edict_complete)
        # rewire callback so it fires regardless of who created the tracker
        self.tracker.on_all_complete = self._on_edict_complete

    # ── aggregation callback ──────────────────────────────
    async def _on_edict_complete(self, edict_id: str) -> None:
        """All subtasks of an edict are done → chancery summarizes once."""
        prog = self.tracker.progress(edict_id)
        summaries = prog.summaries() if prog else []
        if self.edicts is not None:
            self.edicts.mark_completed(edict_id)  # persist across restarts
        await self.bus.post_message(
            "system", "chancery", "aggregate",
            payload={"edict_id": edict_id, "summaries": summaries},
        )

    # ── wiring ─────────────────────────────────────────────
    async def start(self) -> None:
        """Subscribe every post's worker to its inbox."""
        for post_id in self._posts:
            await self.bus.subscribe(post_id, self._make_handler(post_id))

    def _make_handler(self, post_id: str):
        async def handler(msg: Message) -> None:
            await self._dispatch(post_id, msg)

        return handler

    # ── message routing ────────────────────────────────────
    async def _dispatch(self, post_id: str, msg: Message) -> None:
        """Route an inbox message to the agent (or handle it directly)."""
        # the censorate's violation_records become impeachment cases
        if post_id == "censor" and msg.type == "violation_record":
            await self._handle_violation(msg)
            return
        # chancery aggregate: all subtasks done → summarize → ONE memorial
        if post_id == "chancery" and msg.type == "aggregate":
            await self._run_agent(post_id, msg)
            return
        # executor results accumulate at the chancery (aggregation handled
        # by the tracker; individual results do NOT trigger a memorial)
        if post_id == "chancery" and msg.type == "result":
            return

        await self._run_agent(post_id, msg)

    # ── agent execution ────────────────────────────────────
    async def _run_agent(self, post_id: str, msg: Message) -> None:
        if post_id in self._running:
            return  # single-flight: skip while busy (message stays queued)
        self._running.add(post_id)
        try:
            loop = self.loop_factory(post_id)
            # wire the bus audit trail into the agent's tool executions
            if loop.auditor is None:
                loop.auditor = lambda p, t, a, r, **kw: self.bus.audit_tool_call(p, t, a, r)
            task = self._render_task(msg)
            result = await loop.run(post_id, self._system_prompts[post_id], task)
            await self._post_agent_action(post_id, msg, result)
        finally:
            self._running.discard(post_id)

    def _render_task(self, msg: Message) -> str:
        payload = msg.payload or {}
        lines = [f"收到消息（类型: {msg.type}，来自: {msg.frm}）："]
        for k, v in payload.items():
            lines.append(f"- {k}: {v}")
        return "\n".join(lines)

    async def _post_agent_action(self, post_id: str, msg: Message, result: Any) -> None:
        """After an agent run, decide whether a memorial to the emperor is due."""
        # chancery memorializes once, when all subtasks have aggregated.
        if post_id == "chancery" and msg.type == "aggregate":
            await self.memorials.submit(
                frm="chancery",
                content=result.content,
                edict_id=msg.payload.get("edict_id") if msg.payload else None,
            )
        # censor issuing a removal recommendation → impeachment memorial
        if post_id == "censor":
            for tc in result.tool_calls:
                if tc.name == "recommend_removal" and tc.allowed:
                    await self.memorials.submit(
                        frm="censor",
                        content=f"弹劾{tc.arguments.get('post_id')}：{tc.arguments.get('reason', '')}",
                        msg_type="impeachment",
                    )

    # ── direct handlers ────────────────────────────────────
    async def _handle_violation(self, msg: Message) -> None:
        """A violation_record lands in the censorate: open an impeachment case."""
        p = msg.payload or {}
        # delegate to the censor agent to investigate & recommend
        await self._run_agent("censor", msg)

    # ── pump ───────────────────────────────────────────────
    async def pump_once(self) -> None:
        await self.bus.pump_once()

    async def pump(self) -> None:
        while True:
            await self.pump_once()
            await asyncio.sleep(0.05)
