# V1 Roadmap: Real-Time Paper Trading Platform

**Goal**: Deliver a system where a client can consume real-time market data, see aggregated signals, and use that to manage a paper portfolio or adjust trading strategies.

---

## Milestone 0 — Hardening What Exists
*"Make the foundation trustworthy before building on it"*

- [ ] Add `.env.example` with clear setup instructions
- [ ] Add health check endpoints to producer & all consumers (HTTP `/healthz`)
- [ ] Add basic unit tests for aggregation logic and message serialization
- [ ] Add linting config (`ruff` + `pyproject.toml`)
- [ ] Clean up `demo_file.py`
- [ ] Write `FORHARSH.md`

**Deliverable**: A reliable, testable streaming pipeline you can demo with confidence.

---

## Milestone 1 — API & Data Layer
*"Give the data somewhere to live and a way to talk to the outside world"*

- [ ] Replace JSONL file storage with **PostgreSQL** (or SQLite for simplicity)
  - Tables: `trades`, `aggregated_metrics`, `symbols`
  - Schema migrations via `alembic`
- [ ] Build a **FastAPI REST service**:
  - `GET /symbols` — list tracked symbols
  - `GET /symbols/{symbol}/price` — latest price & metrics
  - `GET /symbols/{symbol}/history?window=1h` — recent trade history
  - `GET /metrics` — current aggregated metrics (VWAP, volume, price range)
  - WebSocket endpoint `/ws/stream` — push real-time trades to frontend clients
- [ ] New Kafka consumer: **API feeder** that writes to the DB in near-real-time

**Deliverable**: A queryable API backed by real-time Kafka data.

---

## Milestone 2 — Paper Portfolio Engine
*"The core of what the client actually wants"*

- [x] Portfolio endpoints added to FastAPI service:
  - `POST /portfolio/init` — create/get portfolio
  - `POST /portfolio/trade` — execute a paper buy/sell at current market price
  - `GET /portfolio` — current holdings, cash balance, total value
  - `GET /portfolio/history` — trade log with P&L per trade
  - `GET /portfolio/performance` — returns, max drawdown, win rate
- [x] DB tables: `portfolios`, `positions`, `paper_trades`, `portfolio_snapshots`
- [x] Portfolio valuation consumer: subscribes to `aggregated-metrics`, snapshots portfolio value every 60s
- [x] Starting cash configurable (default $100k)
- [x] 16 new tests (42 total): service logic + API endpoints

**Deliverable**: A working paper trading system where you can buy/sell and track performance.

---

## Milestone 3 — Strategy & Alerts
*"Let the system think for you"*

- [ ] **Strategy engine** — pluggable strategy interface:
  ```python
  class Strategy:
      def on_metric(self, symbol, metrics) -> Signal | None
  ```
  - Ship 2-3 built-in strategies: moving average crossover, VWAP deviation, volume spike
- [ ] **Alerts consumer** — reads `price-alerts` topic, evaluates strategy signals
  - `POST /strategies` — activate/deactivate a strategy
  - `GET /strategies/{id}/signals` — recent signals generated
  - `POST /alerts/rules` — custom alert rules (e.g., "notify when AAPL > $200")
- [ ] Alerts delivered via `price-alerts` topic, consumable via WebSocket

**Deliverable**: Automated signals that can inform (or auto-execute) paper trades.

---

## Milestone 4 — Containerization & Deployment
*"Ship it"*

- [ ] Dockerfiles for new services (API, portfolio, strategy)
- [ ] Update `docker-compose.yml` with full stack
- [ ] **Kubernetes manifests** (`k8s/` directory):
  - Kafka via Strimzi operator or Confluent Helm chart
  - Deployments for each service with liveness/readiness probes
  - ConfigMaps + Secrets for env config
  - Ingress for the API
- [ ] **CI/CD pipeline** (GitHub Actions):
  - Lint → Test → Build images → Push to registry → Deploy
- [ ] Cloud Run alternative: `cloudbuild.yaml` + service YAMLs

**Deliverable**: One-command deployment to K8s or Cloud Run.

---

## Milestone 5 — Observability & Polish
*"Know when things break before the client does"*

- [ ] Prometheus metrics on all services (`/metrics` endpoint)
- [ ] Grafana dashboard: pipeline throughput, consumer lag, portfolio value over time
- [ ] Structured JSON logging across all services
- [ ] Error tracking (Sentry or similar)
- [ ] Rate limiting & basic auth on the API
- [ ] API docs auto-generated via FastAPI's OpenAPI/Swagger

**Deliverable**: Production-grade observability and a polished API experience.

---

## Milestone Dependency Graph

```
M0 (Harden)
 └──▶ M1 (API + DB)
       └──▶ M2 (Portfolio)
       │     └──▶ M3 (Strategies)
       └──▶ M4 (Deploy) ◀── can start in parallel after M1
              └──▶ M5 (Observability)
```

## What a V1 Demo Looks Like

> Client opens the API, sees real-time AAPL/GOOGL/MSFT prices streaming in. They execute
> a few paper trades. A VWAP-deviation strategy fires a "BUY" signal on TSLA. They check
> their portfolio — up 1.2% since morning. All running on K8s with dashboards showing
> Kafka throughput and pipeline health.
