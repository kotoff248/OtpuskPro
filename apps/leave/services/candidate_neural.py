import json
import math
from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path


NEURAL_CANDIDATE_SCORER_VERSION = "vacation-candidate-mlp-v1"
NEURAL_CANDIDATE_SCORER_KIND = "tabular_mlp"
MODEL_ARTIFACT_FILENAME = "vacation_candidate_mlp_v1.json"


@dataclass(frozen=True)
class NeuralCandidateScoringResult:
    score: Decimal
    confidence: Decimal
    recommendation: str
    explanation: str
    model_version: str = NEURAL_CANDIDATE_SCORER_VERSION
    scorer_kind: str = NEURAL_CANDIDATE_SCORER_KIND


_MODEL_CACHE = None


def _model_path():
    return Path(__file__).resolve().parent.parent / "ml_models" / MODEL_ARTIFACT_FILENAME


def load_candidate_mlp_model():
    global _MODEL_CACHE
    if _MODEL_CACHE is None:
        _MODEL_CACHE = json.loads(_model_path().read_text(encoding="utf-8"))
        if _MODEL_CACHE.get("version") != NEURAL_CANDIDATE_SCORER_VERSION:
            raise ValueError("Unexpected neural scorer artifact version.")
    return _MODEL_CACHE


def _percent(value):
    value = max(Decimal("0.00"), min(Decimal("100.00"), Decimal(str(value))))
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _float_feature(features, key, default=0.0):
    try:
        return float(features.get(key, default) or default)
    except (TypeError, ValueError):
        return float(default)


def _bool_feature(features, key):
    return 1.0 if bool(features.get(key)) else 0.0


def _clamp(value, lower=0.0, upper=1.0):
    return max(lower, min(upper, float(value)))


def _sigmoid(value):
    value = _clamp(value, -40.0, 40.0)
    return 1.0 / (1.0 + math.exp(-value))


def _activation(value, name):
    if name == "relu":
        return max(0.0, value)
    if name == "sigmoid":
        return _sigmoid(value)
    return math.tanh(value)


def _linear(node, inputs, hidden_values=None):
    hidden_values = hidden_values or {}
    value = float(node.get("bias", 0.0))
    for key, weight in (node.get("weights") or {}).items():
        value += float(weight) * float(hidden_values.get(key, inputs.get(key, 0.0)))
    for key, weight in (node.get("input_weights") or {}).items():
        value += float(weight) * float(inputs.get(key, 0.0))
    return value


def build_candidate_mlp_inputs(features, *, passed_hard_rules=True):
    features = features or {}
    coverage_ratio = _float_feature(features, "planning_candidate_coverage_ratio")
    calendar_days = max(_float_feature(features, "period_calendar_days"), 1.0)
    chargeable_days = _float_feature(features, "period_chargeable_days")
    summer_overlap_days = _float_feature(features, "period_summer_overlap_days")
    if summer_overlap_days <= 0.0 and _bool_feature(features, "period_overlaps_summer"):
        summer_overlap_days = calendar_days
    risk_score = _float_feature(features, "risk_score")
    risk_level_weight = _float_feature(features, "risk_level_weight", 1.0)
    staff_margin = _float_feature(features, "risk_staff_margin")
    load_level = _float_feature(features, "risk_department_load_level", 1.0)
    priority = features.get("preference_priority") or ""
    candidate_kind = features.get("candidate_kind") or ""
    tenure_days = _float_feature(features, "employee_tenure_days_at_year_end")

    coverage_fit = 1.0 - min(abs(coverage_ratio - 1.0), 1.0)
    over_plan_pressure = max(coverage_ratio - 1.1, 0.0)
    risk_pressure = _clamp((risk_score / 100.0) + (risk_level_weight - 1.0) * 0.12, 0.0, 1.0)
    period_length_fit = 1.0 - min(abs(chargeable_days - 28.0) / 28.0, 1.0)
    planning_open_days = _float_feature(features, "planning_open_required_days")
    planning_blocking_days = _float_feature(features, "planning_blocking_days")

    return {
        "schema_match": 1.0 if int(_float_feature(features, "feature_schema_version")) == 1 else 0.0,
        "passed_hard_rules": 1.0 if passed_hard_rules else 0.0,
        "preference_exact": _bool_feature(features, "preference_exact_period_match"),
        "preference_primary": 1.0 if priority == "primary" else 0.0,
        "preference_backup": 1.0 if priority == "backup" else 0.0,
        "preference_missing": 0.0 if _bool_feature(features, "preference_has_preference") else 1.0,
        "auto_candidate": 1.0 if str(candidate_kind).startswith("auto") else 0.0,
        "manual_candidate": 1.0 if candidate_kind == "manual" else 0.0,
        "coverage_fit": _clamp(coverage_fit),
        "coverage_complete": _clamp(coverage_ratio / 1.15),
        "over_plan_pressure": _clamp(over_plan_pressure),
        "period_length_fit": _clamp(period_length_fit),
        "deadline_fit": (
            1.0
            if _bool_feature(features, "planning_has_blocker")
            and _bool_feature(features, "planning_ends_by_nearest_deadline")
            else 0.0
        ),
        "deadline_miss": (
            1.0
            if _bool_feature(features, "planning_has_blocker")
            and not _bool_feature(features, "planning_ends_by_nearest_deadline")
            else 0.0
        ),
        "planning_blocker_pressure": _clamp(planning_blocking_days / 28.0),
        "planning_open_pressure": _clamp(planning_open_days / 52.0),
        "risk_safety": _clamp(1.0 - risk_pressure),
        "risk_pressure": risk_pressure,
        "risk_conflict": _bool_feature(features, "risk_is_conflict"),
        "staff_margin_positive": _clamp(staff_margin / 5.0),
        "staff_shortage": 1.0 if staff_margin <= 0.0 else 0.0,
        "load_pressure": _clamp((load_level - 1.0) / 4.0),
        "substitution_available": (
            _bool_feature(features, "risk_has_substitution_capacity")
            or _bool_feature(features, "risk_substitution_used")
        ),
        "summer_overlap_ratio": _clamp(summer_overlap_days / calendar_days),
        "cross_month": _bool_feature(features, "period_cross_month") or _bool_feature(features, "period_crosses_month"),
        "tenure_maturity": _clamp(tenure_days / 730.0),
        "manager_role": _bool_feature(features, "employee_is_manager") or _bool_feature(features, "employee_is_management"),
        "has_risk_payload": 1.0 if "risk_staff_margin" in features and "risk_score" in features else 0.0,
    }


