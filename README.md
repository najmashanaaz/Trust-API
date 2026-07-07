# 🔍 API Reliability Monitoring Platform

A full-stack web application that continuously monitors public APIs and displays
their health, uptime, and reliability on a live dashboard.

---

## 📁 Project Structure

```
api-monitor/
├── backend/
│   ├── main.py        # FastAPI app — routes, CORS, background scheduler
│   ├── monitor.py     # HTTP check logic + reliability score formula
│   ├── database.py    # SQLite connection, table creation, CRUD helpers
│   └── apis.py        # The list of 10+ public APIs we monitor
├── frontend/
│   ├── index.html     # Dashboard HTML (semantic structure)
│   ├── style.css      # Dark glass-morphism theme
│   └── script.js      # Fetch data from backend, render cards + charts
├── database/
│   └── monitor.db     # SQLite database — auto-created on first run
├── requirements.txt   # Python dependencies
└── README.md          # You are here!
```

---

## 🚀 Quick Start

### 1. Install dependencies
```bash
pip install -r requirements.txt
```

### 2. Start the server
```bash
uvicorn backend.main:app --reload --port 8000
```

### 3. Open the dashboard
Visit: [http://localhost:8000](http://localhost:8000)

---

## 📡 API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/` | Serves the dashboard |
| GET | `/api/status` | Current status of all monitored APIs |
| GET | `/api/reliability` | Uptime % and reliability score per API |
| GET | `/api/history/{api_id}` | Full check log history for one API |
| GET | `/health` | Server health check |

---

## 📊 Reliability Score Formula

```
Reliability Score = (70% × Uptime%) + (20% × ResponseTimeScore) + (10% × SuccessRateScore)
```

- **Uptime %** — percentage of checks where the API responded with HTTP 200
- **Response Time Score** — normalized score (faster = higher, capped at 2s)
- **Success Rate Score** — ratio of successful to total checks

---

## 🛠️ Tech Stack

| Layer | Technology |
|-------|------------|
| Backend | Python, FastAPI, Uvicorn |
| HTTP Monitoring | Requests |
| Scheduler | Schedule |
| Database | SQLite (built into Python) |
| Frontend | HTML5, CSS3, JavaScript (no frameworks) |

---

## 🗺️ Roadmap

- [x] Phase 1 — Core monitoring + SQLite + Dashboard
- [ ] Phase 2 — Charts (Chart.js), search/filter, history view
- [ ] Phase 3 — Email alerts, export reports, API comparison
- [ ] VS Code Extension — consumes same FastAPI endpoints
