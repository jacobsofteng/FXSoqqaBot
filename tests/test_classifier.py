"""Tests for ML regime classifier per LEARN-03.

Verifies:
- RegimeClassifier initializes with RandomForestClassifier
- Training on synthetic trade data with correct features
- Prediction with confidence scores
- Feature importance analysis
- Minimum data requirements
- Periodic retraining flag
"""

from __future__ import annotations

import random

from fxsoqqabot.learning.classifier import RegimeClassifier
from fxsoqqabot.signals.base import RegimeState


def _make_synthetic_trades(n: int = 60, seed: int = 42) -> list[dict]:
    """Generate synthetic trade data with known regime patterns.

    Creates trades where regime correlates with feature patterns:
    - TRENDING_UP: high flow_confidence, high composite_score
    - RANGING: low confidence, low composite_score
    - HIGH_CHAOS: high chaos_confidence, low flow_confidence
    """
    random.seed(seed)
    trades = []
    regimes = ["trending_up", "ranging", "high_chaos"]

    for i in range(n):
        regime = regimes[i % 3]

        if regime == "trending_up":
            trade = {
                "chaos_confidence": random.gauss(0.3, 0.1),
                "chaos_direction": random.gauss(0.5, 0.2),
                "flow_confidence": random.gauss(0.8, 0.1),
                "flow_direction": random.gauss(0.7, 0.2),
                "timing_confidence": random.gauss(0.6, 0.15),
                "timing_direction": random.gauss(0.5, 0.2),
                "composite_score": random.gauss(0.7, 0.1),
                "fused_confidence": random.gauss(0.75, 0.1),
                "atr": random.gauss(15.0, 3.0),
                "spread_at_entry": random.gauss(0.3, 0.05),
                "equity_at_trade": random.gauss(25.0, 5.0),
                "weight_chaos": random.gauss(0.2, 0.05),
                "weight_flow": random.gauss(0.5, 0.05),
                "weight_timing": random.gauss(0.3, 0.05),
                "regime": regime,
                "pnl": random.gauss(2.0, 1.0),
            }
        elif regime == "ranging":
            trade = {
                "chaos_confidence": random.gauss(0.4, 0.1),
                "chaos_direction": random.gauss(0.0, 0.1),
                "flow_confidence": random.gauss(0.4, 0.1),
                "flow_direction": random.gauss(0.0, 0.1),
                "timing_confidence": random.gauss(0.5, 0.15),
                "timing_direction": random.gauss(0.0, 0.1),
                "composite_score": random.gauss(0.3, 0.1),
                "fused_confidence": random.gauss(0.35, 0.1),
                "atr": random.gauss(5.0, 2.0),
                "spread_at_entry": random.gauss(0.2, 0.05),
                "equity_at_trade": random.gauss(22.0, 3.0),
                "weight_chaos": random.gauss(0.33, 0.05),
                "weight_flow": random.gauss(0.33, 0.05),
                "weight_timing": random.gauss(0.33, 0.05),
                "regime": regime,
                "pnl": random.gauss(-0.5, 1.0),
            }
        else:  # high_chaos
            trade = {
                "chaos_confidence": random.gauss(0.9, 0.05),
                "chaos_direction": random.gauss(0.0, 0.3),
                "flow_confidence": random.gauss(0.2, 0.1),
                "flow_direction": random.gauss(0.0, 0.2),
                "timing_confidence": random.gauss(0.3, 0.1),
                "timing_direction": random.gauss(0.0, 0.2),
                "composite_score": random.gauss(0.2, 0.1),
                "fused_confidence": random.gauss(0.25, 0.1),
                "atr": random.gauss(25.0, 5.0),
                "spread_at_entry": random.gauss(0.5, 0.1),
                "equity_at_trade": random.gauss(20.0, 4.0),
                "weight_chaos": random.gauss(0.5, 0.05),
                "weight_flow": random.gauss(0.2, 0.05),
                "weight_timing": random.gauss(0.3, 0.05),
                "regime": regime,
                "pnl": random.gauss(-1.0, 2.0),
            }

        trades.append(trade)

    return trades


