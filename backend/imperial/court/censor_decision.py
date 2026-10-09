"""Censor decision model — Jev 式监察裁决层（概率评分卡 + 审计摘要）。

Design split (感知 / 裁决分离):
- The censor LLM investigates: gathers evidence, reads logs, and self-rates
  a confidence in [0, 1] that the violation is real and attributable.
- THIS model adjudicates: a deterministic scoring card maps features to a
  probability distribution over {dismiss, warning, removal}; thresholds
  decide the recommendation. The LLM never picks the sanction directly.

Why: sanctions must be reproducible, testable, and explainable. Same
philosophy as the rule engine — 裁决不交 LLM. Every decision emits a
feature-contribution breakdown (audit summary) so the emperor and the
censorate can see *why*.

Model (three-class softmax over a severity logit z):

    z = bias
      + severity_weight[type] * confidence        (感知强度)
      + prior_violation_weight * log1p(priors)    (累犯)
      + prior_warning_weight  * log1p(warnings)   (屡教不改)
      + repeat_bonus * repeat_offender            (重犯加成)

    s_dismiss = -z, s_removal = z, s_warning = -steepness * |z|
    P = softmax(s_dismiss, s_warning, s_removal)

Decision rule (on probabilities, not the raw logit):
    P(removal)            >= removal_threshold → removal
    1 - P(dismiss)        >= warn_threshold    → warning
    otherwise                                 → dismiss

All weights/thresholds come from the institution YAML `censor_policy`
section; absent keys fall back to the defaults below.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

RECOMMENDATIONS = ("dismiss", "warning", "removal")

DEFAULT_SEVERITY_WEIGHTS: dict[str, float] = {
    "tool_violation": 1.6,      # 越权用器
    "comm_violation": 1.3,      # 违制通信
    "dereliction": 1.0,         # 失职
    "court_misconduct": 0.8,    # 朝房失仪
}
DEFAULT_SEVERITY_FALLBACK = 1.0


@dataclass(frozen=True)
class CensorPolicy:
    severity_weights: dict[str, float] = field(default_factory=lambda: dict(DEFAULT_SEVERITY_WEIGHTS))
    severity_fallback: float = DEFAULT_SEVERITY_FALLBACK
    warn_threshold: float = 0.35
    removal_threshold: float = 0.62
    prior_violation_weight: float = 0.55
    prior_warning_weight: float = 0.75
    repeat_bonus: float = 0.60
    bias: float = -1.40
    steepness: float = 1.5

    @classmethod
    def from_dict(cls, raw: dict[str, Any] | None) -> "CensorPolicy":
        if not raw:
            return cls()
        weights = raw.get("severity_weights")
        merged = dict(DEFAULT_SEVERITY_WEIGHTS)
        if isinstance(weights, dict):
            merged.update({str(k): float(v) for k, v in weights.items()})
        return cls(
            severity_weights=merged,
            severity_fallback=float(raw.get("severity_fallback", DEFAULT_SEVERITY_FALLBACK)),
            warn_threshold=float(raw.get("warn_threshold", 0.35)),
            removal_threshold=float(raw.get("removal_threshold", 0.62)),
            prior_violation_weight=float(raw.get("prior_violation_weight", 0.55)),
            prior_warning_weight=float(raw.get("prior_warning_weight", 0.75)),
            repeat_bonus=float(raw.get("repeat_bonus", 0.60)),
            bias=float(raw.get("bias", -1.40)),
            steepness=float(raw.get("steepness", 1.5)),
        )


@dataclass(frozen=True)
class FeatureContribution:
    feature: str
    value: float
    weight: float
    contribution: float

    def as_dict(self) -> dict[str, Any]:
        return {
            "feature": self.feature,
            "value": round(self.value, 4),
            "weight": round(self.weight, 4),
            "contribution": round(self.contribution, 4),
        }


@dataclass(frozen=True)
class CensorDecision:
    recommendation: str  # dismiss | warning | removal
    probabilities: dict[str, float]
    score: float  # severity logit z
    contributions: tuple[FeatureContribution, ...]
    summary: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "recommendation": self.recommendation,
            "probabilities": {k: round(v, 4) for k, v in self.probabilities.items()},
            "score": round(self.score, 4),
            "contributions": [c.as_dict() for c in self.contributions],
            "summary": self.summary,
        }


def _softmax(xs: list[float]) -> list[float]:
    m = max(xs)
    exps = [math.exp(x - m) for x in xs]
    total = sum(exps)
    return [e / total for e in exps]


class CensorDecisionModel:
    """Deterministic probabilistic adjudicator for the censorate."""

    def __init__(self, policy: CensorPolicy | None = None):
        self.policy = policy or CensorPolicy()

    @classmethod
    def from_institution(cls, institution: Any) -> "CensorDecisionModel":
        return cls(CensorPolicy.from_dict(getattr(institution, "censor_policy", None)))

    def decide(
        self,
        *,
        violation_type: str,
        confidence: float,
        prior_violations: int = 0,
        prior_warnings: int = 0,
        repeat_offender: bool | None = None,
    ) -> CensorDecision:
        p = self.policy
        confidence = min(1.0, max(0.0, float(confidence)))
        if repeat_offender is None:
            repeat_offender = prior_warnings > 0 or prior_violations >= 2

        sev_w = p.severity_weights.get(violation_type, p.severity_fallback)
        contributions = (
            FeatureContribution("bias", 1.0, p.bias, p.bias),
            FeatureContribution(f"severity[{violation_type}]×confidence", confidence, sev_w, sev_w * confidence),
            FeatureContribution(
                "prior_violations", math.log1p(prior_violations),
                p.prior_violation_weight, p.prior_violation_weight * math.log1p(prior_violations),
            ),
            FeatureContribution(
                "prior_warnings", math.log1p(prior_warnings),
                p.prior_warning_weight, p.prior_warning_weight * math.log1p(prior_warnings),
            ),
            FeatureContribution(
                "repeat_offender", 1.0 if repeat_offender else 0.0,
                p.repeat_bonus, p.repeat_bonus if repeat_offender else 0.0,
            ),
        )
        z = sum(c.contribution for c in contributions)

        p_dismiss, p_warning, p_removal = _softmax([-z, -p.steepness * abs(z), z])
        probabilities = {"dismiss": p_dismiss, "warning": p_warning, "removal": p_removal}

        if p_removal >= p.removal_threshold:
            recommendation = "removal"
        elif (1.0 - p_dismiss) >= p.warn_threshold:
            recommendation = "warning"
        else:
            recommendation = "dismiss"

        zh = {"dismiss": "不立案", "warning": "留任警告", "removal": "建议革职"}
        summary = (
            f"监察裁决：{zh[recommendation]}"
            f"（P(革职)={p_removal:.2f} / 阈值{p.removal_threshold:.2f}，"
            f"P(立案)={1 - p_dismiss:.2f} / 阈值{p.warn_threshold:.2f}；"
            f"类型={violation_type}，置信={confidence:.2f}，"
            f"前科={prior_violations}，警告={prior_warnings}，重犯={'是' if repeat_offender else '否'}）"
        )
        return CensorDecision(
            recommendation=recommendation,
            probabilities=probabilities,
            score=z,
            contributions=contributions,
            summary=summary,
        )
