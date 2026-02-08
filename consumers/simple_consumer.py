import json
import os
import signal
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
import logging
from datetime import datetime

from dotenv import load_dotenv
from kafka import KafkaConsumer
from kafka.errors import KafkaError

from shared.healthcheck import start_health_server

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Global consumer
consumer = None


def create_kafka_consumer(
        topic,
        group_id,
        bootstrap_servers='localhost:9092',
        auto_offset_reset='earliest'
):
    """
    Create and configure Kafka consumer.

    Args:
        topic: Topic to subscribe to
        group_id: Consumer group ID
        bootstrap_servers: Kafka bootstrap servers
        auto_offset_reset: Where to start reading ('earliest' or 'latest')

    Returns:
        KafkaConsumer instance
    """
    try:
        consumer = KafkaConsumer(
            topic,
            bootstrap_servers=bootstrap_servers,
            group_id=group_id,
            auto_offset_reset=auto_offset_reset,
            enable_auto_commit=True,  # Automatically commit offsets
            auto_commit_interval_ms=5000,  # Commit every 5 seconds
            value_deserializer=lambda m: json.loads(m.decode('utf-8')),
            key_deserializer=lambda k: k.decode('utf-8') if k else None,
            # Consumer timeout - poll returns empty after this time
            # consumer_timeout_ms=1000,
        )
        logger.info(f"Kafka consumer created: topic={topic}, group={group_id}")
        return consumer
    except KafkaError as e:
        logger.error(f"Failed to create Kafka consumer: {e}")
        raise


def process_message(message):
    """
    Process a single message from Kafka.

    Args:
        message: ConsumerRecord from Kafka
    """
    # Extract message details
    topic = message.topic
    partition = message.partition
    offset = message.offset
    value = message.value
    timestamp = message.timestamp

    # Convert timestamp to readable format
    dt = datetime.fromtimestamp(timestamp / 1000.0)

    # Extract trade data
    symbol = value.get('s', 'UNKNOWN')
    price = value.get('p', 0)
    volume = value.get('v', 0)

    logger.info(
        f"[{dt.strftime('%H:%M:%S')}] "
        f"Topic: {topic} | Partition: {partition} | Offset: {offset} | "
        f"Symbol: {symbol} | Price: ${price} | Volume: {volume}"
    )


def signal_handler(sig, frame):
    """Handle graceful shutdown on CTRL+C."""
    logger.info("Shutdown signal received. Closing consumer...")
    if consumer:
        consumer.close()
    sys.exit(0)


def main():
    """Main entry point for the consumer."""
    load_dotenv()

    # Configuration
    topic = 'raw-market-data'
    group_id = 'simple-consumer-group'
    bootstrap_servers = os.getenv('KAFKA_BOOTSTRAP_SERVERS', 'localhost:9092')

    # Start health check endpoint for K8s probes
    start_health_server(port=8001)

    logger.info("Starting Simple Consumer")
    logger.info(f"Topic: {topic}")
    logger.info(f"Consumer Group: {group_id}")
    logger.info(f"Bootstrap Servers: {bootstrap_servers}")

    # Set up signal handler for graceful shutdown
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    # Create consumer
    global consumer
    try:
        consumer = create_kafka_consumer(
            topic=topic,
            group_id=group_id,
            bootstrap_servers=bootstrap_servers,
            auto_offset_reset='earliest'  # Start from beginning for testing
        )
    except Exception as e:
        logger.error(f"Failed to create consumer: {e}")
        sys.exit(1)

    # Start consuming messages
    logger.info("Starting to consume messages... (Press CTRL+C to stop)")

    try:
        message_count = 0
        for message in consumer:
            process_message(message)
            message_count += 1

            # Log stats every 100 messages
            if message_count % 100 == 0:
                logger.info(f"Processed {message_count} messages so far...")

    except KeyboardInterrupt:
        logger.info("KeyboardInterrupt received")
    except Exception as e:
        logger.error(f"Error consuming messages: {e}")
    finally:
        if consumer:
            consumer.close()
            logger.info("Consumer closed")

if __name__ == "__main__":
    main()
