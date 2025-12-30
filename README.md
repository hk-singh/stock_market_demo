# Real-Time Financial Data Streaming Platform

A production-grade Kafka streaming pipeline that ingests real-time stock market data from Finnhub's WebSocket API, processes it through multiple consumer patterns, and stores aggregated metrics for analysis.

## Architecture
```
Finnhub WebSocket API
        ↓
Python Producer (WebSocket Client)
        ↓
Kafka Cluster (Local/GKE)
    ↓   ↓   ↓
┌───────┴───────┴────────┐
│                         │
Consumer 1:          Consumer 2:          Consumer 3:
Simple Logger        Aggregator           Storage
                          ↓                    ↓
                  aggregated-metrics    JSON Files
                       topic            (BigQuery later)
```

## Features

- **Real-time ingestion**: WebSocket connection to Finnhub for live trade data
- **Kafka streaming**: Distributed message processing with partitioning by symbol
- **Multiple consumer patterns**: Demonstrates different processing strategies
- **Metric aggregation**: Real-time calculation of VWAP, moving averages, and price changes
- **Data persistence**: Batch storage with configurable retention
- **Fault tolerance**: Automatic reconnection, offset management, and graceful shutdown
- **Containerized**: Docker and Kubernetes ready for GKE deployment

## Prerequisites

