# TrustAPI Monitor — VS Code Extension

Live AI API reliability scores, downtime alerts, and alternative suggestions right inside VS Code — powered by your local TrustAPI backend.

---

## Prerequisites

Before using the extension, both backend processes must be running:

**Terminal 1 — FastAPI server:**
```bash
cd "Trust-API-main"
pip install -r requirements.txt
uvicorn backend.main:app --reload
```

**Terminal 2 — Monitoring service:**
```bash
cd "Trust-API-main"
python run_monitor.py
```

Copy `.env.example` to `.env` and fill in your Gmail credentials + SECRET_KEY before starting.

---

## Setup & Run the Extension

```bash
cd "Trust-API-main/vscode-extension"
npm install
```

Then press **F5** in VS Code (with the `vscode-extension/` folder open) to launch the **Extension Development Host**.

The extension activates automatically when the workspace contains a `package.json` or `requirements.txt`.

---

## Features

### 1. Reliability Warning at Install Time
When you save `package.json` or `requirements.txt` with a new dependency, the extension checks its reliability score. If the mapped API scores **below 80%**, a warning notification fires with the score and top alternative suggestions.

### 2. Live Downtime Alerts
A background poll (default every 60 s) scans your workspace dependencies against `/api/dependency-scan`. When an API transitions **UP → DOWN**, a VS Code error notification fires immediately — once per outage, not on every poll.

### 3. Smart Alternative Suggestions
Both the install-time warning and the downtime alert include the top 1–2 alternative APIs in the same category (e.g. other `llm_provider` services), ranked by reliability score.

### 4. Dependency Risk Dashboard
Opens automatically on activation. Shows every tracked AI/cloud dependency with:
- Live status (UP / DOWN)
- Reliability score (%)
- Color-coded bar (green ≥ 90, yellow 70–89, red < 70)

**Command palette:** `TrustAPI: Open Dependency Risk Dashboard` or `TrustAPI: Refresh Dependency Risk Dashboard`

---

## Settings

| Setting | Default | Description |
|---|---|---|
| `trustapi.backendUrl` | `http://localhost:8000` | Base URL of the FastAPI backend |
| `trustapi.pollIntervalSeconds` | `60` | How often to poll for downtime alerts |

---

## Tracked Packages

The extension maps these npm/pip packages to monitored APIs:

`openai`, `anthropic`, `@anthropic-ai/sdk`, `groq`, `groq-sdk`, `cohere`, `cohere-ai`, `mistralai`, `@mistralai/mistralai`, `together-ai`, `huggingface_hub`, `transformers`, `@huggingface/inference`, `fireworks-ai`, `boto3`, `@aws-sdk/client-bedrock-runtime`, `@azure/openai`, `azure-ai-inference`, `@google-cloud/aiplatform`, `google-generativeai`, `ibm-watsonx-ai`, and more.

See `backend/package_mapping.py` for the full list.

---

## Offline Behaviour

If the backend is unreachable, the extension shows a muted status bar item:
```
⚠ TrustAPI: backend unreachable
```
No error dialogs are spammed. All features resume automatically once the backend comes back online.
