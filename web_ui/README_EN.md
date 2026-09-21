# AgentRewindRT Web UI

The AgentRewindRT review interface displays AI-agent code-change risk and supports human disposition.

## Features

- Paginated agent-session list with safe polling
- Original request, adjudication, changed files, and diff previews
- Accept, nono rollback request, and alert deletion actions
- Stale-response and duplicate-action protection

## Configuration

| Variable | Description | Default |
| --- | --- | --- |
| `API_BASE_URL` | AgentRewindRT backend URL | `http://localhost:8000` |
| `BACKEND_API_KEY` | Backend API key | empty |
| `HOST` | Listen address | `0.0.0.0` |
| `PORT` | Listen port | `30003` |

## Run

```bash
python run_dashboard.py
```

Open `http://localhost:30003`. The AgentRewindRT Compose deployment at the repository root is recommended for the complete stack.

## Proxy endpoints

- `GET /api/agent-sessions`
- `GET /api/agent-sessions/{run_id}`
- `POST /api/agent-sessions/{run_id}/accept`
- `POST /api/agent-sessions/{run_id}/rollback`
- `DELETE /api/agent-sessions/{run_id}`
