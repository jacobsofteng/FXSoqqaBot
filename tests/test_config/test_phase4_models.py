"""Tests for Phase 4 config models, event types, and state snapshot.

Covers: TUIConfig, WebConfig, LearningConfig additions to BotSettings,
new EventType enum members (MUTATION, RULE_RETIRED, VARIANT_PROMOTED),
and TradingEngineState dataclass for dashboard consumption.
"""

from __future__ import annotations


# ---------------------------------------------------------------------------
# TUIConfig
# ---------------------------------------------------------------------------


class TestTUIConfig:
    """Tests for TUI dashboard configuration."""

    def test_refresh_interval_default(self):
        """TUIConfig.refresh_interval_s defaults to 1.0."""
        from fxsoqqabot.config.models import TUIConfig

        cfg = TUIConfig()
        assert cfg.refresh_interval_s == 1.0

    def test_enabled_default(self):
        """TUIConfig.enabled defaults to True."""
        from fxsoqqabot.config.models import TUIConfig

        cfg = TUIConfig()
        assert cfg.enabled is True


# ---------------------------------------------------------------------------
# WebConfig
# ---------------------------------------------------------------------------


class TestWebConfig:
    """Tests for web dashboard configuration."""

    def test_host_default(self):
        """WebConfig.host defaults to '0.0.0.0'."""
        from fxsoqqabot.config.models import WebConfig

        cfg = WebConfig()
        assert cfg.host == "0.0.0.0"

    def test_port_default(self):
        """WebConfig.port defaults to 8080."""
        from fxsoqqabot.config.models import WebConfig

        cfg = WebConfig()
        assert cfg.port == 8080

    def test_api_key_default(self):
        """WebConfig.api_key defaults to 'changeme'."""
        from fxsoqqabot.config.models import WebConfig

        cfg = WebConfig()
        assert cfg.api_key == "changeme"


# ---------------------------------------------------------------------------
# LearningConfig
# ---------------------------------------------------------------------------


class TestLearningConfig:
    """Tests for self-learning loop configuration."""

    def test_evolve_every_n_trades(self):
        """LearningConfig.evolve_every_n_trades defaults to 50."""
        from fxsoqqabot.config.models import LearningConfig

        cfg = LearningConfig()
        assert cfg.evolve_every_n_trades == 50

    def test_n_shadow_variants(self):
        """LearningConfig.n_shadow_variants defaults to 5."""
        from fxsoqqabot.config.models import LearningConfig

        cfg = LearningConfig()
        assert cfg.n_shadow_variants == 5

    def test_promotion_alpha(self):
        """LearningConfig.promotion_alpha defaults to 0.05."""
        from fxsoqqabot.config.models import LearningConfig

        cfg = LearningConfig()
        assert cfg.promotion_alpha == 0.05

    def test_min_promotion_trades(self):
        """LearningConfig.min_promotion_trades defaults to 50."""
        from fxsoqqabot.config.models import LearningConfig

        cfg = LearningConfig()
        assert cfg.min_promotion_trades == 50

    def test_retirement_threshold(self):
        """LearningConfig.retirement_threshold defaults to 0.3."""
        from fxsoqqabot.config.models import LearningConfig

        cfg = LearningConfig()
        assert cfg.retirement_threshold == 0.3

    def test_enabled_default_off(self):
        """LearningConfig.enabled defaults to False (off until ready)."""
        from fxsoqqabot.config.models import LearningConfig

        cfg = LearningConfig()
        assert cfg.enabled is False


# ---------------------------------------------------------------------------
# BotSettings — Phase 4 subsystem attributes
# ---------------------------------------------------------------------------


