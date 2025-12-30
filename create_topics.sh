#!/bin/bash

# Wait for Kafka to be ready
echo "Waiting for Kafka to be ready..."
sleep 10

# Create topics
docker exec -it kafka kafka-topics --bootstrap-server localhost:9092 \
  --create --topic raw-market-data --partitions 3 --replication-factor 1 \
  --config retention.ms=604800000

docker exec -it kafka kafka-topics --bootstrap-server localhost:9092 \
  --create --topic aggregated-metrics --partitions 3 --replication-factor 1 \
  --config retention.ms=604800000

docker exec -it kafka kafka-topics --bootstrap-server localhost:9092 \
  --create --topic price-alerts --partitions 2 --replication-factor 1 \
  --config retention.ms=604800000

docker exec -it kafka kafka-topics --bootstrap-server localhost:9092 \
  --create --topic dead-letter-queue --partitions 1 --replication-factor 1 \
  --config retention.ms=604800000

echo "Topics created successfully!"

# List all topics
docker exec -it kafka kafka-topics --bootstrap-server localhost:9092 --list