"""Kafka consumer that snapshots portfolio value on every aggregated-metrics update."""

import json
import logging
import os
import signal
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from dotenv import load_dotenv
from kafka import KafkaConsumer
from kafka.errors import KafkaError

from api.database import SessionLocal
from api.models import Portfolio
from api.portfolio_service import take_snapshot
from shared.healthcheck import start_health_server

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

consumer = None


def signal_handler(sig, frame):
    logger.info("Shutdown signal received...")
    if consumer:
        consumer.close()
    sys.exit(0)


def main():
    load_dotenv()

    bootstrap_servers = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092")
    snapshot_interval = 60  # seconds between snapshots

    start_health_server(port=8006)

    logger.info("Starting Portfolio Valuation Consumer")
    logger.info(f"Bootstrap Servers: {bootstrap_servers}")
    logger.info(f"Snapshot interval: {snapshot_interval}s")

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    global consumer
    try:
        consumer = KafkaConsumer(
            "aggregated-metrics",
            bootstrap_servers=bootstrap_servers,
            group_id="valuation-consumer-group",
            auto_offset_reset="latest",
            enable_auto_commit=True,
            value_deserializer=lambda m: json.loads(m.decode("utf-8")),
            consumer_timeout_ms=1000,
        )
    except KafkaError as e:
        logger.error(f"Failed to create consumer: {e}")
        sys.exit(1)

    last_snapshot = 0
    metrics_count = 0

    try:
        while True:
            records = consumer.poll(timeout_ms=2000)
            for _tp, messages in records.items():
                metrics_count += len(messages)

            now = time.time()
            if now - last_snapshot >= snapshot_interval and metrics_count > 0:
                db = SessionLocal()
                try:
                    portfolios = db.query(Portfolio).all()
                    for portfolio in portfolios:
                        snap = take_snapshot(db, portfolio.id)
                        if snap:
                            logger.info(
                                f"Snapshot: portfolio={portfolio.id} "
                                f"value=${snap.total_value:.2f} "
                                f"pnl={snap.pnl_pct:+.2f}%"
                            )
                except Exception as e:
                    logger.error(f"Failed to take snapshot: {e}")
                finally:
                    db.close()

                last_snapshot = now

    except KeyboardInterrupt:
        logger.info("KeyboardInterrupt received")
    finally:
        if consumer:
            consumer.close()
        logger.info("Valuation consumer closed")


if __name__ == "__main__":
    main()
