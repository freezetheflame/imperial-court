"""Post system prompts — the role definition each agent lives by.

These encode the institution's spirit at the prompt level. The hard
constraints (whitelists, routing) live in the rule engine; the prompt
shapes judgement within those rails. Role descriptions are DATA: they come
from the institution YAML (role_descriptions), so swapping institutions
swaps the role guidance with zero code change.
"""
from __future__ import annotations

from imperial.institution import Institution

_COMMON = """你是帝国朝堂中的「{title}」（岗位 id: {id}）。

## 铁律
1. 只使用你职权范围内的工具——规则引擎会拦截越权调用，被拒绝后不要强行重试。
2. 只按制度规定的通信链路行事，不得越级直奏皇帝。
3. 汇报要简洁、准确、按事实陈述。

## 你的岗位
{role_desc}

## 当前制度
{institution_desc}
"""


def _institution_desc(inst: Institution) -> str:
    posts = "、".join(f"{p.title}({p.id})" for p in inst.posts)
    return f"制度「{inst.name}」，在职岗位：{posts}。"


def build_system_prompt(post_id: str, inst: Institution) -> str:
    post = inst.post(post_id)
    role_desc = inst.role_descriptions.get(post.role) or _default_role_desc(post)
    return _COMMON.format(
        title=post.title,
        id=post.id,
        role_desc=role_desc,
        institution_desc=_institution_desc(inst),
    )


def _default_role_desc(post) -> str:
    return (
        f"你是{post.title}。按制度规定履行本职，完成任务后按汇报链路呈报，"
        "不得越权、不得越级。"
    )
