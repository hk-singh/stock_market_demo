"""Pluggable strategy engine.

Every strategy subclasses `Strategy` and implements `on_metric()`.
When a metric arrives from the aggregated-metrics topic, the engine
calls each active strategy. If a strategy returns a Signal, it gets
published to the price-alerts topic and persisted in the DB.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class Signal:
    """A trading signal emitted by a strategy."""

    strategy_name: str
    symbol: str
    action: str  # "BUY", "SELL", or "HOLD"
    reason: str
    strength: float  # 0.0 to 1.0
    price: float
    timestamp: str = field(default_factory=lambda: datetime.utcnow().isoformat())

    def to_dict(self) -> dict:
        return {
            "strategy_name": self.strategy_name,
            "symbol": self.symbol,
            "action": self.action,
            "reason": self.reason,
            "strength": self.strength,
            "price": self.price,
            "timestamp": self.timestamp,
        }


class Strategy:
    """Base class for all trading strategies.

    Subclasses must implement `on_metric(symbol, metrics) -> Signal | None`.
    """

    name: str = "base"
    description: str = ""

    def on_metric(self, symbol: str, metrics: dict) -> Signal | None:
        """Evaluate a new metric and optionally return a signal.

        Args:
            symbol: The stock symbol.
            metrics: Dict with keys like latest_price, vwap, avg_price,
                     min_price, max_price, total_volume, price_change_pct, etc.

        Returns:
            A Signal if the strategy wants to emit one, else None.
        """
        raise NotImplementedError


# ---------------------------------------------------------------------------
# Built-in strategies
# ---------------------------------------------------------------------------


class VWAPDeviationStrategy(Strategy):
    """Emit BUY when price drops significantly below VWAP, SELL when above.

    Rationale: VWAP is the "fair" price weighted by volume. Large deviations
    from VWAP tend to revert, so this is a mean-reversion strategy.
    """

    name = "vwap_deviation"
    description = "Buy when price is >1% below VWAP, sell when >1% above"

    def __init__(self, threshold_pct: float = 1.0):
        self.threshold_pct = threshold_pct

    def on_metric(self, symbol: str, metrics: dict) -> Signal | None:
        price = metrics.get("latest_price", 0)
        vwap = metrics.get("vwap", 0)
        if not vwap or not price:
            return None

        deviation_pct = ((price - vwap) / vwap) * 100

        if deviation_pct < -self.threshold_pct:
            return Signal(
                strategy_name=self.name,
                symbol=symbol,
                action="BUY",
                reason=f"Price ${price:.2f} is {abs(deviation_pct):.1f}% below VWAP ${vwap:.2f}",
                strength=min(abs(deviation_pct) / 5.0, 1.0),
                price=price,
            )
        elif deviation_pct > self.threshold_pct:
            return Signal(
                strategy_name=self.name,
                symbol=symbol,
                action="SELL",
                reason=f"Price ${price:.2f} is {deviation_pct:.1f}% above VWAP ${vwap:.2f}",
                strength=min(deviation_pct / 5.0, 1.0),
                price=price,
            )
        return None


class MovingAverageCrossoverStrategy(Strategy):
    """Track a short-term avg vs long-term avg and signal on crossover.

    Uses the aggregated metrics avg_price as short-term and maintains a
    longer-term EMA internally.
    """

    name = "ma_crossover"
    description = "Buy on bullish crossover (short MA > long MA), sell on bearish"

    def __init__(self, ema_alpha: float = 0.1):
        self.ema_alpha = ema_alpha
        self._long_ema: dict[str, float] = {}
        self._prev_short: dict[str, float] = {}

    def on_metric(self, symbol: str, metrics: dict) -> Signal | None:
        price = metrics.get("latest_price", 0)
        short_ma = metrics.get("avg_price", 0)
        if not price or not short_ma:
            return None

        # Update long EMA
        if symbol not in self._long_ema:
            self._long_ema[symbol] = short_ma
            self._prev_short[symbol] = short_ma
            return None

        prev_short = self._prev_short[symbol]
        prev_long = self._long_ema[symbol]
        self._long_ema[symbol] = (self.ema_alpha * short_ma) + ((1 - self.ema_alpha) * prev_long)
        long_ma = self._long_ema[symbol]
        self._prev_short[symbol] = short_ma

        # Detect crossover: compare previous relationship to current
        was_below = prev_short < prev_long  # short was below long
        now_above = short_ma > long_ma  # short is now above long

        if was_below and now_above:
            return Signal(
                strategy_name=self.name,
                symbol=symbol,
                action="BUY",
                reason=f"Bullish crossover: short MA ${short_ma:.2f} crossed above long MA ${long_ma:.2f}",
                strength=0.7,
                price=price,
            )

        was_above = prev_short > prev_long
        now_below = short_ma < long_ma

        if was_above and now_below:
            return Signal(
                strategy_name=self.name,
                symbol=symbol,
                action="SELL",
                reason=f"Bearish crossover: short MA ${short_ma:.2f} crossed below long MA ${long_ma:.2f}",
                strength=0.7,
                price=price,
            )

        return None


class VolumeSpikeStrategy(Strategy):
    """Emit a signal when volume spikes significantly above average.

    A sudden volume spike often precedes a big price move.
    """

    name = "volume_spike"
    description = "Alert when volume is >2x the rolling average"

    def __init__(self, spike_multiplier: float = 2.0):
        self.spike_multiplier = spike_multiplier
        self._avg_volume: dict[str, float] = {}
        self._alpha = 0.2  # EMA smoothing

    def on_metric(self, symbol: str, metrics: dict) -> Signal | None:
        volume = metrics.get("total_volume", 0)
        price = metrics.get("latest_price", 0)
        if not volume or not price:
            return None

        if symbol not in self._avg_volume:
            self._avg_volume[symbol] = volume
            return None

        avg = self._avg_volume[symbol]
        self._avg_volume[symbol] = (self._alpha * volume) + ((1 - self._alpha) * avg)

        if avg > 0 and volume > avg * self.spike_multiplier:
            change_pct = metrics.get("price_change_pct", 0)
            action = "BUY" if change_pct > 0 else "SELL"
            return Signal(
                strategy_name=self.name,
                symbol=symbol,
                action=action,
                reason=f"Volume spike: {volume:,} is {volume / avg:.1f}x average ({avg:,.0f}), price change {change_pct:+.2f}%",
                strength=min(volume / (avg * 3), 1.0),
                price=price,
            )

        return None


# ---------------------------------------------------------------------------
# Strategy registry
# ---------------------------------------------------------------------------

BUILTIN_STRATEGIES: dict[str, Strategy] = {
    "vwap_deviation": VWAPDeviationStrategy(),
    "ma_crossover": MovingAverageCrossoverStrategy(),
    "volume_spike": VolumeSpikeStrategy(),
}


def get_strategy(name: str) -> Strategy | None:
    return BUILTIN_STRATEGIES.get(name)


def list_strategies() -> list[dict]:
    return [
        {"name": s.name, "description": s.description}
        for s in BUILTIN_STRATEGIES.values()
    ]
