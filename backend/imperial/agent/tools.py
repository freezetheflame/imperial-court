"""Agent tools — the actual work tools available to posts.

These bind the court services + bus to the agent loop. Each tool is
registered in a ToolRegistry; the RuleEngine (via institution whitelist)
decides which posts may call which tool.

Tools that touch other posts (dispatch, report) go through the bus, so
the communication whitelist is enforced on top of the tool whitelist.
"""
from __future__ import annotations

from typing import Any

from imperial.agent.tool_registry import ToolRegistry
from imperial.bus import Bus
from imperial.court.appointments import AppointmentService
from imperial.court.memorials import MemorialService
from imperial.storage import Storage

JSON_OBJ = {"type": "object", "properties": {}, "additionalProperties": True}
STR_PROP = {"type": "string"}


def build_tools(
    *,
    bus: Bus,
    storage: Storage,
    memorials: MemorialService,
    appointments: AppointmentService,
) -> ToolRegistry:
    reg = ToolRegistry()

    # ── coordinator tools (chancery) ───────────────────────
    @reg.register(
        "decompose_task",
        "将上谕拆解为若干子任务，返回子任务清单",
        {
            "type": "object",
            "properties": {
                "edict_id": STR_PROP,
                "subtasks": {
                    "type": "array",
                    "items": {"type": "object", "properties": {"title": STR_PROP, "target": STR_PROP}},
                },
            },
            "required": ["edict_id", "subtasks"],
        },
    )
    def decompose_task(edict_id: str, subtasks: list[dict[str, Any]]) -> dict[str, Any]:
        storage.insert_event("decompose", "chancery", {"edict_id": edict_id, "subtasks": subtasks})
        return {"edict_id": edict_id, "subtasks": subtasks}

    @reg.register(
        "dispatch_task",
        "向执行岗分派子任务（通过消息总线，受通信白名单约束）",
        {
            "type": "object",
            "properties": {
                "edict_id": STR_PROP,
                "target": STR_PROP,
                "title": STR_PROP,
                "description": STR_PROP,
            },
            "required": ["edict_id", "target", "title", "description"],
        },
    )
    async def dispatch_task(edict_id: str, target: str, title: str, description: str) -> dict[str, Any]:
        ok, decision = await bus.post_message(
            "chancery", target, "task_assignment",
            payload={"edict_id": edict_id, "title": title, "description": description},
        )
        return {
            "dispatched": ok,
            "target": target,
            "reason": decision.reason if decision is not None else None,
        }

    # ── executor tools ─────────────────────────────────────
    @reg.register(
        "run_task",
        "执行任务本体（通用执行工具）",
        {
            "type": "object",
            "properties": {"task": STR_PROP, "detail": STR_PROP},
            "required": ["task"],
        },
    )
    def run_task(task: str, detail: str | None = None) -> dict[str, Any]:
        return {"task": task, "detail": detail, "executed": True}

    @reg.register(
        "report_result",
        "将任务结果呈报丞相（通过消息总线）",
        {
            "type": "object",
            "properties": {"edict_id": STR_PROP, "summary": STR_PROP, "detail": STR_PROP},
            "required": ["edict_id", "summary"],
        },
    )
    async def report_result(edict_id: str, summary: str, detail: str | None = None, _post_id: str | None = None) -> dict[str, Any]:
        # _post_id injected by AgentLoop from the post's identity
        frm = _post_id or "finance"
        ok, decision = await bus.post_message(
            frm, "chancery", "result",
            payload={"edict_id": edict_id, "summary": summary, "detail": detail},
        )
        return {"reported": ok, "reason": decision.reason if decision is not None else None}

    @reg.register(
        "review_output",
        "对成果进行质检复核，给出结论",
        {
            "type": "object",
            "properties": {"subject": STR_PROP, "conclusion": STR_PROP, "issues": STR_PROP},
            "required": ["subject", "conclusion"],
        },
    )
    def review_output(subject: str, conclusion: str, issues: str | None = None) -> dict[str, Any]:
        return {"subject": subject, "conclusion": conclusion, "issues": issues}

    @reg.register(
        "compose_message",
        "起草对外消息/文书",
        {
            "type": "object",
            "properties": {"audience": STR_PROP, "content": STR_PROP},
            "required": ["audience", "content"],
        },
    )
    def compose_message(audience: str, content: str) -> dict[str, Any]:
        return {"audience": audience, "content": content}

    # ── shared / inspector tools ───────────────────────────
    @reg.register(
        "query_events",
        "查询事件流/审计记录",
        {
            "type": "object",
            "properties": {"kind": STR_PROP, "post_id": STR_PROP, "limit": {"type": "integer"}},
        },
    )
    def query_events(kind: str | None = None, post_id: str | None = None, limit: int = 20) -> dict[str, Any]:
        rows = storage.get_events(kind=kind, post_id=post_id, limit=limit)
        return {"count": len(rows), "events": rows}

    @reg.register(
        "review_logs",
        "审查某岗位的履职记录（御史专用）",
        {
            "type": "object",
            "properties": {"post_id": STR_PROP},
            "required": ["post_id"],
        },
    )
    def review_logs(post_id: str) -> dict[str, Any]:
        rows = storage.get_events(post_id=post_id, limit=50)
        return {"post_id": post_id, "count": len(rows), "events": rows}

    @reg.register(
        "draft_impeachment",
        "起草弹劾奏章",
        {
            "type": "object",
            "properties": {
                "target_post": STR_PROP,
                "evidence": STR_PROP,
                "type": STR_PROP,
            },
            "required": ["target_post", "evidence"],
        },
    )
    def draft_impeachment(target_post: str, evidence: str, type: str = "tool_violation") -> dict[str, Any]:
        return {"target_post": target_post, "evidence": evidence, "type": type}

    @reg.register(
        "gather_evidence",
        "汇总证据（御史助手专用）",
        {
            "type": "object",
            "properties": {"target_post": STR_PROP},
            "required": ["target_post"],
        },
    )
    def gather_evidence(target_post: str) -> dict[str, Any]:
        rows = storage.get_events(post_id=target_post, limit=50)
        return {"target_post": target_post, "count": len(rows), "events": rows}

    @reg.register(
        "issue_warning",
        "对岗位执行留任警告（御史大夫自决，不需皇帝批准）",
        {
            "type": "object",
            "properties": {"post_id": STR_PROP, "reason": STR_PROP},
            "required": ["post_id", "reason"],
        },
    )
    def issue_warning(post_id: str, reason: str) -> dict[str, Any]:
        post = appointments.warn(post_id, reason=reason)
        return {"post_id": post_id, "status": post["status"]}

    @reg.register(
        "recommend_removal",
        "建议革职某岗位（需皇帝朱批后才执行）",
        {
            "type": "object",
            "properties": {"post_id": STR_PROP, "reason": STR_PROP},
            "required": ["post_id", "reason"],
        },
    )
    def recommend_removal(post_id: str, reason: str) -> dict[str, Any]:
        return {"post_id": post_id, "reason": reason, "recommended": True}

    return reg
