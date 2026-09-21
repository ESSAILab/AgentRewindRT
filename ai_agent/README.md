# AgentRewindRT ai-agent

`ai_agent` 是 AgentRewindRT 的单一后端进程，负责消费智能体完成事件、读取 MinIO diff、执行规则与 LLM 裁决、写入 PostgreSQL，并提供审阅与回退 API。

## 目录

- `agent_guard/`：事件校验、diff 解析、上下文规划、裁决图、Kafka 和回退执行
- `api_server/`：健康检查与 AgentRewindRT 会话 API
- `shared/database/`：PostgreSQL 连接和三张 AgentRewindRT ORM 表
- `main.py`：运行时与 API 入口

## 必填配置

```text
DATABASE_URL
KAFKA_BOOTSTRAP_SERVERS
BACKEND_API_KEY
OPENAI_API_KEYv
```

常用可选配置：`OPENAI_BASE_URL`、`OPENAI_MODEL`、`KAFKA_AGENT_SESSION_TOPIC`、三个 `AGENT_GUARD_DIFF_*` 凭据变量和上下文预算变量。完整默认值见 `agent_guard/config.py`。

OpenAI SDK 用于调用 OpenAI 兼容的 Chat Completions 接口；可通过 `OPENAI_BASE_URL` 指向内网或第三方兼容服务。它作为项目/容器依赖安装，不要求修改宿主机全局 Python。

## 本地运行

```bash
python3 -m venv .venv
.venv/bin/pip install -e '.[dev]'
set -a; . ./.env; set +a
PYTHONPATH=. .venv/bin/python main.py
```

生产部署推荐使用仓库根目录的 `deploy/docker-compose-agentguard.yml` 和 `scripts/agentguard-compose`。

## API 接口与鉴权

默认后端地址为 `http://localhost:8000`。除健康检查外，下列接口均要求 `X-API-Key` 请求头，其值应与后端环境变量 `BACKEND_API_KEY` 一致。

| 方法 | 路径 | 功能 |
| --- | --- | --- |
| `GET` | `/health` | 查询服务与组件状态 |
| `GET` | `/agent-sessions?page=1&size=20` | 分页查询会话 |
| `GET` | `/agent-sessions/{run_id}` | 查询会话详情 |
| `POST` | `/agent-sessions/{run_id}/accept` | 接受变更 |
| `POST` | `/agent-sessions/{run_id}/rollback` | 请求快照回退 |
| `DELETE` | `/agent-sessions/{run_id}` | 删除会话记录 |

回退接口接收 JSON 请求体，例如 `{"requested_by":"reviewer","snapshot":0}`，并返回回退操作标识与状态。回退异步执行，需查询会话确认最终结果。Web UI 在端口 `30003` 通过 `/api/agent-sessions...` 代理会话接口；端口 `8000` 使用表中的原生路径。
