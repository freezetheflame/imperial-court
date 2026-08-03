"""Institution loading and validation.

A institution is *data*: a YAML document defining posts, their tool
allowances, the communication protocol, and the memorial state machine.
Swapping institutions = swapping YAML files.

Deep module: load_institution() hides YAML parsing and schema validation
behind a small interface returning an Institution model.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


class InstitutionError(ValueError):
    """Raised when an institution definition is malformed."""


@dataclass(frozen=True)
class Post:
    id: str
    title: str
    role: str
    reports_to: str | None
    tool_allowance: tuple[str, ...]
    model: str | None = None


@dataclass(frozen=True)
class CommRule:
    frm: tuple[str, ...] | str  # 'emperor' | 'system' | ['finance', ...]
    to: tuple[str, ...] | str
    types: tuple[str, ...]


@dataclass(frozen=True)
class Institution:
    id: str
    name: str
    version: str
    posts: tuple[Post, ...]
    comm_rules: tuple[CommRule, ...]
    memorial_states: tuple[str, ...]
    memorial_transitions: dict[str, tuple[str, ...]]
    ui_config: dict[str, Any] = field(default_factory=dict)

    # ── lookups ────────────────────────────────────────────
    def post(self, post_id: str) -> Post:
        for p in self.posts:
            if p.id == post_id:
                return p
        raise KeyError(f"unknown post: {post_id}")

    def has_post(self, post_id: str) -> bool:
        return any(p.id == post_id for p in self.posts)

    def posts_by_role(self, role: str) -> tuple[Post, ...]:
        return tuple(p for p in self.posts if p.role == role)

    def can_send(self, frm: str, to: str, msg_type: str) -> bool:
        """Static communication whitelist check."""
        for rule in self.comm_rules:
            frm_ok = frm == rule.frm if isinstance(rule.frm, str) else frm in rule.frm
            to_ok = to == rule.to if isinstance(rule.to, str) else to in rule.to
            if frm_ok and to_ok and msg_type in rule.types:
                return True
        return False

    def can_call_tool(self, post_id: str, tool: str) -> bool:
        """Static tool whitelist check."""
        return tool in self.post(post_id).tool_allowance


_SPECIAL_ACTORS = {"emperor", "system", "any", "any_executor"}
_REQUIRED_POST_FIELDS = {"id", "title", "role", "reports_to", "tool_allowance"}
_VALID_ROLES = {"coordinator", "executor", "inspector", "inspector_assistant", "external"}


def load_institution(path: Path | str) -> Institution:
    """Load and validate an institution definition from YAML."""
    path = Path(path)
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise InstitutionError(f"institution file not found: {path}") from None
    except yaml.YAMLError as e:
        raise InstitutionError(f"invalid YAML in {path}: {e}") from e

    inst = raw.get("institution") if isinstance(raw, dict) else None
    if not isinstance(inst, dict):
        raise InstitutionError("missing top-level 'institution' mapping")

    inst_id = inst.get("id")
    if not isinstance(inst_id, str) or not inst_id:
        raise InstitutionError("institution.id must be a non-empty string")

    posts_raw = inst.get("posts")
    if not isinstance(posts_raw, list) or not posts_raw:
        raise InstitutionError("institution.posts must be a non-empty list")

    posts: list[Post] = []
    seen: set[str] = set()
    for pr in posts_raw:
        if not isinstance(pr, dict):
            raise InstitutionError(f"post entry must be a mapping, got {pr!r}")
        missing = _REQUIRED_POST_FIELDS - set(pr)
        if missing:
            raise InstitutionError(f"post {pr.get('id', '?')} missing fields: {sorted(missing)}")
        pid = pr["id"]
        if pid in seen:
            raise InstitutionError(f"duplicate post id: {pid}")
        seen.add(pid)
        if pr["role"] not in _VALID_ROLES:
            raise InstitutionError(f"post {pid} has invalid role: {pr['role']}")
        allowance = pr["tool_allowance"]
        if not isinstance(allowance, list) or not allowance or not all(isinstance(t, str) for t in allowance):
            raise InstitutionError(f"post {pid} tool_allowance must be a non-empty list of strings")
        reports_to = pr.get("reports_to")
        posts.append(
            Post(
                id=pid,
                title=pr["title"],
                role=pr["role"],
                reports_to=None if reports_to in (None, "", "emperor") else str(reports_to),
                tool_allowance=tuple(allowance),
                model=pr.get("model"),
            )
        )

    rules_raw = inst.get("communication_rules")
    if not isinstance(rules_raw, list):
        raise InstitutionError("institution.communication_rules must be a list")

    all_actors = set(seen) | _SPECIAL_ACTORS
    comm_rules: list[CommRule] = []
    for rr in rules_raw:
        if not isinstance(rr, dict):
            raise InstitutionError(f"communication rule must be a mapping: {rr!r}")
        for fld in ("from", "to"):
            val = rr.get(fld)
            refs = val if isinstance(val, list) else [val]
            if not refs or any(r not in all_actors for r in refs):
                raise InstitutionError(f"communication rule references unknown actor: {fld}={val!r}")
        types = rr.get("type")
        if not isinstance(types, list) or not types or not all(isinstance(t, str) for t in types):
            raise InstitutionError(f"communication rule type must be a non-empty list: {rr!r}")
        frm = tuple(rr["from"]) if isinstance(rr["from"], list) else rr["from"]
        to = tuple(rr["to"]) if isinstance(rr["to"], list) else rr["to"]
        comm_rules.append(CommRule(frm=frm, to=to, types=tuple(types)))

    sm = inst.get("memorial_state_machine")
    if not isinstance(sm, dict):
        raise InstitutionError("missing memorial_state_machine")
    states = sm.get("states")
    if not isinstance(states, list) or "submitted" not in states or "archived" not in states:
        raise InstitutionError("memorial_state_machine.states must include 'submitted' and 'archived'")
    transitions_raw = sm.get("transitions", {})
    if not isinstance(transitions_raw, dict):
        raise InstitutionError("memorial_state_machine.transitions must be a mapping")
    transitions: dict[str, tuple[str, ...]] = {
        s: tuple(transitions_raw.get(s, ())) for s in states
    }
    for s, targets in transitions.items():
        if not all(t in states for t in targets):
            raise InstitutionError(f"transition from {s} references unknown state")

    ui = inst.get("emperor_ui", {}) if isinstance(inst.get("emperor_ui"), dict) else {}

    return Institution(
        id=inst_id,
        name=str(inst.get("name", inst_id)),
        version=str(inst.get("version", "0.0.0")),
        posts=tuple(posts),
        comm_rules=tuple(comm_rules),
        memorial_states=tuple(states),
        memorial_transitions=transitions,
        ui_config=ui,
    )