- Python 3.9+
- Docker & Docker Compose
- Finnhub API key (free tier: https://finnhub.io/)
- GCP account with credits (for GKE deployment)

## Local Setup

### 1. Clone and Setup Environment
```bash
git clone <your-repo>
cd kafka-streaming-project

# Create .env file
cat > .env << EOF
FINNHUB_API_KEY=your_api_key_here
KAFKA_BOOTSTRAP_SERVERS=localhost:9092
EOF
```

### 2. Start Kafka Cluster
```bash
# Start Kafka, Zookeeper, and Kafka UI
docker-compose up -d

# Wait ~60 seconds for Kafka to be ready
docker-compose logs -f kafka

# Create topics
./create-topics.sh
```

**Kafka UI**: http://localhost:8080

### 3. Install Dependencies
```bash
# Producer
cd producer
pip install -r requirements.txt

# Consumers
cd ../consumers
pip install -r requirements.txt
```

### 4. Run the Pipeline

**Terminal 1 - Producer:**
```bash
cd producer
python producer.py
```

**Terminal 2 - Simple Consumer:**
```bash
cd consumers
python simple_consumer.py
```

**Terminal 3 - Aggregator Consumer:**
```bash
cd consumers
python aggregator_consumer.py
```

**Terminal 4 - Storage Consumer:**
```bash
cd consumers
python storage_consumer.py
```

## Kafka Topics

| Topic | Purpose | Partitions | Retention |
|-------|---------|------------|-----------|
| `raw-market-data` | Raw trades from Finnhub | 3 | 7 days |
| `aggregated-metrics` | Calculated metrics (VWAP, averages) | 3 | 7 days |
| `price-alerts` | Price threshold alerts | 2 | 7 days |
| `dead-letter-queue` | Failed messages | 1 | 7 days |

## Key Design Decisions

### Partitioning Strategy
- **By symbol**: Ensures ordering per stock (all AAPL trades processed in order)
- **3 partitions**: Allows parallel processing while staying within free tier limits

### Compression
- **Snappy**: ~50% size reduction with minimal CPU overhead
- Optimizes network bandwidth and storage costs

### Consumer Groups
- **Independent groups**: Each consumer type has its own group for parallel processing
- **Manual offset commits**: Ensures exactly-once semantics for critical operations

### Error Handling
- WebSocket auto-reconnection with exponential backoff
- Dead letter queue for poison messages
- Graceful shutdown with signal handlers

## Project Structure
```
kafka-streaming-project/
├── producer/
│   ├── producer.py              # Main WebSocket producer
│   ├── websocket_handler.py     # WebSocket client implementation
│   └── requirements.txt
├── consumers/
│   ├── simple_consumer.py       # Basic message verification
│   ├── aggregator_consumer.py   # Metric calculation
│   ├── storage_consumer.py      # Data persistence
│   └── requirements.txt
├── kubernetes/                   # K8s manifests (for GKE)
│   ├── kafka/
│   ├── producer/
│   └── consumers/
├── docker-compose.yml           # Local Kafka setup
├── create-topics.sh             # Topic initialization
├── .env                         # Environment variables
├── .gitignore
└── README.md
```

## Testing

### Verify Data Flow
```bash
# Check producer is sending
docker exec -it kafka kafka-console-consumer \
  --bootstrap-server localhost:9092 \
  --topic raw-market-data \
  --from-beginning \
  --max-messages 10

# Check aggregated metrics
docker exec -it kafka kafka-console-consumer \
  --bootstrap-server localhost:9092 \
  --topic aggregated-metrics \
  --from-beginning

# View consumer lag
# Navigate to http://localhost:8080 → Consumer Groups
```

### Market Hours Note
- US stocks trade 9:30 AM - 4:00 PM ET (Monday-Friday)
- For 24/7 testing, use crypto symbols: `BINANCE:BTCUSDT`, `BINANCE:ETHUSDT`

## Docker Commands
```bash
# Start services
docker-compose up -d

# View logs
docker-compose logs -f kafka

# Stop services
docker-compose down

# Reset (delete all data)
docker-compose down -v

# Check service health
docker-compose ps
```

## GCP/GKE Deployment

*(Coming soon - deployment instructions for GKE)*
```bash
# Create GKE cluster
gcloud container clusters create kafka-streaming-cluster \
  --zone us-central1-a \
  --num-nodes 3 \
  --machine-type e2-standard-2

# Deploy Kafka using Strimzi
kubectl create namespace kafka
kubectl create -f 'https://strimzi.io/install/latest?namespace=kafka' -n kafka

# Deploy producers and consumers
kubectl apply -f kubernetes/
```

## Metrics Calculated

The aggregator consumer calculates:
- **VWAP**: Volume-Weighted Average Price
- **Average Price**: Mean price over sliding window
- **Min/Max Price**: Price range in window
- **Total Volume**: Cumulative volume
- **Price Change %**: Percentage change from first to last trade in window

## Configuration

Edit these in `.env`:
```bash
FINNHUB_API_KEY=your_key_here
KAFKA_BOOTSTRAP_SERVERS=localhost:9092  # or kafka:29092 in Docker
```

Edit symbols in `producer/producer.py`:
```python
symbols = ['AAPL', 'GOOGL', 'MSFT', 'TSLA']
```

## Troubleshooting

**Kafka won't start:**
```bash
# Check logs
docker-compose logs kafka

# Wait longer (takes 30-60 seconds)
# Ensure ports 9092, 2181, 8080 are free
```

**Producer can't connect:**
```bash
# Verify Kafka is running
docker-compose ps

# Check KAFKA_BOOTSTRAP_SERVERS in .env
# For Docker: use kafka:29092
# For local Python: use localhost:9092
```

**No trades appearing:**
- Check if market is open (9:30 AM - 4:00 PM ET)
- Try crypto symbols for 24/7 data
- Verify Finnhub API key is valid

**Consumer lag increasing:**
- Add more consumers (up to partition count)
- Increase batch sizes
- Check for processing bottlenecks

## 📚 Technologies Used

- **Python 3.9+**: Core application logic
- **Kafka 3.x**: Distributed streaming platform
- **Docker & Docker Compose**: Containerization
- **Kubernetes (GKE)**: Orchestration
- **Finnhub API**: Real-time market data
- **Snappy**: Message compression
- **Google Cloud Platform**: Cloud infrastructure

## 🎯 Interview Talking Points

This project demonstrates:

1. **Real-time streaming architecture** with producer-consumer patterns
2. **Kafka fundamentals**: Topics, partitions, consumer groups, offset management
3. **Scalability**: Horizontal scaling via consumer groups and partitioning
4. **Fault tolerance**: Reconnection logic, exactly-once semantics, DLQ
5. **Cloud deployment**: Containerization and Kubernetes orchestration
6. **Production best practices**: Logging, monitoring, graceful shutdown
7. **Data processing patterns**: Stream aggregation, windowing, batch storage

## Contributing

This is a portfolio project. Suggestions welcome!

## 📝 License

MIT

## Author

**Your Name**
- GitHub: [@hk-singh](https://github.com/hk-singh)
- LinkedIn: [Harsh Singh](https://linkedin.com/in/hks2094/)

---

**Built as a demonstration of real-time data streaming with Apache Kafka**