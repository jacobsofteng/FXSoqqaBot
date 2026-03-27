"""ML regime classifier using RandomForest on trade context per LEARN-03.

Trains a RandomForestClassifier on logged trade context data to predict
market regimes. Uses 14 features from trade logs (per-module confidences,
directions, composite scores, ATR, spread, equity, weights) to classify
regime state.

The classifier improves regime detection over time as more trade context
accumulates. Feature importance analysis reveals which signals contribute
most to regime prediction accuracy.

Key behaviors:
- Train on 20+ trades with cross-validation accuracy tracking
- Predict regime with confidence from predict_proba
- Feature importance sorted by contribution
- Graceful handling of insufficient data
"""

from __future__ import annotations

from typing import Any

import numpy as np
import structlog
from sklearn.ensemble import RandomForestClassifier
from sklearn.model_selection import cross_val_score
from sklearn.preprocessing import LabelEncoder

from fxsoqqabot.signals.base import RegimeState

logger = structlog.get_logger().bind(component="regime_classifier")


class RegimeClassifier:
    """ML-based regime classifier using RandomForest on trade context.

    Trains on logged trade data to predict regime state. Uses 14 features
    from trade context including per-module confidence/direction, composite
    scores, ATR, spread, equity, and module weights.

    Args:
        n_estimators: Number of trees in the RandomForest.
        min_training_samples: Minimum trades required for training.
    """

    FEATURE_COLUMNS: list[str] = [
        "chaos_confidence",
        "chaos_direction",
        "flow_confidence",
        "flow_direction",
        "timing_confidence",
        "timing_direction",
        "composite_score",
        "fused_confidence",
        "atr",
        "spread_at_entry",
        "equity_at_trade",
        "weight_chaos",
        "weight_flow",
        "weight_timing",
    ]

    def __init__(
        self,
        n_estimators: int = 100,
        min_training_samples: int = 20,
    ) -> None:
        self._clf = RandomForestClassifier(
            n_estimators=n_estimators,
            random_state=42,
            n_jobs=-1,
        )
        self._label_encoder = LabelEncoder()
        self._min_training_samples = min_training_samples
        self.is_trained: bool = False
        self.training_accuracy: float = 0.0
        self._n_features: int = len(self.FEATURE_COLUMNS)

    def _extract_features(self, trade: dict) -> list[float]:
        """Extract feature vector from a trade dict.

        Missing features are filled with 0.0.

        Args:
            trade: Trade dict with feature keys.

        Returns:
            List of float values in FEATURE_COLUMNS order.
        """
        return [float(trade.get(col, 0.0) or 0.0) for col in self.FEATURE_COLUMNS]

    def train(self, trades: list[dict]) -> dict[str, Any]:
        """Train the classifier on trade context data.

        Filters trades with non-null regime and pnl fields, extracts
        feature matrix and target labels, fits the RandomForest, and
        computes cross-validation accuracy.

        Args:
            trades: List of trade dicts with feature columns and "regime" field.

        Returns:
            Dict with is_trained, sample_count, cv_accuracy, feature_importances.
        """
        # Filter valid trades (non-null regime and pnl)
        valid_trades = [
            t for t in trades
            if t.get("regime") is not None and t.get("pnl") is not None
        ]

        if len(valid_trades) < self._min_training_samples:
            logger.info(
                "insufficient_training_data",
                sample_count=len(valid_trades),
                required=self._min_training_samples,
            )
            return {
                "is_trained": False,
                "reason": f"Insufficient data: {len(valid_trades)} < {self._min_training_samples}",
                "sample_count": len(valid_trades),
            }

        # Build feature matrix X
        X = np.array(
            [self._extract_features(t) for t in valid_trades],
            dtype=np.float64,
        )

        # Build target vector y
        regimes = [str(t["regime"]) for t in valid_trades]
        y = self._label_encoder.fit_transform(regimes)

        # Fit the classifier
        self._clf.fit(X, y)
        self.is_trained = True

        # Cross-validation (3-fold if enough data, skip if < 6 samples per fold)
        cv_accuracy = 0.0
        n_unique_classes = len(set(y))
        if len(valid_trades) >= 6 * n_unique_classes and n_unique_classes >= 2:
            try:
                cv_scores = cross_val_score(self._clf, X, y, cv=3)
                cv_accuracy = float(np.mean(cv_scores))
            except ValueError:
                # Edge case: too few samples per class for stratified split
                cv_accuracy = 0.0
        else:
            # Compute training accuracy as fallback
            predictions = self._clf.predict(X)
            cv_accuracy = float(np.mean(predictions == y))

        self.training_accuracy = cv_accuracy

        importances = self.get_feature_importance()

        logger.info(
            "classifier_trained",
            sample_count=len(valid_trades),
            cv_accuracy=cv_accuracy,
            n_classes=n_unique_classes,
            top_features=list(importances.keys())[:3],
        )

        return {
            "is_trained": True,
            "sample_count": len(valid_trades),
            "cv_accuracy": cv_accuracy,
            "feature_importances": importances,
        }

    def predict_regime(
        self, features: dict[str, float]
    ) -> tuple[RegimeState, float]:
        """Predict regime state from feature dict.

        If the classifier is not trained, returns (RANGING, 0.0) as
        a safe default.

        Args:
            features: Dict of feature_name -> float values.

        Returns:
            Tuple of (predicted RegimeState, confidence as max probability).
        """
        if not self.is_trained:
            return RegimeState.RANGING, 0.0

        # Extract feature vector
        feature_vector = np.array(
            [float(features.get(col, 0.0) or 0.0) for col in self.FEATURE_COLUMNS],
            dtype=np.float64,
        ).reshape(1, -1)

        # Predict class and probability
        predicted_class = self._clf.predict(feature_vector)[0]
        probabilities = self._clf.predict_proba(feature_vector)[0]

        # Decode back to regime string
        regime_str = self._label_encoder.inverse_transform([predicted_class])[0]
        confidence = float(np.max(probabilities))

        # Map string to RegimeState enum
        try:
            regime = RegimeState(regime_str)
        except ValueError:
            logger.warning(
                "unknown_regime_predicted",
                regime_str=regime_str,
            )
            regime = RegimeState.RANGING

        return regime, confidence

    def get_feature_importance(self) -> dict[str, float]:
        """Get feature importance sorted by contribution descending.

        Returns:
            Dict of feature_name -> importance value, sorted descending.
            Empty dict if classifier is not trained.
        """
        if not self.is_trained:
            return {}

        importances = dict(
            zip(self.FEATURE_COLUMNS, self._clf.feature_importances_)
        )

        # Sort by importance descending
        return dict(
            sorted(importances.items(), key=lambda x: x[1], reverse=True)
        )

    def get_prediction_confidence(self) -> float:
        """Return the training accuracy (from cross-validation).

        Returns:
            Cross-validation accuracy as a float.
        """
        return self.training_accuracy

    def get_state(self) -> dict[str, Any]:
        """Serialize classifier state for persistence.

        Returns:
            Dict with is_trained flag and label_encoder classes.
        """
        return {
            "is_trained": self.is_trained,
            "training_accuracy": self.training_accuracy,
            "label_classes": (
                list(self._label_encoder.classes_)
                if self.is_trained
                else []
            ),
        }

    def load_state(self, state: dict[str, Any]) -> None:
        """Restore classifier from serialized state.

        Note: The actual RandomForest model is not persisted here.
        Call train() again with data to rebuild the model.

        Args:
            state: Dict from get_state().
        """
        self.is_trained = state.get("is_trained", False)
        self.training_accuracy = state.get("training_accuracy", 0.0)

        label_classes = state.get("label_classes", [])
        if label_classes:
            self._label_encoder.classes_ = np.array(label_classes)

        logger.info(
            "classifier_state_loaded",
            is_trained=self.is_trained,
            training_accuracy=self.training_accuracy,
        )
