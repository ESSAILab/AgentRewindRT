# AgentRewindRT ai-agent

`ai_agent` is AgentRewindRT's single backend process. It consumes completed agent-session events, loads diffs from MinIO, runs rule and LLM adjudication, writes PostgreSQL records, and exposes review and rollback APIs.

## Layout

- `agent_guard/`: validation, diff parsing, context planning, adjudication graph, Kafka, and rollback execution
- `api_server/`: health and AgentRewindRT session APIs
- `shared/database/`: PostgreSQL connection and three AgentRewindRT ORM tables
- `main.py`: runtime and API entry point

Required variables are `DATABASE_URL`, `KAFKA_BOOTSTRAP_SERVERS`, `BACKEND_API_KEY`, and `OPENAI_API_KEY`. Common optional variables include `OPENAI_BASE_URL`, `OPENAI_MODEL`, `KAFKA_AGENT_SESSION_TOPIC`, MinIO credentials, and context-budget settings.

The OpenAI SDK calls an OpenAI-compatible Chat Completions endpoint. `OPENAI_BASE_URL` may point to an internal or third-party compatible service. The SDK is a project/container dependency and does not require changing the host system Python.

```bash
python3 -m venv .venv
.venv/bin/pip install -e '.[dev]'
set -a; . ./.env; set +a
PYTHONPATH=. .venv/bin/python main.py
```

For production-like deployment, use `deploy/docker-compose-agentguard.yml` through `scripts/agentguard-compose` from the repository root.

## API and authentication

The default backend address is `http://localhost:8000`. All endpoints below, except the health check, require an `X-API-Key` header matching the backend environment variable `BACKEND_API_KEY`.

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/health` | Query service and component status |
| `GET` | `/agent-sessions?page=1&size=20` | List sessions with pagination |
| `GET` | `/agent-sessions/{run_id}` | Retrieve session details |
| `POST` | `/agent-sessions/{run_id}/accept` | Accept changes |
| `POST` | `/agent-sessions/{run_id}/rollback` | Request snapshot rollback |
| `DELETE` | `/agent-sessions/{run_id}` | Delete a session record |

The rollback endpoint accepts a JSON body such as `{"requested_by":"reviewer","snapshot":0}` and returns the rollback operation ID and state. Rollback runs asynchronously; query the session to confirm the final result. The Web UI on port `30003` proxies session endpoints under `/api/agent-sessions...`; the backend on port `8000` uses the native paths listed above.
