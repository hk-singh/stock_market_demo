# FORHARSH.md — The Full Story of This Project

## What Are We Building?

Imagine you're standing on the floor of the New York Stock Exchange. Thousands of trades fly past every second — Apple at $178.52, Tesla at $245.67, Google at $175.30 — and you need to catch them all, organize them, and make sense of the chaos. That's exactly what this project does, except instead of standing on a trading floor, we're using a WebSocket connection and Apache Kafka.

This is a **real-time financial data streaming platform**. It connects to Finnhub's live market feed, ingests every trade as it happens, processes it through multiple independent pipelines, and stores the results. The end goal (see `ROADMAP.md`) is a full paper trading system where you can test strategies against real market data — without risking a penny.

---

## The Architecture (How the Pieces Fit Together)

Think of it like a postal system:

1. **The Producer** is the post office that receives all incoming mail (trades from Finnhub)
2. **Kafka** is the sorting facility — it organizes messages into topics and ensures nothing gets lost
3. **The Consumers** are the mail carriers — each one takes the messages and does something different with them

```
Finnhub WebSocket API (live trades)
        |
        v
   [Producer] -----> Kafka Broker
                        |
              +---------+---------+
              |         |         |
              v         v         v
         [Simple]  [Aggregator]  [Storage]
         Consumer   Consumer     Consumer
              |         |            |
           stdout   metrics      .jsonl
                    topic        files
```

### Why This Architecture?

**Decoupling.** The producer doesn't know or care what happens to the messages after Kafka gets them. You can add 10 more consumers tomorrow and the producer keeps humming along. This is the core principle of event-driven architecture — and it's why companies like LinkedIn, Uber, and Netflix use Kafka.

**Ordering guarantees.** All trades for AAPL go to the same Kafka partition (because we partition by symbol). This means the aggregator always sees AAPL trades in order, which is critical for calculating accurate moving averages.

