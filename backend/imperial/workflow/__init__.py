"""Workflow engine — executes the decree/inspection pipeline as data.

The institution YAML declares a workflow (entry, stages, fan-out, veto
branches, terminal memorial). This engine turns those declarations into
the actual message routing + aggregation that used to be hardcoded in
scheduler.py / tools.py / edicts.py (all keyed to 'chancery' / 'censor').

It is deliberately thin: the hard constraints (tool + communication
whitelists) still live in the rule engine; this module only advances the
workflow when an agent completes a stage.
"""
from __future__ import annotations

from typing import Any

from imperial.agent.tracker import TaskTracker
from imperial.bus import Bus
from imperial.institution import Fanout, Institution, Workflow


class WorkflowEngine:
    """Drives a workflow: entry routing, dispatch/report targets, aggregation,
    and the terminal memorial produced when a stage completes."""

    def __init__(
        self,
        *,
        institution: Institution,
        bus: Bus,
        memorials: Any,
        edicts: Any | None = None,
        tracker: TaskTracker | None = None,
    ):
        self.institution = institution
        self.bus = bus
        self.memorials = memorials
        self.edicts = edicts
        self.tracker = tracker or TaskTracker()
        # aggregation is driven by the workflow: rewire the tracker callback
        self.tracker.on_all_complete = self._on_all_complete

    # ── workflow lookup ────────────────────────────────────
    def workflow(self, name: str = "decree") -> Workflow:
        return self.institution.workflow(name)

    # ── entry (edicts.issue) ───────────────────────────────
    async def start_edict(self, edict_id: str, payload: dict) -> None:
        wf = self.workflow("decree")
        await self.bus.post_message(wf.entry_from, wf.entry_to, wf.entry_type, payload)

    # ── routing lookups (used by tools) ────────────────────
    def dispatch_fanout(self) -> Fanout:
        stage = self.workflow("decree").stage_by_capability("dispatch")
        if stage is None or stage.fanout is None:
            raise KeyError("decree workflow has no dispatch stage")
        return stage.fanout

    def dispatch_post(self) -> str:
        stage = self.workflow("decree").stage_by_capability("dispatch")
        if stage is None or stage.post is None:
            raise KeyError("decree workflow has no dispatch stage")
        return stage.post

    def report_target(self) -> str:
        stage = self.workflow("decree").stage_by_capability("execute")
        if stage is None or stage.report_to is None:
            raise KeyError("decree workflow has no execute stage")
        return stage.report_to

    def aggregate_post(self) -> str:
        stage = self.workflow("decree").stage_by_capability("aggregate")
        if stage is None or stage.post is None:
            raise KeyError("decree workflow has no aggregate stage")
        return stage.post

    # ── draft / review transitions (e.g. 三省六部) ─────────
    async def submit_draft(self, edict_id: str, draft_text: str, _post_id: str) -> dict:
        wf = self.workflow("decree")
        stage = wf.stage_by_capability("draft")
        if stage is None or stage.next is None:
            return {"error": "decree workflow has no draft stage"}
        ok, decision = await self.bus.post_message(
            _post_id or stage.post, stage.next.to, stage.next.type,
            payload={"edict_id": edict_id, "draft": draft_text},
        )
        return {"submitted": ok, "reason": decision.reason if decision is not None else None}

    async def approve(self, edict_id: str, reason: str, _post_id: str) -> dict:
        wf = self.workflow("decree")
        stage = wf.stage_by_capability("review")
        if stage is None or stage.branches is None or "ok" not in stage.branches:
            return {"error": "decree workflow has no review stage with an 'ok' branch"}
        hop = stage.branches["ok"]
        ok, decision = await self.bus.post_message(
            _post_id or stage.post, hop.to, hop.type,
            payload={"edict_id": edict_id, "reason": reason},
        )
        return {"approved": ok, "reason": decision.reason if decision is not None else None}

    async def veto(self, edict_id: str, reason: str, _post_id: str) -> dict:
        wf = self.workflow("decree")
        stage = wf.stage_by_capability("review")
        if stage is None or stage.branches is None or "veto" not in stage.branches:
            return {"error": "decree workflow has no review stage with a 'veto' branch"}
        hop = stage.branches["veto"]
        ok, decision = await self.bus.post_message(
            _post_id or stage.post, hop.to, hop.type,
            payload={"edict_id": edict_id, "reason": reason},
        )
        return {"vetoed": ok, "reason": decision.reason if decision is not None else None}

    # ── scheduler routing hint ─────────────────────────────
    def should_run(self, post_id: str, msg_type: str) -> bool:
        """Whether an incoming message should launch the post's agent.

        The aggregate post swallows individual 'result' messages (their
        completion is tracked by the tracker); only the synthetic 'aggregate'
        message triggers the summarizing run.
        """
        wf = self.institution.workflows.get("decree")
        if wf is None:
            return True
        agg = wf.stage_by_capability("aggregate")
        if agg is not None and post_id == agg.post and msg_type == "result":
            return False
        return True

    # ── aggregation ────────────────────────────────────────
    async def _on_all_complete(self, edict_id: str) -> None:
        """All subtasks done → persist + tell the aggregate post to summarize."""
        if self.edicts is not None:
            self.edicts.mark_completed(edict_id)
        prog = self.tracker.progress(edict_id)
        summaries = prog.summaries() if prog else []
        await self.bus.post_message(
            "system", self.aggregate_post(), "aggregate",
            payload={"edict_id": edict_id, "summaries": summaries},
        )

    # ── agent-done hook (scheduler) ────────────────────────
    async def on_agent_done(self, post_id: str, msg: Any, result: Any) -> None:
        """Route the outcome of a finished agent run per the workflow."""
        edict_id = msg.payload.get("edict_id") if msg.payload else None
        # decree aggregate stage → memorial to the emperor
        wf = self.institution.workflows.get("decree")
        if wf is not None:
            agg = wf.stage_by_capability("aggregate")
            if agg is not None and post_id == agg.post and msg.type == "aggregate":
                await self.memorials.submit(
                    frm=post_id,
                    content=result.content,
                    edict_id=edict_id,
                )
                return
        # inspection terminal (e.g. recommend_removal → impeachment memorial)
        await self._maybe_inspect_terminal(post_id, msg, result)

    async def _maybe_inspect_terminal(self, post_id: str, msg: Any, result: Any) -> None:
        insp = self.institution.workflows.get("inspection")
        if insp is None:
            return
        term = insp.terminal_stage()
        if term is None or term.post != post_id or term.terminal is None:
            return
        if msg.type != insp.entry_type:
            return
        on_tool = term.terminal.on_tool
        if on_tool is None:
            return
        for tc in result.tool_calls:
            if tc.name == on_tool and tc.allowed:
                # Jev gate: when the tool carries a decision-model verdict,
                # the impeachment is filed only if the model approved filing
                # (dismissed/downgraded cases must not reach the emperor).
                if isinstance(tc.result, dict) and "recommended" in tc.result and not tc.result["recommended"]:
                    return
                await self.memorials.submit(
                    frm=post_id,
                    content=f"弹劾{tc.arguments.get('post_id')}：{tc.arguments.get('reason', '')}",
                    msg_type="impeachment",
                )
                return
