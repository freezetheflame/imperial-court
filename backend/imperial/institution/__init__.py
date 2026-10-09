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
class Hop:
    """A message hop: send a message type to a post when a stage advances."""
    to: str
    type: str


@dataclass(frozen=True)
class Fanout:
    """Fan-out: a dispatch stage sends one type to every post in 'to'."""
    to: tuple[str, ...]
    type: str


@dataclass(frozen=True)
class Terminal:
    """Terminal stage: the agent's text becomes a memorial to the emperor."""
    type: str  # 'memorial' | 'impeachment'
    on_tool: str | None = None  # only fire if the agent (allowed) called this tool


@dataclass(frozen=True)
class Stage:
    """One stage in a workflow: who acts, what capability, and where it leads."""
    id: str
    capability: str  # draft | review | dispatch | execute | aggregate | inspect
    post: str | None = None
    posts: tuple[str, ...] = ()
    next: Hop | None = None
    branches: dict[str, Hop] | None = None  # 'ok' | 'veto'
    fanout: Fanout | None = None
    report_to: str | None = None
    terminal: Terminal | None = None


@dataclass(frozen=True)
class Workflow:
    """How a decree (or inspection) flows through the court, as data."""
    name: str
    entry_from: str
    entry_to: str
    entry_type: str
    stages: tuple[Stage, ...]
    max_vetoes: int = 3

    def stage(self, stage_id: str) -> Stage:
        for s in self.stages:
            if s.id == stage_id:
                return s
        raise KeyError(f"unknown stage: {stage_id}")

    def entry_stage(self) -> Stage:
        return self.stages[0]

    def stage_by_capability(self, capability: str) -> Stage | None:
        for s in self.stages:
            if s.capability == capability:
                return s
        return None

    def terminal_stage(self) -> Stage | None:
        for s in self.stages:
            if s.terminal is not None:
                return s
        return None


@dataclass(frozen=True)
class CourtRoomConfig:
    """朝房集议配置：哪些岗位可入朝房、每议题轮次熔断、总开关。"""
    enabled: bool = False
    max_turns: int = 24
    participants: tuple[str, ...] = ()


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
    workflows: dict[str, Workflow] = field(default_factory=dict)
    role_descriptions: dict[str, str] = field(default_factory=dict)
    court_room: CourtRoomConfig = field(default_factory=CourtRoomConfig)
    censor_policy: dict[str, Any] = field(default_factory=dict)

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

    def workflow(self, name: str = "decree") -> Workflow:
        """Return a named workflow (e.g. 'decree' or 'inspection')."""
        if name not in self.workflows:
            raise KeyError(f"unknown workflow: {name}")
        return self.workflows[name]


_SPECIAL_ACTORS = {"emperor", "system", "any", "any_executor", "court_room"}
_REQUIRED_POST_FIELDS = {"id", "title", "role", "reports_to", "tool_allowance"}
# roles are descriptive (UI group + prompt key); the engine keys off Stage.capability
_VALID_ROLES = {
    "coordinator", "executor", "inspector", "inspector_assistant", "external",
    "drafter", "reviewer", "dispatcher", "domain_executor",
}
_VALID_CAPABILITIES = {"draft", "review", "dispatch", "execute", "aggregate", "inspect"}
_VALID_TERMINAL_TYPES = {"memorial", "impeachment"}


# ── workflow parsing ────────────────────────────────────────
def _parse_hop(raw: Any, wname: str, sid: str, field: str, all_posts: set[str]) -> Hop | None:
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise InstitutionError(f"workflow {wname} stage {sid} {field} must be a mapping")
    to, typ = raw.get("to"), raw.get("type")
    if not isinstance(to, str) or to not in all_posts:
        raise InstitutionError(f"workflow {wname} stage {sid} {field}.to references unknown post: {to!r}")
    if not isinstance(typ, str) or not typ:
        raise InstitutionError(f"workflow {wname} stage {sid} {field}.type must be a non-empty string")
    return Hop(to=to, type=typ)