**Fault tolerance.** If the aggregator crashes, it restarts and picks up right where it left off (thanks to Kafka's offset tracking). No data is lost. The storage consumer only commits its offset *after* successfully writing to disk — this is basically "exactly-once" semantics, which is the holy grail of stream processing.

---

## The Codebase — File by File

### `producer/`

- **`producer.py`** — The main entry point. Loads environment variables, creates a Kafka producer with Snappy compression, and feeds every trade from the WebSocket callback straight into the `raw-market-data` topic. Uses the stock symbol as the partition key.

- **`websocket_handler.py`** — A clean wrapper around the `websocket-client` library. Handles connection, auto-reconnection (with a 5-second retry), subscribing to symbols, and parsing Finnhub's JSON messages. The key design choice: it takes a callback function (`on_message_callback`) so it's completely decoupled from Kafka.

### `consumers/`

- **`simple_consumer.py`** — The "sanity check" consumer. It just logs every message to stdout with metadata (partition, offset, timestamp). Sounds trivial, but it's invaluable for debugging. When something goes wrong, this is the first thing you check.

- **`aggregator_consumer.py`** — The brains. Contains `TradeAggregator`, which maintains a sliding window of the last 20 trades per symbol and calculates:
  - **VWAP** (Volume-Weighted Average Price) — the "true" average price, weighted by how much was traded at each price
  - Average, min, max price
  - Price change percentage
  - Total volume

  Every 10 trades, it publishes the metrics to the `aggregated-metrics` topic. This is a **producer AND consumer** — a common Kafka pattern called a "stream processor."

- **`storage_consumer.py`** — Writes trades to disk in JSON Lines format (one JSON object per line). Batches 50 messages before writing for efficiency. The JSONL format was chosen because it's trivially appendable (no need to parse the whole file to add a line) and every data warehouse on earth can import it.

### `shared/`

- **`healthcheck.py`** — A lightweight HTTP server that runs in a background daemon thread. Exposes `GET /healthz` on a configurable port. This is what Kubernetes liveness/readiness probes hit to know if a service is alive. It's dead simple on purpose — health checks should never be the thing that crashes your app.

### `tests/`

- **`test_aggregator.py`** — Tests the `TradeAggregator` class thoroughly: single trades, multiple trades, VWAP math, sliding window eviction, multi-symbol independence, edge cases (zero volume).

- **`test_healthcheck.py`** — Spins up the health server on a test port, verifies `/healthz` returns 200 and `/unknown` returns 404.

- **`test_serialization.py`** — Verifies that trade and metrics messages survive a JSON encode/decode round-trip without data loss.

### Root Files

- **`docker-compose.yml`** — The full local stack: Zookeeper, Kafka, Kafka UI, producer, and all 3 consumers. Build contexts point to the repo root so the `shared/` module is available. Every service has a health check.

- **`create_topics.sh`** — Creates the 4 Kafka topics with proper partition counts and 7-day retention. Run this once after Kafka starts.

- **`pyproject.toml`** — Linting config (ruff) and test config (pytest). Ruff enforces import sorting, removes unused imports, and catches common bugs.

- **`ROADMAP.md`** — The full V1 roadmap, from hardening (Milestone 0) through paper portfolio trading (Milestone 2) to K8s deployment (Milestone 4).

---

## Technologies and Why We Chose Them

| Technology | Why |
|---|---|
| **Apache Kafka** | The industry standard for real-time streaming. Handles millions of messages/sec, provides ordering guarantees, and has a mature ecosystem. |
| **Python** | Fast to iterate, great libraries for data processing (pandas), and the Finnhub SDK is Python-first. |
| **Snappy compression** | ~50% size reduction with nearly zero CPU overhead. Perfect for high-throughput pipelines where you're bandwidth-constrained. |
| **Docker + Compose** | Reproducible environments. "Works on my machine" becomes "works on every machine." |
| **JSON Lines** | Simpler than Parquet for our current scale, appendable, and universally importable. We'll move to a proper database in Milestone 1. |
| **ruff** | Blazing fast Python linter (written in Rust). Replaces flake8, isort, and pyupgrade in a single tool. |

---

## Lessons Learned (The Hard-Won Kind)

### 1. Build contexts in Docker Compose are trickier than they look

**The bug:** When we added the `shared/` module, the Dockerfiles couldn't `COPY shared/ ./shared/` because the build context was set to `./producer` or `./consumers` — and `shared/` lives one directory up.

**The fix:** Changed the build context to `.` (repo root) and updated all `COPY` paths to be relative from root: `COPY producer/producer.py .` instead of `COPY producer.py .`.

**The lesson:** Always think about build context *before* adding shared code. A monorepo with shared modules almost always needs the repo root as the build context.

### 2. Health checks are not optional for containers

If you don't have a health endpoint, Kubernetes (and Docker Compose) has no idea if your app is actually working. It could be stuck in an infinite loop, deadlocked, or silently dropping messages — and the orchestrator would happily report it as "Running."

We added a tiny threaded HTTP server that costs almost nothing but gives us proper liveness probes. The key insight: run it as a **daemon thread** so it dies automatically when the main process exits.

### 3. Manual offset commits are worth the complexity

The simple consumer uses auto-commit (easy, but can lose messages if you crash between commit and processing). The aggregator and storage consumers use manual commits — they only commit *after* successfully processing/writing data. Yes, it's more code. But it's the difference between "we think we processed everything" and "we *know* we did."

### 4. Partition by what you query by

We partition by stock symbol. This seems obvious in hindsight, but the alternative (round-robin partitioning) would mean the aggregator might see AAPL trades out of order across partitions. Partitioning by symbol guarantees ordering *per symbol*, which is exactly what we need for moving averages and VWAP.

### 5. Test the math, not the plumbing

Our tests focus on the `TradeAggregator` — the actual business logic. We don't try to spin up a real Kafka cluster in tests (that's integration testing, and it belongs in CI with Docker). Unit tests should be fast, focused, and runnable without external dependencies.

---

## How Good Engineers Think About This

1. **Start with the data flow.** Before writing a single line of code, draw the arrows. Where does data come from? Where does it go? What transformations happen? The architecture diagram came first, the code came second.

2. **Make it work, make it right, make it fast.** Milestone 0 is about "make it right" — adding tests, linting, and health checks to the code that already works. Resist the urge to optimize before you have confidence in correctness.

3. **Design for operability.** Health checks, structured logging, graceful shutdown handlers — these aren't features for users, they're features for the person who gets paged at 3 AM. That person might be you.

4. **Keep services small and focused.** Each consumer does exactly one thing. The aggregator doesn't also write to disk. The storage consumer doesn't calculate metrics. This makes each piece independently testable, deployable, and scalable.

---

## What's Next

Check `ROADMAP.md` for the full plan. The short version:

- **Milestone 1**: FastAPI REST service + PostgreSQL (give the data an API and a real database)
- **Milestone 2**: Paper portfolio engine (the actual product)
- **Milestone 3**: Pluggable trading strategies and alerts
- **Milestone 4**: Kubernetes deployment
- **Milestone 5**: Monitoring and observability

We're building something that could genuinely be useful — not just a demo, but a tool for testing trading ideas against real market data in real time. The foundation is solid. Now we build on it.