def _hidden_values(model, inputs):
    activation_name = model.get("hidden_activation", "tanh")
    values = {}
    for node in model.get("hidden_layer", []):
        values[node["name"]] = _activation(_linear(node, inputs, values), activation_name)
    return values


def _recommendation(score, heads, inputs, *, passed_hard_rules):
    if not passed_hard_rules:
        return "blocked"
    if inputs.get("risk_conflict", 0.0) >= 1.0:
        return "avoid"
    prefer_probability = _sigmoid(heads.get("prefer", 0.0))
    avoid_probability = _sigmoid(heads.get("avoid", 0.0))
    if score >= Decimal("80.00") and prefer_probability >= avoid_probability:
        return "prefer"
    if score < Decimal("55.00") or avoid_probability > prefer_probability + 0.18:
        return "avoid"
    return "normal"


def _explanation(recommendation, score, confidence, inputs, hidden, *, passed_hard_rules, features):
    if not passed_hard_rules:
        reason = features.get("candidate_block_reason_key") or "hard_rule"
        return (
            f"Кандидат не передавался в нейромодуль: он заблокирован жесткими правилами ({reason}). "
            f"Оценка {score}%, уверенность {confidence}%."
        )

    factors = []
    if hidden.get("preference_alignment", 0.0) > 0.45:
        factors.append("период хорошо совпадает с пожеланием")
    if hidden.get("coverage_balance", 0.0) > 0.38:
        factors.append("закрывает плановую потребность без сильного перекоса")
    if hidden.get("deadline_closure", 0.0) > 0.32:
        factors.append("помогает закрыть срочный остаток")
    if hidden.get("staffing_safety", 0.0) > 0.34:
        factors.append("оставляет приемлемый запас состава отдела")
    if hidden.get("department_pressure", 0.0) > 0.55:
        factors.append("модель видит повышенную нагрузку отдела")
    if hidden.get("manager_caution", 0.0) > 0.45:
        factors.append("для управленческой роли нужен дополнительный контроль")
    if not factors:
        factors.append("вариант прошел проверку, но требует управленческой оценки")

    recommendation_label = {
        "prefer": "предпочтительный вариант",
        "normal": "допустимый вариант",
        "avoid": "нежелательный вариант",
    }.get(recommendation, "допустимый вариант")
    return (
        f"Нейромодуль {NEURAL_CANDIDATE_SCORER_VERSION} выбрал {recommendation_label}: "
        f"{', '.join(factors[:3])}. Оценка {score}%, уверенность {confidence}%."
    )


def score_candidate_features_neural(features, *, passed_hard_rules=True):
    features = features or {}
    if not passed_hard_rules:
        score = Decimal("0.00")
        confidence = Decimal("94.00")
        return NeuralCandidateScoringResult(
            score=score,
            confidence=confidence,
            recommendation="blocked",
            explanation=_explanation(
                "blocked",
                score,
                confidence,
                {},
                {},
                passed_hard_rules=False,
                features=features,
            ),
        )

    model = load_candidate_mlp_model()
    inputs = build_candidate_mlp_inputs(features, passed_hard_rules=passed_hard_rules)
    hidden = _hidden_values(model, inputs)
    heads = {
        name: _linear(head, inputs, hidden)
        for name, head in (model.get("heads") or {}).items()
    }
    score = _percent(_sigmoid(heads["score"]) * 100.0)
    confidence = _percent(_sigmoid(heads["confidence"]) * 100.0)
    recommendation = _recommendation(score, heads, inputs, passed_hard_rules=passed_hard_rules)
    return NeuralCandidateScoringResult(
        score=score,
        confidence=confidence,
        recommendation=recommendation,
        explanation=_explanation(
            recommendation,
            score,
            confidence,
            inputs,
            hidden,
            passed_hard_rules=passed_hard_rules,
            features=features,
        ),
    )
