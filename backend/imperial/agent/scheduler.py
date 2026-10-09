"""AgentScheduler — turns the bus into a living agent network.

Each post has an agent worker that subscribes to its inbox. When a message
arrives, the worker hands it to AgentLoop as a task; the loop's tool calls
(dispatch/report) flow back through the bus to other posts' inboxes, so a
single edict fans out into a full court process.

The *workflow* (which post dispatches, which executors report to whom, who
aggregates, who memorializes) is data, not code: the WorkflowEngine reads it
from the institution YAML. The scheduler only runs agents and hands each
finished run back to the engine to route the next step.

Design notes:
- Workers are single-flight per post: while a post's agent is running, new
  messages for it are requeued (never dropped) and retried on a later pump.
- Different posts run in PARALLEL: dispatch starts the agent as a task and
  the pump moves on to other inboxes; pump_once() awaits the tasks it
  started so tests keep their synchronous feel.
- The scheduler is async and driven by an explicit pump(); tests drive it
  with pump_once(), production with a background task.
"""
from __future__ import annotations

import asyncio
from typing import Any

from imperial.agent.llm_client import LLMError
from imperial.agent.loop import AgentLoop
from imperial.agent.prompts import build_system_prompt
from imperial.bus import Bus, Message
from imperial.court.memorials import MemorialService
from imperial.institution import Institution
from imperial.workflow import WorkflowEngine


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
        engine: WorkflowEngine | None = None,
    ):
        self.institution = institution
        self.bus = bus
        self.memorials = memorials
        self.loop_factory = loop_factory
        self.edicts = edicts
        self._running: set[str] = set()
        self._pending: set[asyncio.Task] = set()
        self._system_prompts = {
            p.id: build_system_prompt(p.id, institution) for p in institution.posts
        }
        self._posts = posts or [p.id for p in institution.posts]
        # workflow engine: aggregation + terminal memorials, driven by data
        self.engine = engine or WorkflowEngine(
            institution=institution, bus=bus, memorials=memorials,
            edicts=edicts, tracker=tracker,
        )
        self.tracker = self.engine.tracker

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
        """Route an inbox message to the agent, unless the workflow says to
        swallow it (e.g. individual results at the aggregate post).

        Busy posts get their message requeued (not dropped); vacant posts
        (革职后空缺) are skipped and audited — a dismissed agent never runs.
        """
        if not self.engine.should_run(post_id, msg.type):
            return
        if not self.bus.engine.post_active(post_id):
            self.bus.storage.insert_event(
                "agent_skipped", post_id,
                {"reason": "post vacant (职权中止)", "msg_type": msg.type, "frm": msg.frm},
            )
            return
        if post_id in self._running:
            await self.bus.requeue(post_id, msg)
            return
        self._running.add(post_id)
        task = asyncio.create_task(self._run_agent(post_id, msg))
        self._pending.add(task)
        task.add_done_callback(self._pending.discard)

    # ── agent execution ────────────────────────────────────
    async def _run_agent(self, post_id: str, msg: Message) -> None:
        try:
            loop = self.loop_factory(post_id)
            # wire the bus audit trail into the agent's tool executions
            if loop.auditor is None:
                loop.auditor = lambda p, t, a, r, **kw: self.bus.audit_tool_call(p, t, a, r)
            task = self._render_task(msg)
            try:
                result = await loop.run(post_id, self._system_prompts[post_id], task)
            except LLMError as e:
                # degraded: LLM retries exhausted — audit and skip routing so
                # a failure string never becomes a memorial; the message is
                # consumed, but inquire_progress can re-urge the workflow.
                self.bus.storage.insert_event(
                    "llm_failure", post_id,
                    {"error": str(e), "msg_type": msg.type, "frm": msg.frm},
                )
                return
            await self.engine.on_agent_done(post_id, msg, result)
        except Exception as e:  # noqa: BLE001 — a crashing agent must not kill the pump
            self.bus.storage.insert_event(
                "agent_error", post_id,
                {"error": str(e), "msg_type": msg.type, "frm": msg.frm},
            )
        finally:
            self._running.discard(post_id)

    def _render_task(self, msg: Message) -> str:
        payload = msg.payload or {}
        lines = [f"收到消息（类型: {msg.type}，来自: {msg.frm}）："]
        for k, v in payload.items():
            lines.append(f"- {k}: {v}")
        return "\n".join(lines)

    # ── pump ───────────────────────────────────────────────
    async def pump_once(self) -> None:
        """Pump until quiescent: deliver → await the agent runs started
        during delivery → repeat while new messages arrived. Different
        posts' agents run concurrently; callers (tests) keep synchronous,
        whole-cascade semantics."""
        while True:
            await self.bus.pump_once()
            pending = [t for t in self._pending if not t.done()]
            if pending:
                await asyncio.gather(*pending, return_exceptions=True)
            if not self.bus.has_queued_messages():
                break

    async def pump(self) -> None:
        while True:
            await self.pump_once()
            await asyncio.sleep(0.05)
