"""Jev 式监察决策模型 tests — 确定性、可复现、阈值可配。"""
import math

import pytest

from imperial.court.censor_decision import (
    CensorDecisionModel,
    CensorPolicy,
)


@pytest.fixture
def model():
    return CensorDecisionModel()  # default policy


# ── probabilistic sanity ─────────────────────────────────
def test_probabilities_form_distribution(model):
    d = model.decide(violation_type="tool_violation", confidence=0.7)
    total = sum(d.probabilities.values())
    assert total == pytest.approx(1.0, abs=1e-9)
    assert set(d.probabilities) == {"dismiss", "warning", "removal"}
    # contributions sum to the severity logit
    assert sum(c.contribution for c in d.contributions) == pytest.approx(d.score)


def test_deterministic_same_input_same_output(model):
    a = model.decide(violation_type="dereliction", confidence=0.5, prior_violations=2)
    b = model.decide(violation_type="dereliction", confidence=0.5, prior_violations=2)
    assert a.as_dict() == b.as_dict()


# ── decision boundaries ──────────────────────────────────
def test_first_minor_offence_dismisses(model):
    """初犯 + 低置信 → 不立案（bias 压制，单案不兴狱）。"""
    d = model.decide(violation_type="dereliction", confidence=0.3)
    assert d.recommendation == "dismiss"
    assert d.probabilities["dismiss"] > 0.5


def test_solid_first_offence_warns(model):
    """初犯 + 高置信越权 → 警告，不到革职。"""
    d = model.decide(violation_type="tool_violation", confidence=0.9)
    assert d.recommendation == "warning"
    assert d.probabilities["removal"] < 0.62


def test_repeat_offender_removal(model):
    """累犯 + 警告在先 + 高置信 → 革职。"""
    d = model.decide(
        violation_type="tool_violation", confidence=0.9,
        prior_violations=4, prior_warnings=2, repeat_offender=True,
    )
    assert d.recommendation == "removal"
    assert d.probabilities["removal"] >= 0.62


def test_monotonicity_more_priors_higher_removal(model):
    """前科越多，P(革职) 单调不降。"""
    ps = [
        model.decide(violation_type="comm_violation", confidence=0.7, prior_violations=n)
        for n in range(5)
    ]
    probs = [d.probabilities["removal"] for d in ps]
    assert all(b >= a - 1e-9 for a, b in zip(probs, probs[1:]))


def test_confidence_clamped(model):
    """LLM 自评超出 [0,1] 时被钳制，不会炸掉评分。"""
    a = model.decide(violation_type="dereliction", confidence=5.0)
    b = model.decide(violation_type="dereliction", confidence=1.0)
    assert a.score == pytest.approx(b.score)


def test_unknown_violation_type_uses_fallback(model):
    d = model.decide(violation_type="heresy", confidence=0.8)
    assert any("heresy" in c.feature for c in d.contributions)


# ── policy configurability (制度 YAML 驱动) ──────────────
def test_policy_override_changes_verdict():
    """同一案情，不同制度阈值 → 不同裁决（换制度 = 换法度）。"""
    strict = CensorDecisionModel(CensorPolicy.from_dict({
        "removal_threshold": 0.25, "warn_threshold": 0.2,
    }))
    lenient = CensorDecisionModel(CensorPolicy.from_dict({
        "removal_threshold": 0.95, "warn_threshold": 0.9,
    }))
    case = dict(violation_type="tool_violation", confidence=0.85)
    assert strict.decide(**case).recommendation == "removal"
    assert lenient.decide(**case).recommendation == "dismiss"


def test_policy_from_institution_yaml(institution):
    """真实制度文件里的 censor_policy 段被正确加载。"""
    model = CensorDecisionModel.from_institution(institution)
    assert model.policy.warn_threshold == pytest.approx(0.35)
    assert model.policy.removal_threshold == pytest.approx(0.62)
    assert model.policy.severity_weights["tool_violation"] == pytest.approx(1.6)


def test_audit_summary_is_explainable(model):
    d = model.decide(violation_type="tool_violation", confidence=0.8, prior_violations=1)
    assert "监察裁决" in d.summary
    assert "P(革职)" in d.summary
    # every feature contribution is recorded (audit trail)
    features = [c.feature for c in d.contributions]
    assert features[0] == "bias"
    assert any("severity" in f for f in features)
    assert not any(math.isnan(c.contribution) for c in d.contributions)
