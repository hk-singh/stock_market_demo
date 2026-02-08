import json
import os
import signal
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
import logging

from dotenv import load_dotenv
from kafka import KafkaProducer
from kafka.errors import KafkaError
from websocket_handler import FinnhubWebSocketClient

from shared.healthcheck import start_health_server

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Global variable to hold WebSocket client
ws_client = None
kafka_producer = None

def create_kafka_producer(bootstrap_servers="localhost:9092"):
    """
    Create and configure Kafka producer.

    Args:
        bootstrap_servers: Kafka bootstrap servers

    Returns:
        KafkaProducer instance
    """
    try:
        producer = KafkaProducer(
            bootstrap_servers=bootstrap_servers,
            value_serializer=lambda v: json.dumps(v).encode('utf-8'),
            key_serializer=lambda k: k.encode('utf-8') if k else None,
            acks='all',  # Wait for all replicas to acknowledge
            retries=3,
            max_in_flight_requests_per_connection=1,  # Ensure ordering
            compression_type="snappy",
            # Error handling
            api_version=(2, 5, 0)
        )
        logger.info(f"Kafka producer created successfully: {bootstrap_servers}")
        return producer
    except KafkaError as e:
        logger.error(f"Failed to create Kafka producer: {e}")
        raise

def handle_trade_message(trade_data):
    """
    Callback function to handle incoming trade messages.
    This is where we'll add Kafka producer logic later.

    Args:
        trade_data: Dictionary containing trade information
            - s: symbol
            - p: price
            - v: volume
            - t: timestamp
            - c: conditions (list of trade conditions)
    """
    symbol = trade_data.get('s', 'UNKNOWN')
    price = trade_data.get('p', 0)
    volume = trade_data.get('v', 0)
    timestamp = trade_data.get('t', 0)

    logger.info(f"Processing trade: Symbol={symbol}, "
                f"Price=${price}, "
                f"Volume={volume}, "
                f"Timestamp={timestamp}")

    # Publish to Kafka
    if kafka_producer:
        try:
            # Use symbol as key for partitioning (all trades for same symbol go to same partition)
            kafka_producer.send(
                topic='raw-market-data',
                key=symbol,
                value=trade_data
            )
            # Optional: Wait for acknowledgment (blocks, but ensures delivery)
            # record_metadata = future.get(timeout=10)
            # logger.debug(f"Message sent to partition {record_metadata.partition} "
            #              f"at offset {record_metadata.offset}")
        except KafkaError as e:
            logger.error(f"Failed to send message to Kafka: {e}")
        except Exception as e:
            logger.error(f"Unexpected error sending to Kafka: {e}")

def signal_handler(sig, frame):
    """Handle graceful shutdown on CTRL+C."""
    logger.info("Shutdown signal received. Closing connections...")
    if ws_client:
        ws_client.disconnect()
    if kafka_producer:
        logger.info("Flushing Kafka producer...")
        kafka_producer.flush()
        kafka_producer.close()
        logger.info("Kafka producer closed")
    sys.exit(0)


def main():
    """Main entry point for the producer."""
    # Load environment variables
    load_dotenv()

    api_key = os.getenv('FINNHUB_API_KEY')
    if not api_key:
        logger.error("FINNHUB_API_KEY not found in environment variables")
        sys.exit(1)
    # Get Kafka bootstrap servers from env or use default
    kafka_bootstrap_servers = os.getenv('KAFKA_BOOTSTRAP_SERVERS', 'localhost:9092')

    # Define symbols to track
    # Start with a few major stocks
    symbols = [
        'AAPL',  # Apple
        'GOOGL',  # Google
        'MSFT',  # Microsoft
        'TSLA',  # Tesla
    ]

    # Start health check endpoint for K8s probes
    start_health_server(port=8000)

    logger.info("Starting Finnhub WebSocket Producer")
    logger.info(f"Kafka Bootstrap Servers: {kafka_bootstrap_servers}")
    logger.info(f"Tracking symbols: {', '.join(symbols)}")

    # Set up signal handler for graceful shutdown
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    # Create Kafka producer
    global kafka_producer
    try:
        kafka_producer = create_kafka_producer(kafka_bootstrap_servers)
    except Exception as e:
        logger.error(f"Failed to create Kafka producer: {e}")
        sys.exit(1)

    # Create and connect WebSocket client
    global ws_client
    ws_client = FinnhubWebSocketClient(
        api_key=api_key,
        symbols=symbols,
        on_message_callback=handle_trade_message
    )

    try:
        # This is a blocking call - keeps running until interrupted
        ws_client.connect()
    except KeyboardInterrupt:
        logger.info("KeyboardInterrupt received")
        ws_client.disconnect()
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        ws_client.disconnect()
        sys.exit(1)

if __name__ == "__main__":
    main()
