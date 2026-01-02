import os
import signal
import sys
import json
from kafka import KafkaConsumer
from kafka.errors import KafkaError
from dotenv import load_dotenv
import logging
from datetime import datetime
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

consumer = None


def create_kafka_consumer(topic, group_id, bootstrap_servers):
    """Create Kafka consumer."""
    try:
        consumer = KafkaConsumer(
            topic,
            bootstrap_servers=bootstrap_servers,
            group_id=group_id,
            auto_offset_reset='earliest',  # Process all messages from beginning
            enable_auto_commit=False,  # Manual commit after batch write
            value_deserializer=lambda m: json.loads(m.decode('utf-8')),
            key_deserializer=lambda k: k.decode('utf-8') if k else None,
        )
        logger.info(f"Consumer created: topic={topic}, group={group_id}")
        return consumer
    except KafkaError as e:
        logger.error(f"Failed to create consumer: {e}")
        raise


def save_batch_to_file(batch, filename):
    """
    Save batch of data to JSON Lines file (append mode).

    JSON Lines format: one JSON object per line, making it easy to:
    - Stream process large files
    - Append without parsing entire file
    - Import into BigQuery/databases

    Args:
        batch: List of records to save
        filename: Filename to save to
    """
    try:
        # Create data directory if it doesn't exist
        data_dir = Path('data')
        data_dir.mkdir(exist_ok=True)

        filepath = data_dir / filename

        # Append batch to file (one JSON per line)
        with open(filepath, 'a') as f:
            for record in batch:
                f.write(json.dumps(record) + '\n')

        logger.info(f"Saved {len(batch)} records to {filepath}")
        return True

    except Exception as e:
        logger.error(f"Failed to save batch to file: {e}")
        return False


def signal_handler(sig, frame):
    """Handle graceful shutdown."""
    logger.info("Shutdown signal received...")
    if consumer:
        consumer.close()
    sys.exit(0)


def main():
    """Main entry point for storage consumer."""
    load_dotenv()

    # Configuration
    topic = 'raw-market-data'
    group_id = 'storage-consumer-group'
    bootstrap_servers = os.getenv('KAFKA_BOOTSTRAP_SERVERS', 'localhost:9092')
    batch_size = 50  # Write to file every 50 messages

    logger.info(f"Starting Storage Consumer")
    logger.info(f"Topic: {topic}")
    logger.info(f"Consumer Group: {group_id}")
    logger.info(f"Batch Size: {batch_size}")

    # Set up signal handlers
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    # Create consumer
    global consumer
    try:
        consumer = create_kafka_consumer(topic, group_id, bootstrap_servers)
    except Exception as e:
        logger.error(f"Failed to create consumer: {e}")
        sys.exit(1)

    logger.info("Starting to consume and store messages...")
    logger.info(f"Writing batches of {batch_size} records to data/ directory")

    try:
        message_count = 0
        batch = []

        # Create filename with date
        today = datetime.now().strftime('%Y-%m-%d')
        filename = f'trades_{today}.jsonl'

        logger.info(f"Saving to file: data/{filename}")

        for message in consumer:
            message_count += 1

            # Add message value to batch
            batch.append(message.value)

            # Write batch to file when it reaches batch_size
            if len(batch) >= batch_size:
                success = save_batch_to_file(batch, filename)

                if success:
                    # Commit offset only after successful write
                    consumer.commit()
                    logger.info(f"Batch committed. Total messages processed: {message_count}")
                    batch = []  # Clear batch
                else:
                    logger.error("Failed to save batch, not committing offset")

            # Log progress every 100 messages
            if message_count % 100 == 0:
                logger.info(f"Processed {message_count} messages (current batch size: {len(batch)})")

    except KeyboardInterrupt:
        logger.info("KeyboardInterrupt received")

        # Save remaining batch before exiting
        if batch:
            logger.info(f"Saving final batch of {len(batch)} records...")
            success = save_batch_to_file(batch, filename)
            if success:
                consumer.commit()
                logger.info("Final batch saved and committed")

    except Exception as e:
        logger.error(f"Error in consumer loop: {e}")

        # Try to save remaining batch
        if batch:
            logger.info(f"Attempting to save {len(batch)} records before exit...")
            save_batch_to_file(batch, filename)

    finally:
        if consumer:
            consumer.close()
        logger.info(f"Storage consumer closed. Total messages processed: {message_count}")


if __name__ == "__main__":
    main()