import json
import os
import signal
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
import logging
from collections import defaultdict
from datetime import datetime

from dotenv import load_dotenv
from kafka import KafkaConsumer, KafkaProducer
from kafka.errors import KafkaError

from shared.healthcheck import start_health_server

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Global variables
consumer = None
producer = None


class TradeAggregator:
    """
    Aggregates trade data and calculates metrics per symbol.
    Uses sliding windows to calculate moving averages and other metrics.
    """

    def __init__(self, window_size=20):
        """
        Initialize aggregator.

        Args:
            window_size: Number of trades to keep in window for calculations
        """
        self.window_size = window_size
        # Store recent trades per symbol
        self.trades = defaultdict(list)  # symbol -> list of trades
        self.trade_count = defaultdict(int)  # symbol -> count

    def add_trade(self, symbol: str, price: float, volume: int, timestamp: int):
        """Add a trade and maintain the sliding window."""
        trade = {
            'price': price,
            'volume': volume,
            'timestamp': timestamp
        }

        self.trades[symbol].append(trade)
        self.trade_count[symbol] += 1

        # Keep only last N trades
        if len(self.trades[symbol]) > self.window_size:
            self.trades[symbol].pop(0)

    def calculate_metrics(self, symbol: str) -> dict:
        """
        Calculate aggregated metrics for a symbol.

        Returns dict with:
            - symbol
            - trade_count
            - avg_price
            - min_price
            - max_price
            - total_volume
            - vwap (volume-weighted average price)
            - price_change_pct (from first to last in window)
        """
        if symbol not in self.trades or len(self.trades[symbol]) == 0:
            return None

        trades = self.trades[symbol]
        prices = [t['price'] for t in trades]
        volumes = [t['volume'] for t in trades]

        # Calculate VWAP (Volume-Weighted Average Price)
        total_value = sum(p * v for p, v in zip(prices, volumes))
        total_volume = sum(volumes)
        vwap = total_value / total_volume if total_volume > 0 else 0

        # Price change percentage
        if len(prices) > 1:
            price_change_pct = ((prices[-1] - prices[0]) / prices[0]) * 100
        else:
            price_change_pct = 0

        metrics = {
            'symbol': symbol,
            'trade_count': self.trade_count[symbol],
            'window_size': len(trades),
            'avg_price': round(sum(prices) / len(prices), 2),
            'min_price': round(min(prices), 2),
            'max_price': round(max(prices), 2),
            'latest_price': round(prices[-1], 2),
            'total_volume': total_volume,
            'vwap': round(vwap, 2),
            'price_change_pct': round(price_change_pct, 2),
            'timestamp': datetime.now().isoformat()
        }

        return metrics


def create_kafka_consumer(topic, group_id, bootstrap_servers):
    """Create Kafka consumer."""
    try:
        consumer = KafkaConsumer(
            topic,
            bootstrap_servers=bootstrap_servers,
            group_id=group_id,
            auto_offset_reset='latest',  # Start from latest for real-time processing
            enable_auto_commit=False,  # Manual commit after processing
            value_deserializer=lambda m: json.loads(m.decode('utf-8')),
            key_deserializer=lambda k: k.decode('utf-8') if k else None,
        )
        logger.info(f"Consumer created: topic={topic}, group={group_id}")
        return consumer
    except KafkaError as e:
        logger.error(f"Failed to create consumer: {e}")
        raise


def create_kafka_producer(bootstrap_servers):
    """Create Kafka producer for publishing aggregated metrics."""
    try:
        producer = KafkaProducer(
            bootstrap_servers=bootstrap_servers,
            value_serializer=lambda v: json.dumps(v).encode('utf-8'),
            key_serializer=lambda k: k.encode('utf-8') if k else None,
            acks='all',
            compression_type='snappy'
        )
        logger.info("Producer created for aggregated metrics")
        return producer
    except KafkaError as e:
        logger.error(f"Failed to create producer: {e}")
        raise


def signal_handler(sig, frame):
    """Handle graceful shutdown."""
    logger.info("Shutdown signal received...")
    if consumer:
        consumer.close()
    if producer:
        producer.flush()
        producer.close()
    sys.exit(0)


def main():
    """Main entry point for aggregator consumer."""
    load_dotenv()

    # Configuration
    input_topic = 'raw-market-data'
    output_topic = 'aggregated-metrics'
    group_id = 'aggregator-consumer-group'
    bootstrap_servers = os.getenv('KAFKA_BOOTSTRAP_SERVERS', 'localhost:9092')

    # Start health check endpoint for K8s probes
    start_health_server(port=8002)

    logger.info("Starting Aggregator Consumer")
    logger.info(f"Input Topic: {input_topic}")
    logger.info(f"Output Topic: {output_topic}")
    logger.info(f"Consumer Group: {group_id}")

    # Set up signal handlers
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    # Create consumer and producer
    global consumer, producer
    try:
        consumer = create_kafka_consumer(input_topic, group_id, bootstrap_servers)
        producer = create_kafka_producer(bootstrap_servers)
    except Exception as e:
        logger.error(f"Failed to create Kafka clients: {e}")
        sys.exit(1)

    # Create aggregator
    aggregator = TradeAggregator(window_size=20)

    logger.info("Starting to consume and aggregate messages...")
    logger.info("Calculating metrics every 10 trades per symbol...")

    try:
        message_count = 0

        for message in consumer:
            message_count += 1

            # Extract trade data
            trade = message.value
            symbol = trade.get('s')
            price = trade.get('p')
            volume = trade.get('v')
            timestamp = trade.get('t')

            # Add to aggregator
            aggregator.add_trade(symbol, price, volume, timestamp)

            # Calculate and publish metrics every 10 trades
            if message_count % 10 == 0:
                metrics = aggregator.calculate_metrics(symbol)
                if metrics:
                    logger.info(f"Metrics for {symbol}: "
                                f"VWAP=${metrics['vwap']}, "
                                f"Avg=${metrics['avg_price']}, "
                                f"Change={metrics['price_change_pct']}%, "
                                f"Volume={metrics['total_volume']}")

                    # Publish to aggregated-metrics topic
                    try:
                        producer.send(
                            topic=output_topic,
                            key=symbol,
                            value=metrics
                        )
                    except Exception as e:
                        logger.error(f"Failed to publish metrics: {e}")

                # Commit offset after successful processing
                consumer.commit()

            # Log progress every 100 messages
            if message_count % 100 == 0:
                logger.info(f"Processed {message_count} total messages")

    except KeyboardInterrupt:
        logger.info("KeyboardInterrupt received")
    except Exception as e:
        logger.error(f"Error in consumer loop: {e}")
    finally:
        if consumer:
            consumer.close()
        if producer:
            producer.flush()
            producer.close()
        logger.info("Aggregator consumer closed")


if __name__ == "__main__":
    main()