class TestBotSettingsPhase4:
    """Tests for Phase 4 additions to BotSettings."""

    def test_tui_attribute(self):
        """BotSettings includes tui: TUIConfig."""
        from fxsoqqabot.config.models import BotSettings, TUIConfig

        s = BotSettings()
        assert isinstance(s.tui, TUIConfig)

    def test_web_attribute(self):
        """BotSettings includes web: WebConfig."""
        from fxsoqqabot.config.models import BotSettings, WebConfig

        s = BotSettings()
        assert isinstance(s.web, WebConfig)

    def test_learning_attribute(self):
        """BotSettings includes learning: LearningConfig."""
        from fxsoqqabot.config.models import BotSettings, LearningConfig

        s = BotSettings()
        assert isinstance(s.learning, LearningConfig)


# ---------------------------------------------------------------------------
# EventType — learning events
# ---------------------------------------------------------------------------


class TestEventTypeLearning:
    """Tests for learning-related EventType enum members."""

    def test_mutation_event(self):
        """EventType.MUTATION exists with value 'mutation'."""
        from fxsoqqabot.core.events import EventType

        assert EventType.MUTATION == "mutation"

    def test_rule_retired_event(self):
        """EventType.RULE_RETIRED exists with value 'rule_retired'."""
        from fxsoqqabot.core.events import EventType

        assert EventType.RULE_RETIRED == "rule_retired"

    def test_variant_promoted_event(self):
        """EventType.VARIANT_PROMOTED exists with value 'variant_promoted'."""
        from fxsoqqabot.core.events import EventType

        assert EventType.VARIANT_PROMOTED == "variant_promoted"


# ---------------------------------------------------------------------------
# TradingEngineState
# ---------------------------------------------------------------------------


class TestTradingEngineState:
    """Tests for shared state snapshot dataclass."""

    def test_is_dataclass(self):
        """TradingEngineState is a dataclass."""
        import dataclasses

        from fxsoqqabot.core.state_snapshot import TradingEngineState

        assert dataclasses.is_dataclass(TradingEngineState)

    def test_default_regime(self):
        """Default regime is RANGING."""
        from fxsoqqabot.core.state_snapshot import TradingEngineState
        from fxsoqqabot.signals.base import RegimeState

        s = TradingEngineState()
        assert s.regime == RegimeState.RANGING

    def test_default_fields(self):
        """All expected fields exist with correct defaults."""
        from fxsoqqabot.core.state_snapshot import TradingEngineState

        s = TradingEngineState()
        assert s.regime_confidence == 0.0
        assert s.signal_confidences == {}
        assert s.signal_directions == {}
        assert s.open_position is None
        assert s.equity == 0.0
        assert s.daily_pnl == 0.0
        assert s.breaker_status == {}
        assert s.recent_trades == []
        assert s.volume_delta == 0.0
        assert s.bid_pressure == 0.0
        assert s.ask_pressure == 0.0
        assert s.daily_trade_count == 0
        assert s.daily_win_rate == 0.0
        assert s.is_connected is False

    def test_mutable(self):
        """TradingEngineState is NOT frozen -- engine writes, dashboards read."""
        from fxsoqqabot.core.state_snapshot import TradingEngineState

        s = TradingEngineState()
        s.equity = 100.0  # Should not raise
        assert s.equity == 100.0

    def test_to_dict(self):
        """to_dict() serializes for WebSocket JSON transmission."""
        from fxsoqqabot.core.state_snapshot import TradingEngineState

        s = TradingEngineState()
        d = s.to_dict()
        assert "regime" in d
        assert "equity" in d
        assert "daily_pnl" in d
        assert "volume_delta" in d
        assert "bid_pressure" in d
        assert "ask_pressure" in d
        assert "is_connected" in d
        assert d["regime"] == "ranging"  # String value, not enum

    def test_to_dict_regime_value(self):
        """to_dict() serializes regime as string value."""
        from fxsoqqabot.core.state_snapshot import TradingEngineState
        from fxsoqqabot.signals.base import RegimeState

        s = TradingEngineState()
        s.regime = RegimeState.TRENDING_UP
        d = s.to_dict()
        assert d["regime"] == "trending_up"
