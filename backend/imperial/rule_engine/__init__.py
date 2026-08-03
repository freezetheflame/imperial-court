"""Rule engine — the single arbiter of what is allowed.

Deterministic adjudication only. Decisions that need judgement (severity,
impeachment recommendations) belong to the censorate agents, NOT here.

Interface: `judge(action, context) -> RuleDecision`.

Static rules are derived from the Institution (communication + tool
whitelists, memorial state machine). Dynamic policy functions can be
registered for rules that need more than a lookup.

Deep module: callers only see judge(); they never know whether a rule was
a whitelist lookup or a policy function.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Protocol

from imperial.institution import Institution


@dataclass(frozen=True)
class RuleDecision:
    allowed: bool
    reason: str
    kind: str = "static"  # 'static' | 'policy'

    def as_dict(self) -> dict:
        return {"allowed": self.allowed, "reason": self.reason, "kind": self.kind}


class Action(Protocol):
    """A request to be adjudicated."""

    @property
    def kind(self) -> str: ...  # 'send_message' | 'call_tool' | 'transition_memorial'

    def as_dict(self) -> dict: ...


class SendMessageAction:
    kind = "send_message"

    def __init__(self, frm: str, to: str, msg_type: str):
        self.frm, self.to, self.msg_type = frm, to, msg_type

    def as_dict(self) -> dict:
        return {"kind": self.kind, "from": self.frm, "to": self.to, "type": self.msg_type}


class CallToolAction:
    kind = "call_tool"

    def __init__(self, post: str, tool: str):
        self.post, self.tool = post, tool

    def as_dict(self) -> dict:
        return {"kind": self.kind, "post": self.post, "tool": self.tool}


class TransitionMemorialAction:
    kind = "transition_memorial"

    def __init__(self, frm: str, to: str):
        self.frm, self.to = frm, to

    def as_dict(self) -> dict:
        return {"kind": self.kind, "from": self.frm, "to": self.to}


PolicyFn = Callable[[dict, Institution], RuleDecision]


class RuleEngine:
    """Adjudicates actions against an institution's rules."""

    def __init__(self, institution: Institution):
        self.institution = institution
        self._policies: dict[str, PolicyFn] = {}

    # ── policy registration (dynamic rules) ────────────────
    def register_policy(self, key: str, fn: PolicyFn) -> None:
        self._policies[key] = fn

    # ── single adjudication entry point ────────────────────
    def judge(self, action: Action, context: dict | None = None) -> RuleDecision:
        ctx = context or {}
        if isinstance(action, SendMessageAction):
            return self._judge_message(action, ctx)
        if isinstance(action, CallToolAction):
            return self._judge_tool(action, ctx)
        if isinstance(action, TransitionMemorialAction):
            return self._judge_transition(action, ctx)
        raise ValueError(f"unknown action kind: {getattr(action, 'kind', '?')}")

    # ── static adjudicators ────────────────────────────────
    def _judge_message(self, action: SendMessageAction, ctx: dict) -> RuleDecision:
        key = f"message:{action.frm}->{action.to}:{action.msg_type}"
        policy = self._policies.get(key)
        if policy is not None:
            d = policy(action.as_dict(), self.institution)
            return RuleDecision(d.allowed, d.reason, kind="policy")
        if self.institution.can_send(action.frm, action.to, action.msg_type):
            return RuleDecision(True, "communication whitelist allows")
        return RuleDecision(False, "not in communication whitelist")

    def _judge_tool(self, action: CallToolAction, ctx: dict) -> RuleDecision:
        key = f"tool:{action.post}:{action.tool}"
        policy = self._policies.get(key)
        if policy is not None:
            d = policy(action.as_dict(), self.institution)
            return RuleDecision(d.allowed, d.reason, kind="policy")
        if self.institution.can_call_tool(action.post, action.tool):
            return RuleDecision(True, "tool whitelist allows")
        return RuleDecision(False, "tool not in post's allowance")

    def _judge_transition(self, action: TransitionMemorialAction, ctx: dict) -> RuleDecision:
        allowed = action.to in self.institution.memorial_transitions.get(action.frm, ())
        if allowed:
            return RuleDecision(True, f"state transition {action.frm}->{action.to} allowed")
        return RuleDecision(False, f"state transition {action.frm}->{action.to} not allowed")

    # ── convenience: structured actions from dicts ─────────
    @staticmethod
    def action_from_dict(data: dict) -> Action:
        kind = data.get("kind")
        if kind == "send_message":
            return SendMessageAction(data["from"], data["to"], data["type"])
        if kind == "call_tool":
            return CallToolAction(data["post"], data["tool"])
        if kind == "transition_memorial":
            return TransitionMemorialAction(data["from"], data["to"])
        raise ValueError(f"unknown action kind: {kind}")
