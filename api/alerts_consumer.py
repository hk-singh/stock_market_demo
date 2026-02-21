"""Kafka consumer that evaluates strategies and publishes signals to price-alerts topic."""

import json
import logging
import os
import signal
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from datetime import datetime

from dotenv import load_dotenv
from kafka import KafkaConsumer, KafkaProducer
from kafka.errors import KafkaError

from api.database import SessionLocal
from api.models import ActiveStrategy, AlertRule, StrategySignal
from api.strategy_engine import BUILTIN_STRATEGIES, Signal
from shared.healthcheck import start_health_server

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

_consumer = None


def signal_handler(sig, frame):
    logger.info("Shutdown signal received...")
    if _consumer:
        _consumer.close()
    sys.exit(0)


def _get_active_strategies(db) -> dict[str, list[str]]:
    """Return {strategy_name: [symbols]} for all active entries."""
    rows = db.query(ActiveStrategy).filter(ActiveStrategy.is_active == 1).all()
    result: dict[str, list[str]] = {}
    for row in rows:
        result.setdefault(row.strategy_name, []).append(row.symbol)
    return result


def _evaluate_alert_rules(db, symbol: str, metrics: dict) -> list[dict]:
    """Check custom alert rules and return triggered alerts."""
    rules = (
        db.query(AlertRule)
        .filter(AlertRule.symbol == symbol, AlertRule.is_active == 1)
        .all()
    )
    triggered = []
    price = metrics.get("latest_price", 0)
    volume = metrics.get("total_volume", 0)

    for rule in rules:
        fire = (
            (rule.condition == "price_above" and price > rule.threshold)
            or (rule.condition == "price_below" and price < rule.threshold)
            or (rule.condition == "volume_above" and volume > rule.threshold)
        )

        if fire:
            rule.triggered_count += 1
            rule.last_triggered_at = datetime.utcnow()
            triggered.append({
                "type": "alert_rule",
                "rule_id": rule.id,
                "rule_name": rule.name,
                "symbol": symbol,
                "condition": rule.condition,
                "threshold": rule.threshold,
                "actual_value": price if "price" in rule.condition else volume,
                "timestamp": datetime.utcnow().isoformat(),
            })

    if triggered:
        db.commit()
    return triggered


def _save_signal(db, sig: Signal) -> StrategySignal:
    """Persist a strategy signal to the database."""
    record = StrategySignal(
        strategy_name=sig.strategy_name,
        symbol=sig.symbol,
        action=sig.action,
        reason=sig.reason,
        strength=sig.strength,
        price=sig.price,
        created_at=datetime.utcnow(),
    )
    db.add(record)
    db.commit()
    return record


def main():
    load_dotenv()

    bootstrap_servers = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092")

    start_health_server(port=8007)

    logger.info("Starting Alerts Consumer")
    logger.info(f"Bootstrap Servers: {bootstrap_servers}")

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    global _consumer
    producer = None

    try:
        _consumer = KafkaConsumer(
            "aggregated-metrics",
            bootstrap_servers=bootstrap_servers,
            group_id="alerts-consumer-group",
            auto_offset_reset="latest",
            enable_auto_commit=True,
            value_deserializer=lambda m: json.loads(m.decode("utf-8")),
            consumer_timeout_ms=1000,
        )
    except KafkaError as e:
        logger.error(f"Failed to create consumer: {e}")
        sys.exit(1)

    try:
        producer = KafkaProducer(
            bootstrap_servers=bootstrap_servers,
            value_serializer=lambda v: json.dumps(v).encode("utf-8"),
        )
    except KafkaError as e:
        logger.error(f"Failed to create producer: {e}")
        sys.exit(1)

    signals_count = 0
    alerts_count = 0

    try:
        while True:
            records = _consumer.poll(timeout_ms=2000)

            for _tp, messages in records.items():
                for message in messages:
                    metrics = message.value
                    symbol = metrics.get("symbol", "")
                    if not symbol:
                        continue

                    db = SessionLocal()
                    try:
                        active = _get_active_strategies(db)

                        # Evaluate each strategy that is active for this symbol
                        for strategy_name, symbols in active.items():
                            if symbol not in symbols:
                                continue

                            strategy = BUILTIN_STRATEGIES.get(strategy_name)
                            if not strategy:
                                continue

                            sig = strategy.on_metric(symbol, metrics)
                            if sig:
                                _save_signal(db, sig)
                                producer.send("price-alerts", value=sig.to_dict())
                                signals_count += 1
                                logger.info(
                                    f"Signal: {sig.strategy_name} -> {sig.action} "
                                    f"{sig.symbol} @ ${sig.price:.2f} "
                                    f"(strength={sig.strength:.2f})"
                                )

                        # Evaluate custom alert rules
                        triggered = _evaluate_alert_rules(db, symbol, metrics)
                        for alert in triggered:
                            producer.send("price-alerts", value=alert)
                            alerts_count += 1
                            logger.info(
                                f"Alert: rule '{alert['rule_name']}' triggered "
                                f"for {symbol}"
                            )

                    except Exception as e:
                        logger.error(f"Error processing metrics for {symbol}: {e}")
                    finally:
                        db.close()

            if records:
                producer.flush()

    except KeyboardInterrupt:
        logger.info("KeyboardInterrupt received")
    finally:
        if _consumer:
            _consumer.close()
        if producer:
            producer.close()
        logger.info(
            f"Alerts consumer closed. "
            f"Emitted {signals_count} signals, {alerts_count} alerts."
        )


if __name__ == "__main__":
    main()