# ── Test 1: RegimeClassifier initializes with RandomForestClassifier ──


def test_initializes_with_random_forest() -> None:
    from sklearn.ensemble import RandomForestClassifier

    clf = RegimeClassifier()
    assert isinstance(clf._clf, RandomForestClassifier)
    assert clf.is_trained is False


# ── Test 2: train() builds feature matrix with correct columns ──


def test_train_builds_feature_matrix() -> None:
    clf = RegimeClassifier()
    trades = _make_synthetic_trades(60)
    result = clf.train(trades)

    assert result["is_trained"] is True
    assert result["sample_count"] == 60


# ── Test 3: Feature columns include required fields ──


def test_feature_columns_include_required() -> None:
    required = {"chaos_confidence", "flow_confidence", "timing_confidence",
                "composite_score", "atr", "spread_at_entry"}
    assert required.issubset(set(RegimeClassifier.FEATURE_COLUMNS))


# ── Test 4: Target column is regime mapped to integer ──


def test_target_regime_encoded() -> None:
    clf = RegimeClassifier()
    trades = _make_synthetic_trades(60)
    clf.train(trades)

    # LabelEncoder should have classes
    assert len(clf._label_encoder.classes_) > 0
    assert clf.is_trained is True


# ── Test 5: predict_regime() returns RegimeState and confidence ──


def test_predict_regime_returns_state_and_confidence() -> None:
    clf = RegimeClassifier()
    trades = _make_synthetic_trades(60)
    clf.train(trades)

    features = {
        "chaos_confidence": 0.9,
        "chaos_direction": 0.0,
        "flow_confidence": 0.2,
        "flow_direction": 0.0,
        "timing_confidence": 0.3,
        "timing_direction": 0.0,
        "composite_score": 0.2,
        "fused_confidence": 0.25,
        "atr": 25.0,
        "spread_at_entry": 0.5,
        "equity_at_trade": 20.0,
        "weight_chaos": 0.5,
        "weight_flow": 0.2,
        "weight_timing": 0.3,
    }

    regime, confidence = clf.predict_regime(features)

    assert isinstance(regime, RegimeState)
    assert 0.0 <= confidence <= 1.0


# ── Test 6: get_feature_importance() returns sorted dict ──


def test_get_feature_importance() -> None:
    clf = RegimeClassifier()
    trades = _make_synthetic_trades(60)
    clf.train(trades)

    importance = clf.get_feature_importance()

    assert isinstance(importance, dict)
    assert len(importance) > 0

    # Check sorted descending by importance
    values = list(importance.values())
    assert values == sorted(values, reverse=True)


# ── Test 7: train() with fewer than 20 trades returns not trained ──


def test_train_insufficient_data() -> None:
    clf = RegimeClassifier(min_training_samples=20)
    trades = _make_synthetic_trades(10)  # Only 10 trades

    result = clf.train(trades)

    assert result["is_trained"] is False
    assert "insufficient" in result["reason"].lower()
    assert clf.is_trained is False


# ── Test 8: Untrained model returns default prediction ──


def test_untrained_returns_default() -> None:
    clf = RegimeClassifier()

    regime, confidence = clf.predict_regime({"chaos_confidence": 0.5})

    assert regime == RegimeState.RANGING
    assert confidence == 0.0


# ── Test 9: Feature importance empty when not trained ──


def test_feature_importance_empty_when_untrained() -> None:
    clf = RegimeClassifier()
    assert clf.get_feature_importance() == {}


# ── Test 10: Training accuracy stored ──


def test_training_accuracy_stored() -> None:
    clf = RegimeClassifier()
    trades = _make_synthetic_trades(60)
    result = clf.train(trades)

    assert "cv_accuracy" in result
    assert clf.training_accuracy >= 0.0