def _parse_branches(raw: Any, wname: str, sid: str, all_posts: set[str]) -> dict[str, Hop] | None:
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise InstitutionError(f"workflow {wname} stage {sid} branches must be a mapping")
    if "ok" not in raw:
        raise InstitutionError(f"workflow {wname} stage {sid} branches requires 'ok'")
    branches: dict[str, Hop] = {}
    for key in ("ok", "veto"):
        if key in raw:
            branches[key] = _parse_hop(raw[key], wname, sid, f"branches.{key}", all_posts)
    return branches


def _parse_fanout(raw: Any, wname: str, sid: str, all_posts: set[str]) -> Fanout | None:
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise InstitutionError(f"workflow {wname} stage {sid} fanout must be a mapping")
    to, typ = raw.get("to"), raw.get("type")
    if not isinstance(to, list) or not to or any(t not in all_posts for t in to):
        raise InstitutionError(f"workflow {wname} stage {sid} fanout.to must be a non-empty list of known posts")
    if not isinstance(typ, str) or not typ:
        raise InstitutionError(f"workflow {wname} stage {sid} fanout.type must be a non-empty string")
    return Fanout(to=tuple(to), type=typ)


def _parse_terminal(raw: Any, wname: str, sid: str) -> Terminal | None:
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise InstitutionError(f"workflow {wname} stage {sid} terminal must be a mapping")
    typ = raw.get("type")
    if typ not in _VALID_TERMINAL_TYPES:
        raise InstitutionError(
            f"workflow {wname} stage {sid} terminal.type must be one of {sorted(_VALID_TERMINAL_TYPES)}"
        )
    on_tool = raw.get("on_tool")
    if on_tool is not None and (not isinstance(on_tool, str) or not on_tool):
        raise InstitutionError(f"workflow {wname} stage {sid} terminal.on_tool must be a non-empty string")
    return Terminal(type=typ, on_tool=on_tool)


def _parse_stage(wname: str, sr: dict, all_posts: set[str]) -> Stage:
    sid = sr.get("id")
    if not isinstance(sid, str) or not sid:
        raise InstitutionError(f"workflow {wname} stage missing id")
    capability = sr.get("capability")
    if capability not in _VALID_CAPABILITIES:
        raise InstitutionError(f"workflow {wname} stage {sid} invalid capability: {capability!r}")

    post = sr.get("post")
    posts = sr.get("posts")
    if (post is None) == (posts is None):
        raise InstitutionError(f"workflow {wname} stage {sid} must set exactly one of post/posts")
    if post is not None:
        if not isinstance(post, str) or post not in all_posts:
            raise InstitutionError(f"workflow {wname} stage {sid} post references unknown post: {post!r}")
    elif not isinstance(posts, list) or not posts or any(p not in all_posts for p in posts):
        raise InstitutionError(f"workflow {wname} stage {sid} posts must be a non-empty list of known posts")

    next_hop = _parse_hop(sr.get("next"), wname, sid, "next", all_posts)
    branches = _parse_branches(sr.get("branches"), wname, sid, all_posts)
    fanout = _parse_fanout(sr.get("fanout"), wname, sid, all_posts)
    terminal = _parse_terminal(sr.get("terminal"), wname, sid)

    report_to = sr.get("report_to")
    if report_to is not None and (not isinstance(report_to, str) or report_to not in all_posts):
        raise InstitutionError(f"workflow {wname} stage {sid} report_to references unknown post: {report_to!r}")

    # capability → required routing field
    if capability == "dispatch" and fanout is None:
        raise InstitutionError(f"workflow {wname} stage {sid} (dispatch) requires fanout")
    if capability == "execute" and report_to is None:
        raise InstitutionError(f"workflow {wname} stage {sid} (execute) requires report_to")
    if capability == "draft" and next_hop is None:
        raise InstitutionError(f"workflow {wname} stage {sid} (draft) requires next")
    if capability == "review" and branches is None:
        raise InstitutionError(f"workflow {wname} stage {sid} (review) requires branches")
    if capability in ("aggregate", "inspect") and terminal is None:
        raise InstitutionError(f"workflow {wname} stage {sid} ({capability}) requires terminal")

    return Stage(
        id=sid,
        capability=capability,
        post=post,
        posts=tuple(posts) if posts is not None else (),
        next=next_hop,
        branches=branches,
        fanout=fanout,
        report_to=report_to,
        terminal=terminal,
    )


