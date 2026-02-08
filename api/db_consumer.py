"""Kafka consumer that writes trades and aggregated metrics to PostgreSQL."""

import json
import logging
import os
import signal
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from datetime import datetime

from dotenv import load_dotenv
from kafka import KafkaConsumer
from kafka.errors import KafkaError
from sqlalchemy.orm import Session

from api.database import SessionLocal
from api.models import AggregatedMetric, Trade
from shared.healthcheck import start_health_server

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

consumer_trades = None
consumer_metrics = None


def write_trade(db: Session, trade_data: dict) -> None:
    trade = Trade(
        symbol=trade_data.get("s", "UNKNOWN"),
        price=trade_data.get("p", 0),
        volume=trade_data.get("v", 0),
        trade_timestamp=trade_data.get("t", 0),
        ingested_at=datetime.utcnow(),
    )
    db.add(trade)


def write_metric(db: Session, metric_data: dict) -> None:
    metric = AggregatedMetric(
        symbol=metric_data["symbol"],
        trade_count=metric_data["trade_count"],
        window_size=metric_data["window_size"],
        avg_price=metric_data["avg_price"],
        min_price=metric_data["min_price"],
        max_price=metric_data["max_price"],
        latest_price=metric_data["latest_price"],
        total_volume=metric_data["total_volume"],
        vwap=metric_data["vwap"],
        price_change_pct=metric_data["price_change_pct"],
        calculated_at=datetime.utcnow(),
    )
    db.add(metric)


def create_consumer(topic: str, group_id: str, bootstrap_servers: str) -> KafkaConsumer:
    try:
        return KafkaConsumer(
            topic,
            bootstrap_servers=bootstrap_servers,
            group_id=group_id,
            auto_offset_reset="latest",
            enable_auto_commit=False,
            value_deserializer=lambda m: json.loads(m.decode("utf-8")),
            key_deserializer=lambda k: k.decode("utf-8") if k else None,
            consumer_timeout_ms=1000,
        )
    except KafkaError as e:
        logger.error(f"Failed to create consumer for {topic}: {e}")
        raise


def signal_handler(sig, frame):
    logger.info("Shutdown signal received...")
    if consumer_trades:
        consumer_trades.close()
    if consumer_metrics:
        consumer_metrics.close()
    sys.exit(0)


def main():
    load_dotenv()

    bootstrap_servers = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092")
    batch_size = 25

    start_health_server(port=8004)

    logger.info("Starting DB Writer Consumer")
    logger.info(f"Bootstrap Servers: {bootstrap_servers}")
    logger.info(f"Batch Size: {batch_size}")

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    global consumer_trades, consumer_metrics
    try:
        consumer_trades = create_consumer(
            "raw-market-data", "db-writer-trades-group", bootstrap_servers
        )
        consumer_metrics = create_consumer(
            "aggregated-metrics", "db-writer-metrics-group", bootstrap_servers
        )
    except Exception as e:
        logger.error(f"Failed to create consumers: {e}")
        sys.exit(1)

    logger.info("Consuming from raw-market-data and aggregated-metrics...")

    trade_batch = []
    metric_batch = []
    total_trades = 0
    total_metrics = 0

    try:
        while True:
            # Poll trades
            trade_records = consumer_trades.poll(timeout_ms=500)
            for _tp, messages in trade_records.items():
                for msg in messages:
                    trade_batch.append(msg.value)

            # Poll metrics
            metric_records = consumer_metrics.poll(timeout_ms=500)
            for _tp, messages in metric_records.items():
                for msg in messages:
                    metric_batch.append(msg.value)

            # Flush trade batch
            if len(trade_batch) >= batch_size:
                db = SessionLocal()
                try:
                    for t in trade_batch:
                        write_trade(db, t)
                    db.commit()
                    consumer_trades.commit()
                    total_trades += len(trade_batch)
                    logger.info(
                        f"Wrote {len(trade_batch)} trades to DB "
                        f"(total: {total_trades})"
                    )
                    trade_batch = []
                except Exception as e:
                    db.rollback()
                    logger.error(f"Failed to write trades: {e}")
                finally:
                    db.close()

            # Flush metric batch
            if len(metric_batch) >= 5 or (metric_batch and not metric_records):
                db = SessionLocal()
                try:
                    for m in metric_batch:
                        write_metric(db, m)
                    db.commit()
                    consumer_metrics.commit()
                    total_metrics += len(metric_batch)
                    logger.info(
                        f"Wrote {len(metric_batch)} metrics to DB "
                        f"(total: {total_metrics})"
                    )
                    metric_batch = []
                except Exception as e:
                    db.rollback()
                    logger.error(f"Failed to write metrics: {e}")
                finally:
                    db.close()

    except KeyboardInterrupt:
        logger.info("KeyboardInterrupt received")
    finally:
        # Flush remaining
        if trade_batch or metric_batch:
            db = SessionLocal()
            try:
                for t in trade_batch:
                    write_trade(db, t)
                for m in metric_batch:
                    write_metric(db, m)
                db.commit()
                logger.info(
                    f"Final flush: {len(trade_batch)} trades, "
                    f"{len(metric_batch)} metrics"
                )
            except Exception as e:
                db.rollback()
                logger.error(f"Failed final flush: {e}")
            finally:
                db.close()

        if consumer_trades:
            consumer_trades.close()
        if consumer_metrics:
            consumer_metrics.close()
        logger.info("DB Writer Consumer closed")


if __name__ == "__main__":
    main()