def _parse_workflows(inst: dict, all_posts: set[str]) -> dict[str, Workflow]:
    raw = inst.get("workflows")
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise InstitutionError("institution.workflows must be a mapping")
    out: dict[str, Workflow] = {}
    for name, wf_raw in raw.items():
        if not isinstance(name, str) or not name:
            raise InstitutionError("workflow names must be non-empty strings")
        if not isinstance(wf_raw, dict):
            raise InstitutionError(f"workflow {name} must be a mapping")
        entry = wf_raw.get("entry")
        if not isinstance(entry, dict):
            raise InstitutionError(f"workflow {name} missing entry")
        entry_from, entry_to, entry_type = entry.get("from"), entry.get("to"), entry.get("type")
        if not all(isinstance(x, str) and x for x in (entry_from, entry_to, entry_type)):
            raise InstitutionError(f"workflow {name} entry requires from/to/type")
        if entry_to not in all_posts:
            raise InstitutionError(f"workflow {name} entry.to references unknown post: {entry_to!r}")

        stages_raw = wf_raw.get("stages")
        if not isinstance(stages_raw, list) or not stages_raw:
            raise InstitutionError(f"workflow {name} stages must be a non-empty list")
        seen: set[str] = set()
        stages: list[Stage] = []
        for sr in stages_raw:
            if not isinstance(sr, dict):
                raise InstitutionError(f"workflow {name} stage must be a mapping")
            sid = sr.get("id")
            if not isinstance(sid, str) or not sid or sid in seen:
                raise InstitutionError(f"workflow {name} has missing/duplicate stage id: {sid!r}")
            seen.add(sid)
            stages.append(_parse_stage(name, sr, all_posts))
        if stages[-1].terminal is None:
            raise InstitutionError(f"workflow {name} last stage must be terminal")

        max_vetoes = wf_raw.get("max_vetoes", 3)
        if not isinstance(max_vetoes, int) or max_vetoes < 0:
            raise InstitutionError(f"workflow {name} max_vetoes must be a non-negative int")

        out[name] = Workflow(
            name=name,
            entry_from=entry_from,
            entry_to=entry_to,
            entry_type=entry_type,
            stages=tuple(stages),
            max_vetoes=max_vetoes,
        )
    return out


def _parse_role_descriptions(inst: dict) -> dict[str, str]:
    raw = inst.get("role_descriptions")
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise InstitutionError("institution.role_descriptions must be a mapping")
    return {str(k): str(v) for k, v in raw.items()}


def _parse_court_room(inst: dict, all_posts: set[str]) -> CourtRoomConfig:
    """Parse the optional court_room section (朝房集议 / agent playground).

    Absent section → disabled config (default). Present but malformed →
    fail fast, consistent with the rest of the loader.
    """
    raw = inst.get("court_room")
    if raw is None:
        return CourtRoomConfig()
    if not isinstance(raw, dict):
        raise InstitutionError("institution.court_room must be a mapping")
    enabled = raw.get("enabled", True)
    if not isinstance(enabled, bool):
        raise InstitutionError("court_room.enabled must be a boolean")
    max_turns = raw.get("max_turns", 24)
    if not isinstance(max_turns, int) or max_turns < 1:
        raise InstitutionError("court_room.max_turns must be a positive int")
    participants = raw.get("participants", [])
    if not isinstance(participants, list) or any(p not in all_posts for p in participants):
        raise InstitutionError("court_room.participants must be a list of known posts")
    return CourtRoomConfig(enabled=enabled, max_turns=max_turns, participants=tuple(participants))


def _parse_censor_policy(inst: dict) -> dict[str, Any]:
    """Optional censor_policy section (Jev 式监察决策模型的阈值与权重).

    Kept as a raw validated mapping; CensorDecisionModel applies defaults
    for absent keys so institutions can override selectively.
    """
    raw = inst.get("censor_policy")
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise InstitutionError("institution.censor_policy must be a mapping")
    return dict(raw)


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

    workflows = _parse_workflows(inst, set(seen))
    role_descriptions = _parse_role_descriptions(inst)
    court_room = _parse_court_room(inst, set(seen))
    censor_policy = _parse_censor_policy(inst)

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
        workflows=workflows,
        role_descriptions=role_descriptions,
        court_room=court_room,
        censor_policy=censor_policy,
    )
