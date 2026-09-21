# AgentGuard 单模式裁剪实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 DeepXDR 裁剪为只支持智能体安全分析的 AgentGuard 系统，并彻底移除 baseline、Redis、网络探针、TTP/MITRE 分析及其数据库和界面。

**Architecture:** nono shim 将 diff 保存到 MinIO，并把经过边界校验的会话事件直接发布到 Kafka `agent.session.finished`。单一 ai-agent 进程消费会话和回退 Topic，使用 LLM 裁决后写入 PostgreSQL，并通过精简的 FastAPI 和 Web UI 提供会话审阅、接受、回退和删除操作。

**Tech Stack:** Python 3.11、FastAPI、SQLAlchemy/asyncpg、Kafka/aiokafka、MinIO/S3/boto3、LangGraph、OpenAI SDK、Alpine.js、Docker Compose、pytest

**Spec:** `docs/superpowers/specs/2026-09-10-agentguard-only-design.md`

## Global Constraints

- 最终运行时只依赖 Kafka、PostgreSQL、MinIO、ai-agent 和 web-ui。
- 不保留网络安全分析兼容开关、隐藏页面或废弃 ORM 模型。
- AgentGuard 业务表仅为 `agent_sessions`、`agent_adjudications`、`agent_rollbacks`。
- 旧网络分析表通过独立显式迁移删除，应用启动和测试不得自动执行删表。
- 真实数据库删表操作不属于本实施计划的自动执行范围。
- nono 工作区和 state home 路径安全策略、防重复回退和 fail-closed 行为必须保持。
- Commit message 必须以 `feat`、`fix`、`docs`、`style`、`refactor`、`perf`、`test`、`chore` 或 `revert` 开头。
- 每个任务开始前先确认 `git status --short`，不得覆盖无关用户改动。

---

## 文件结构决策

最终保留的核心结构：

```text
ai_agent/
├── agent_guard/                 # diff、规则、LLM、Kafka、repository、rollback
├── api_server/
│   ├── __init__.py
│   ├── main.py                  # AgentGuard-only FastAPI factory
│   ├── routes.py                # health + agent session routes
│   └── schemas.py               # AgentGuard API schemas
├── shared/
│   ├── database/
│   │   ├── bootstrap.py         # PostgreSQL-only bootstrap
│   │   ├── connection.py        # PostgreSQL-only connection manager
│   │   └── models.py            # 三张 AgentGuard 表
│   └── utils/                   # 仅保留实际使用的日志/时间工具
├── Dockerfile
├── main.py                      # AgentGuardSystem
└── pyproject.toml               # 最小依赖
deploy/
├── docker-compose-agentguard.yml
├── AGENTGUARD_SMOKE.md
└── migrations/
    └── drop_network_analysis_tables.sql
scripts/
├── agentguard-compose
├── agentguard-smoke-nono.sh
├── agentguard_path_policy.py
├── agentguard_smoke_cases.py
└── nono
web_ui/
└── src/web/
    ├── dashboard.py             # AgentGuard-only proxy
    └── templates/dashboard.html # AgentGuard-only UI
```

不新建第二套 repository 或配置框架；先在现有路径上收缩，降低导入迁移风险。

---

### Task 1: 让智能体会话绕过 baseline 直接进入 AgentGuard

**Files:**

- Modify: `ai_agent/agent_guard/nono_shim.py`
- Modify: `ai_agent/agent_guard/nono_wrapper.py`
- Modify: `ai_agent/agent_guard/consumer.py`
- Create: `ai_agent/agent_guard/event_validation.py`
- Modify: `tests/agent_guard/test_nono_shim.py`
- Modify: `tests/agent_guard/test_nono_wrapper.py`
- Modify: `tests/agent_guard/test_consumer.py`
- Create: `tests/agent_guard/test_event_validation.py`

**Interfaces:**

- Produces: `validate_finished_session_event(event: dict[str, Any]) -> dict[str, Any]`，成功时返回规范化浅拷贝，失败时抛出 `ValueError`。
- Produces: shim 默认 Topic `agent.session.finished`，环境变量 `DEEPXDR_AGENT_SESSION_TOPIC` 可覆盖。
- Consumes: `AgentSessionEventHandler.handle(event, cancellation_token=...)` 在任何数据库写入或 LLM 调用前执行验证。

- [ ] **Step 1: 为直接 Topic 和事件校验写失败测试**

在 `tests/agent_guard/test_nono_shim.py` 的 Kafka publisher 测试中断言默认 Topic：

```python
assert published["topic"] == "agent.session.finished"
```

在 `tests/agent_guard/test_event_validation.py` 添加：

```python
import pytest

from ai_agent.agent_guard.event_validation import validate_finished_session_event


def valid_event():
    return {
        "type": "agent_session",
        "event_type": "finished",
        "run_id": "run-1",
        "original_request": "update README",
        "workspace": "/workspace/project",
        "diff_ref": {"uri": "s3://agent-diffs/run-1.diff", "sha256": "abc"},
        "nono": {"session_id": "session-1", "state_home": "/state/nono"},
    }


def test_valid_finished_session_is_normalized_without_mutating_input():
    event = valid_event()
    normalized = validate_finished_session_event(event)
    assert normalized is not event
    assert normalized["source"] == "nono-path-shim"
    assert normalized["category"] == "agent_runtime_change"
    assert "baseline_action" not in normalized


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (("type",), "other"),
        (("event_type",), "started"),
        (("run_id",), ""),
        (("original_request",), ""),
        (("workspace",), "relative/path"),
        (("diff_ref", "uri"), ""),
        (("diff_ref", "sha256"), ""),
        (("nono", "session_id"), ""),
        (("nono", "state_home"), ""),
    ],
)
def test_invalid_finished_session_is_rejected(path, value):
    event = valid_event()
    target = event
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    with pytest.raises(ValueError):
        validate_finished_session_event(event)
```

- [ ] **Step 2: 运行测试并确认失败**

Run:

```bash
pytest -q tests/agent_guard/test_event_validation.py tests/agent_guard/test_nono_shim.py tests/agent_guard/test_nono_wrapper.py tests/agent_guard/test_consumer.py
```

Expected: FAIL，原因包括 `event_validation` 模块不存在或默认发布 Topic 仍为 `events`。

- [ ] **Step 3: 实现会话事件边界校验**

新增 `ai_agent/agent_guard/event_validation.py`：

```python
from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any


def validate_finished_session_event(event: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(event, dict):
        raise ValueError("agent session event must be an object")
    if event.get("type") != "agent_session":
        raise ValueError("agent session event type must be agent_session")
    if event.get("event_type") != "finished":
        raise ValueError("agent session event_type must be finished")
    for field in ("run_id", "original_request", "workspace"):
        if not isinstance(event.get(field), str) or not event[field].strip():
            raise ValueError(f"agent session event requires {field}")
    if not Path(event["workspace"]).is_absolute():
        raise ValueError("agent session workspace must be absolute")
    diff_ref = event.get("diff_ref")
    if not isinstance(diff_ref, dict) or not diff_ref.get("uri") or not diff_ref.get("sha256"):
        raise ValueError("agent session event requires diff_ref.uri and diff_ref.sha256")
    nono = event.get("nono")
    if not isinstance(nono, dict) or not nono.get("session_id") or not nono.get("state_home"):
        raise ValueError("agent session event requires nono.session_id and nono.state_home")
    normalized = deepcopy(event)
    normalized.setdefault("source", "nono-path-shim")
    normalized["category"] = "agent_runtime_change"
    normalized.pop("baseline_action", None)
    return normalized
```

在 `consumer.py` 中，在调用 `process_finished_session_event` 之前调用该函数，并把返回值用于后续持久化和分析。

- [ ] **Step 4: 将 shim 和 wrapper 默认 Topic 改为专用 Topic**

`nono_shim.py` 的 Topic 选择改为：

```python
topic = os.getenv("DEEPXDR_AGENT_SESSION_TOPIC", "agent.session.finished")
```

`nono_wrapper.py` 的 `events_topic` 参数重命名为 `session_topic`，默认值为 `agent.session.finished`；删除 `events`、`KAFKA_RAW_EVENTS_TOPIC` 和 `baseline_action` 语义。

- [ ] **Step 5: 运行 Task 1 测试**

Run:

```bash
pytest -q tests/agent_guard/test_event_validation.py tests/agent_guard/test_nono_shim.py tests/agent_guard/test_nono_wrapper.py tests/agent_guard/test_consumer.py tests/agent_guard/test_runtime_consumer.py
```

Expected: PASS。

- [ ] **Step 6: 提交 Task 1**

```bash
git add ai_agent/agent_guard tests/agent_guard
git commit -m "refactor:让智能体会话直接进入AgentGuard"
```

---

### Task 2: 将后端入口和 API 裁剪为 AgentGuard 单模式

**Files:**

- Modify: `ai_agent/main.py`
- Modify: `ai_agent/api_server/main.py`
- Modify: `ai_agent/api_server/routes.py`
- Modify: `ai_agent/api_server/schemas.py`
- Modify: `ai_agent/api_server/__init__.py`
- Modify: `ai_agent/shared/utils/config.py`
- Modify: `tests/api_server/test_agent_guard_routes.py`
- Create: `tests/api_server/test_agent_guard_app.py`

**Interfaces:**

- Produces: `create_app(agent_session_repository, agent_rollback_publisher) -> FastAPI`。
- Produces: `AgentGuardSystem.initialize/start/shutdown`。
- Retains: six endpoints defined in the spec and `X-API-Key` authentication behavior.
- Consumes: `AgentGuardRuntime`, `SqlAlchemyAgentSessionRepositoryProvider`, `AgentGuardConfig`。

- [ ] **Step 1: 写 AgentGuard-only OpenAPI 失败测试**

新增 `tests/api_server/test_agent_guard_app.py`：

```python
from ai_agent.agent_guard.repository import InMemoryAgentSessionRepository
from ai_agent.api_server.main import create_app


class PublisherStub:
    async def publish(self, event):
        return None


def test_openapi_contains_only_agentguard_business_routes():
    app = create_app(InMemoryAgentSessionRepository(), PublisherStub())
    paths = set(app.openapi()["paths"])
    assert paths == {
        "/health",
        "/agent-sessions",
        "/agent-sessions/{run_id}",
        "/agent-sessions/{run_id}/accept",
        "/agent-sessions/{run_id}/rollback",
    }


def test_openapi_has_no_network_analysis_terms():
    document = str(
        create_app(InMemoryAgentSessionRepository(), PublisherStub()).openapi()
    ).lower()
    for forbidden in ("short-ttp", "long-ttp", "mitre", "event detail", "feedback"):
        assert forbidden not in document
```

复用现有 `InMemoryAgentSessionRepository` 和 publisher stub 作为 fixture；删除接口与详情共享同一路径，所以 paths 集合中只出现一次 `/agent-sessions/{run_id}`。

- [ ] **Step 2: 运行 API 测试并确认失败**

Run:

```bash
pytest -q tests/api_server/test_agent_guard_app.py tests/api_server/test_agent_guard_routes.py
```

Expected: FAIL，因为 `create_app` 仍要求窗口/TTP 组件且 OpenAPI 包含网络分析路由。

- [ ] **Step 3: 精简 schema 和 routes**

`schemas.py` 仅保留 health、分页 AgentSession、详情、accept、rollback 和 delete 响应模型。`routes.py` 删除所有 TTP、event、stats、feedback、queue 和 system status 导入、全局变量及路由。

保留的 health 响应改为：

```python
return {
    "status": "healthy",
    "service": "agent-guard",
    "components": {
        "agent_session_repository": "healthy" if agent_session_repository else "unhealthy",
        "rollback_publisher": "healthy" if agent_rollback_publisher else "unhealthy",
    },
}
```

业务接口继续使用 `require_api_key`；health 可保持无需 API Key，以支持容器健康检查。

- [ ] **Step 4: 重写 AgentGuard-only app factory**

`api_server/main.py` 不再导入 `ttp_generator` 或管理 Long TTP feedback timer：

```python
def create_app(agent_session_repository=None, agent_rollback_publisher=None) -> FastAPI:
    app = FastAPI(
        title="AgentGuard API",
        description="AI 智能体变更风险分析与恢复 API",
        version="1.0.0",
    )
    # 保留现有受限 CORS 中间件
    set_agent_guard_components(agent_session_repository, agent_rollback_publisher)
    app.include_router(router)
    return app
```

- [ ] **Step 5: 将 `main.py` 改成单模式入口**

删除 `KafkaEventConsumer`、`DynamicEventWindowManager`、`ShortTTPGenerator` 和 `_handle_new_event`。`AgentGuardSystem.initialize()` 只初始化数据库、LLM、runtime 和 API：

```python
await init_database(self.config.database_url)
db_manager = init_db_manager(self.config.database_url)
await db_manager.initialize()
self.agent_guard_runtime = AgentGuardRuntime(...)
await self.agent_guard_runtime.start()
self.api_app = create_app(
    SqlAlchemyAgentSessionRepositoryProvider(),
    self.agent_guard_runtime.rollback_publisher(),
)
```

关闭顺序为 runtime 后 database manager。删除 `AGENT_GUARD_ENABLED` 分支；若旧 `AgentGuardConfig.enabled` 暂时仍存在，在本任务中要求必须为 true，Task 5 再移除该字段。

- [ ] **Step 6: 精简运行配置但暂不移除数据库 Redis 参数**

`shared/utils/config.py` 删除 Elasticsearch、窗口、TTP、研究、MCP 和 MITRE 配置字段，只保留 database、Kafka、API、日志和 OpenAI 字段。Redis 参数在 Task 3 与连接层一起删除，避免中间提交导入失败。

- [ ] **Step 7: 运行后端测试**

Run:

```bash
pytest -q tests/api_server/test_agent_guard_app.py tests/api_server/test_agent_guard_routes.py tests/agent_guard
python -m compileall -q ai_agent
```

Expected: PASS。

- [ ] **Step 8: 提交 Task 2**

```bash
git add ai_agent/main.py ai_agent/api_server ai_agent/shared/utils/config.py tests/api_server
git commit -m "refactor:将后端裁剪为AgentGuard单模式"
```

---

### Task 3: 将数据库裁剪为 PostgreSQL 和三张 AgentGuard 表

**Files:**

- Modify: `ai_agent/shared/database/models.py`
- Modify: `ai_agent/shared/database/connection.py`
- Modify: `ai_agent/shared/database/bootstrap.py`
- Modify: `ai_agent/shared/database/__init__.py`
- Delete: `ai_agent/shared/database/repositories.py`
- Delete: `ai_agent/shared/database/elastic_repositories.py`
- Delete: `ai_agent/shared/database/elasticsearch_client_v8.py`
- Delete: `ai_agent/shared/database/es_common.py`
- Create: `deploy/migrations/drop_network_analysis_tables.sql`
- Modify: `tests/shared_database/test_agent_guard_models.py`
- Create: `tests/shared_database/test_postgres_only_connection.py`
- Create: `tests/shared_database/test_drop_network_tables_migration.py`

**Interfaces:**

- Produces: `init_db_manager(database_url: str) -> DatabaseManager`。
- Produces: `init_database(database_url: str | None = None) -> None`。
- Retains: `get_db()` and AgentGuard rollback compatibility migrations.
- Produces: explicit non-automatic SQL migration deleting only the approved network tables.

- [ ] **Step 1: 写 ORM 表集合失败测试**

更新 `tests/shared_database/test_agent_guard_models.py`：

```python
from ai_agent.shared.database.connection import Base
import ai_agent.shared.database.models  # noqa: F401


def test_only_agentguard_business_tables_are_registered():
    assert set(Base.metadata.tables) == {
        "agent_sessions",
        "agent_adjudications",
        "agent_rollbacks",
    }
```

新增连接层测试，断言 `DatabaseManager` 不再有 `redis_url`、`redis_client` 或 `get_redis_client`。

- [ ] **Step 2: 写删表迁移白名单失败测试**

`tests/shared_database/test_drop_network_tables_migration.py` 读取 SQL，提取 `DROP TABLE IF EXISTS` 表名并断言精确集合：

```python
EXPECTED = {
    "events", "short_ttps", "long_ttps", "short_ttp_events",
    "long_ttp_events", "long_ttp_short_ttps", "processing_status",
    "system_metrics", "long_ttp_generations", "langgraph_checkpoints",
    "langgraph_writes", "langgraph_blobs",
}
assert dropped_tables == EXPECTED
assert not {"agent_sessions", "agent_adjudications", "agent_rollbacks"} & dropped_tables
```

- [ ] **Step 3: 运行数据库测试并确认失败**

Run:

```bash
pytest -q tests/shared_database
```

Expected: FAIL，metadata 包含网络表，连接管理器仍创建 Redis 客户端，迁移文件不存在。

- [ ] **Step 4: 删除网络 ORM 和 repository**

`models.py` 仅保留 `AgentSession`、`AgentAdjudication`、`AgentRollback`。确保外键删除行为与现有 repository 测试一致，不改变列名、默认值和索引名。

删除四个传统 repository/Elasticsearch 文件，并使用 `rg` 清除所有残余导入。

- [ ] **Step 5: 将连接层改成 PostgreSQL-only**

`DatabaseManager.__init__` 只接收 `database_url`；删除 Redis import、初始化、关闭和 getter。保留 SQLAlchemy engine/session、`create_tables()`、`get_session()` 和 AgentGuard rollback 兼容性迁移。

`bootstrap.py` 改成：

```python
async def init_database(database_url: str | None = None) -> None:
    database_url = database_url or os.getenv("DATABASE_URL")
    if not database_url:
        raise ValueError("DATABASE_URL is required")
    db_manager = init_db_manager(database_url)
    try:
        await db_manager.initialize()
        await db_manager.create_tables()
    finally:
        await db_manager.close()
```

- [ ] **Step 6: 创建显式旧表清理迁移**

`deploy/migrations/drop_network_analysis_tables.sql` 内容使用事务和精确表名：

```sql
BEGIN;
DROP TABLE IF EXISTS long_ttp_short_ttps CASCADE;
DROP TABLE IF EXISTS long_ttp_events CASCADE;
DROP TABLE IF EXISTS short_ttp_events CASCADE;
DROP TABLE IF EXISTS long_ttp_generations CASCADE;
DROP TABLE IF EXISTS long_ttps CASCADE;
DROP TABLE IF EXISTS short_ttps CASCADE;
DROP TABLE IF EXISTS events CASCADE;
DROP TABLE IF EXISTS processing_status CASCADE;
DROP TABLE IF EXISTS system_metrics CASCADE;
DROP TABLE IF EXISTS langgraph_writes CASCADE;
DROP TABLE IF EXISTS langgraph_blobs CASCADE;
DROP TABLE IF EXISTS langgraph_checkpoints CASCADE;
COMMIT;
```

文件头注释写明备份命令、显式 `psql -f` 用法和验证查询。应用启动代码不得引用该文件。

- [ ] **Step 7: 运行数据库和 AgentGuard repository 测试**

Run:

```bash
pytest -q tests/shared_database tests/agent_guard/test_sql_repository.py tests/api_server/test_agent_guard_routes.py
python -m compileall -q ai_agent/shared ai_agent/agent_guard
```

Expected: PASS。

- [ ] **Step 8: 提交 Task 3**

```bash
git add ai_agent/shared/database deploy/migrations tests/shared_database
git commit -m "refactor:删除网络分析数据库模型和Redis连接"
```

---

### Task 4: 将 Web UI 裁剪为智能体安全单模式

**Files:**

- Modify: `web_ui/src/web/dashboard.py`
- Modify: `web_ui/src/web/templates/dashboard.html`
- Modify: `web_ui/README.md`
- Modify: `web_ui/README_EN.md`
- Modify: `tests/web_ui/test_agent_guard_dashboard_template.py`
- Modify: `tests/web_ui/test_agent_session_proxy.py`
- Create: `tests/web_ui/test_agentguard_only_dashboard.py`

**Interfaces:**

- Retains proxies: list/detail/accept/rollback/delete under `/api/agent-sessions`。
- Deletes: TTP/event/stats/feedback proxies and `/ws`。
- Produces: `/` renders an AgentGuard-only dashboard with existing action semantics.

- [ ] **Step 1: 写单模式模板和路由失败测试**

新增 `tests/web_ui/test_agentguard_only_dashboard.py`：

```python
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
TEMPLATE = ROOT / "web_ui/src/web/templates/dashboard.html"
DASHBOARD = ROOT / "web_ui/src/web/dashboard.py"


def test_template_is_agentguard_only():
    html = TEMPLATE.read_text(encoding="utf-8")
    assert "Agent Guard Sessions" in html or "智能体安全分析" in html
    for forbidden in (
        "analysisMode", "switchToNetworkMode", "switchToAgentMode",
        "shortTTPs", "longTTPs", "suricata_alert", "openrasp_alert", "falco_alert",
    ):
        assert forbidden not in html


def test_web_proxy_has_no_network_routes():
    source = DASHBOARD.read_text(encoding="utf-8")
    for forbidden in (
        "/api/short-ttps", "/api/long-ttps", "/api/stats",
        "/api/ttp/", "/api/proxy/events/", "@app.websocket",
    ):
        assert forbidden not in source
```

- [ ] **Step 2: 运行 Web UI 测试并确认失败**

Run:

```bash
pytest -q tests/web_ui
```

Expected: FAIL，模板仍包含双模式和 TTP，dashboard 仍包含网络代理。

- [ ] **Step 3: 精简 Web 代理**

`dashboard.py` 保留静态文件、首页、统一 backend request helper 和五组 AgentGuard 代理。删除 `ConnectionManager`、WebSocket、统计、TTP、event、feedback 代码及未使用 import。

所有代理继续：

- 携带 `X-API-Key`。
- 保留后端状态码和错误 detail。
- 对超时/连接失败返回 503。
- rollback 原样转发 JSON body。

- [ ] **Step 4: 精简模板为 AgentGuard 首页**

以现有 AgentGuard 区域为基础保留列表、详情、分页和操作方法，删除网络模式 DOM/JS/CSS。初始化固定执行 `loadAgentSessions(1)`，不读写 analysis mode localStorage。

必须保留现有防回归行为：

- 已接受或已请求回退后隐藏动作按钮。
- 手工翻页请求优先于后台轮询。
- 过期请求响应不得覆盖最新页。
- 刷新失败时保留上一次成功数据。
- fallback handler 不拦截 Alpine click。

- [ ] **Step 5: 更新 Web UI 中英文 README**

文档只列出 AgentGuard 页面、五组代理接口、`API_BASE_URL`、`BACKEND_API_KEY` 和端口，不再描述 TTP、图表、WebSocket 或网络告警。

- [ ] **Step 6: 运行 Web UI 测试**

Run:

```bash
pytest -q tests/web_ui
python -m compileall -q web_ui/src/web
```

Expected: PASS。

- [ ] **Step 7: 提交 Task 4**

```bash
git add web_ui tests/web_ui
git commit -m "refactor:将Web界面裁剪为智能体安全单模式"
```

---

### Task 5: 精简部署、配置和 Python 依赖

**Files:**

- Modify: `deploy/docker-compose-agentguard.yml`
- Delete: `deploy/docker-compose-agent.yml`
- Delete: `deploy/docker-compose-agent-all-in-one.yml`
- Delete: `deploy/docker-compose-app.yml`
- Modify: `scripts/agentguard-compose`
- Modify: `tests/agent_guard/test_agentguard_compose.py`
- Modify: `ai_agent/pyproject.toml`
- Modify: `ai_agent/Dockerfile`
- Modify: `web_ui/pyproject.toml`
- Modify: `web_ui/Dockerfile`
- Create: `tests/agent_guard/test_runtime_dependencies.py`

**Interfaces:**

- Produces: Compose services exactly `kafka`, `postgres`, `minio`, `minio-init`, `ai-agent`, `web-ui`。
- Produces: `scripts/agentguard-compose` accepts only `deploy/docker-compose-agentguard.yml`。
- Retains: host workspace/state root validation and identical source/target bind mounts.

- [ ] **Step 1: 写 Compose 服务集合失败测试**

更新 `test_agentguard_compose.py`：

```python
def test_agentguard_compose_has_only_required_services():
    config = yaml.safe_load(COMPOSE_FILE.read_text(encoding="utf-8"))
    assert set(config["services"]) == {
        "kafka", "postgres", "minio", "minio-init", "ai-agent", "web-ui"
    }
    text = COMPOSE_FILE.read_text(encoding="utf-8").lower()
    for forbidden in ("baseline-adjudication", "redis", "elasticsearch", "falco", "openrasp", "suricata"):
        assert forbidden not in text
```

删除允许 all-in-one Compose 的测试，改为断言任何非 AgentGuard Compose 都被拒绝。

- [ ] **Step 2: 写依赖黑名单失败测试**

新增 `test_runtime_dependencies.py`，使用 `tomllib` 读取依赖并断言包名不包含：

```python
FORBIDDEN = {
    "redis", "elasticsearch", "mitreattack-python", "mcp", "pandas",
    "pymupdf", "beautifulsoup4", "supabase", "azure-identity",
    "azure-search-documents", "tavily-python", "duckduckgo-search",
    "exa-py", "arxiv", "linkup-sdk", "langchain-anthropic",
    "langchain-deepseek", "langchain-groq", "langchain-mcp-adapters",
}
```

依赖规范先按 PEP 508 解析出标准化项目名，再比较，避免版本字符串影响。

- [ ] **Step 3: 运行部署与依赖测试并确认失败**

Run:

```bash
pytest -q tests/agent_guard/test_agentguard_compose.py tests/agent_guard/test_runtime_dependencies.py
```

Expected: FAIL，因为 Compose 仍有 baseline/Redis 且 pyproject 仍有网络分析依赖。

- [ ] **Step 4: 精简 Compose**

删除 Redis service/volume、baseline service 和相关 `depends_on`。ai-agent 环境仅保留：

```text
DATABASE_URL
KAFKA_BOOTSTRAP_SERVERS
KAFKA_AGENT_SESSION_TOPIC
KAFKA_AGENT_ROLLBACK_REQUESTED_TOPIC
KAFKA_AGENT_ROLLBACK_COMPLETED_TOPIC
AGENTGUARD_PATHS_VALIDATED
AGENT_GUARD_DIFF_*
AGENT_GUARD_*_TOKEN_LIMIT
API_PORT
BACKEND_API_KEY
LOG_LEVEL
OPENAI_MODEL
OPENAI_API_KEY
OPENAI_BASE_URL
```

删除 `KAFKA_TOPIC`、`KAFKA_GROUP_ID`、`REDIS_URL`、`ELASTICSEARCH_*` 和所有 `BASELINE_*`。宿主机 shim 的 smoke 命令设置 `DEEPXDR_AGENT_SESSION_TOPIC=agent.session.finished`。

- [ ] **Step 5: 删除旧 Compose 并收紧 launcher**

删除三个旧 Compose。`resolve_compose_file()` 只允许默认 AgentGuard 文件，删除 all-in-one 特例，同时保持 canonical path 校验。

- [ ] **Step 6: 按 import 清单精简依赖和镜像**

保留实际必需包：

```toml
dependencies = [
    "pydantic==2.12.5",
    "sqlalchemy==2.0.32",
    "asyncpg==0.29.0",
    "aiokafka==0.11.0",
    "fastapi==0.115.0",
    "uvicorn==0.40.0",
    "langgraph==0.5.4",
    "openai==1.99.2",
    "python-dotenv==1.0.1",
    "boto3>=1.35.0,<2.0.0",
]
```

如果 `rg` 证明 `pydantic-settings`、`structlog` 或其他包仍被保留源码直接导入，则加入精确版本；不为已删除代码保留依赖。setuptools package include 只保留 `api_server*`、`agent_guard*`、`shared*`。

Dockerfile 删除 MITRE 数据、研究系统描述和运行时在线 `pip install boto3`；依赖全部在构建阶段安装。保留 non-root 默认镜像用户，AgentGuard Compose 仅因 nono restore 需要时显式使用 root。

- [ ] **Step 7: 运行部署与依赖测试**

Run:

```bash
pytest -q tests/agent_guard/test_agentguard_compose.py tests/agent_guard/test_runtime_dependencies.py tests/system
docker compose -f deploy/docker-compose-agentguard.yml config >/dev/null
```

Expected: PASS。若 Docker Compose CLI 不可用，记录环境限制，但 pytest 中的 YAML 与路径验证必须通过。

- [ ] **Step 8: 提交 Task 5**

```bash
git add deploy scripts/agentguard-compose ai_agent/pyproject.toml ai_agent/Dockerfile web_ui/pyproject.toml web_ui/Dockerfile tests/agent_guard
git commit -m "chore:移除baseline和Redis部署依赖"
```

---

### Task 6: 物理删除网络分析源码、第三方探针和对应测试

**Files:**

- Delete: `baseline_adjudication/`
- Delete: `third_party/`
- Delete: `ai_agent/data_consumer/`
- Delete: `ai_agent/ttp_generator/`
- Delete: `ai_agent/mitre_attck_agent/`
- Delete: `ai_agent/defense/`
- Delete: `ai_agent/data/`
- Delete: `ai_agent/.cache/mitre_attack/`
- Delete: `ai_agent/shared/models/`
- Delete: `ai_agent/shared/utils/elasticsearch_config.py`
- Create: `tests/test_agentguard_only_repository.py`

**Interfaces:**

- Produces: repository contains no network probe, baseline, TTP, MITRE or Elasticsearch implementation/reference outside historical docs under `.git`。
- Consumes: Tasks 1–5 must have removed all runtime imports before deletion.

- [ ] **Step 1: 写仓库边界失败测试**

新增 `tests/test_agentguard_only_repository.py`：

```python
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_network_analysis_directories_are_absent():
    forbidden = [
        "baseline_adjudication", "third_party", "ai_agent/data_consumer",
        "ai_agent/ttp_generator", "ai_agent/mitre_attck_agent",
        "ai_agent/defense", "ai_agent/data", "ai_agent/.cache/mitre_attack",
    ]
    assert [path for path in forbidden if (ROOT / path).exists()] == []


def test_runtime_source_has_no_network_analysis_imports():
    source = "\n".join(
        path.read_text(encoding="utf-8", errors="ignore")
        for root in (ROOT / "ai_agent", ROOT / "web_ui")
        for path in root.rglob("*.py")
    ).lower()
    for forbidden in ("ttp_generator", "mitre_attck_agent", "data_consumer", "elasticsearch"):
        assert forbidden not in source
```

- [ ] **Step 2: 运行边界测试并确认失败**

Run:

```bash
pytest -q tests/test_agentguard_only_repository.py
```

Expected: FAIL，禁止目录仍然存在。

- [ ] **Step 3: 删除网络实现目录**

使用 `git rm -r` 精确删除本任务 Files 列表中的目录，不使用通配符。删除前用 `git status --short` 确认目录中没有未提交用户改动。

- [ ] **Step 4: 删除网络专属测试**

精确删除：

```text
tests/baseline_adjudication/
tests/test_attack_rag_workflow.py
tests/test_cleanup_baseline.py
tests/test_defense_manager.py
tests/test_kafka_consumer_offsets.py
tests/test_long_ttp_mitre_result.py
tests/test_mcp_client_env.py
tests/test_mcp_server_security.py
tests/test_prompt_evidence_sources.py
tests/test_short_ttp_workflow.py
tests/test_truncate_messages_security.py
```

删除任何只测试已移除网络数据库 repository 的文件，但不删除 AgentGuard、API、system 或 web_ui 测试。

- [ ] **Step 5: 扫描残余运行时代码**

Run:

```bash
rg -n -i --glob '!docs/superpowers/**' --glob '!README*.md' \
  'falco|openrasp|suricata|short.?ttp|long.?ttp|mitre|baseline.adjudication|elasticsearch' \
  ai_agent web_ui deploy scripts tests
```

Expected: 无输出。若命中迁移 SQL 中批准的旧表名，只允许该文件及其白名单测试出现；测试应针对该例外使用明确路径而不是扩大排除范围。

- [ ] **Step 6: 运行保留测试与导入检查**

Run:

```bash
pytest -q
python -m compileall -q ai_agent web_ui scripts
PYTHONPATH=ai_agent python -c "import main; import api_server; import agent_guard.runtime"
```

Expected: PASS。

- [ ] **Step 7: 提交 Task 6**

```bash
git add -A
git commit -m "refactor:删除网络探针和TTP分析源码"
```

---

### Task 7: 更新 AgentGuard 单模式文档和完整验收

**Files:**

- Modify: `README.md`
- Modify: `README_EN.md`
- Modify: `ai_agent/README.md`
- Modify: `ai_agent/README_EN.md`
- Modify: `deploy/AGENTGUARD_SMOKE.md`
- Modify: `scripts/agentguard-smoke-nono.sh`
- Modify: `tests/agent_guard/test_agentguard_compose.py`

**Interfaces:**

- Produces: 单一部署和使用说明，不包含网络分析安装路径。
- Produces: smoke flow `nono shim -> agent.session.finished -> ai-agent -> PostgreSQL -> web-ui -> rollback`。

- [ ] **Step 1: 更新文档断言测试**

文档测试要求根 README 和 smoke 文档包含：

```text
AGENTGUARD_WORKSPACE_ROOT
AGENTGUARD_NONO_STATE_ROOT
scripts/agentguard-compose
agent.session.finished
Kafka
PostgreSQL
MinIO
```

并断言非历史设计/迁移文档不包含 Falco、OpenRASP、Suricata、Short TTP、Long TTP、baseline 或 Redis 部署说明。

- [ ] **Step 2: 运行文档测试并确认失败**

Run:

```bash
pytest -q tests/agent_guard/test_agentguard_compose.py tests/test_agentguard_only_repository.py
```

Expected: FAIL，README 仍主要描述 DeepXDR 网络分析。

- [ ] **Step 3: 重写中英文文档**

根 README 包含：

1. AgentGuard 目标与实验性状态。
2. 五个运行服务的架构图。
3. nono、Docker、LLM 前置条件。
4. 两个宿主机安全根目录配置。
5. `scripts/agentguard-compose up -d --build` 启动流程。
6. nono shim 安装/PATH 和环境变量。
7. 会话分析、接受、回退、删除操作。
8. API 和故障排查。
9. 显式旧表迁移说明与备份警告。

ai-agent 和 web-ui README 只描述各自保留职责。smoke 文档删除 baseline/Redis 服务，并明确 shim 直接发布专用 Topic。

- [ ] **Step 4: 更新 smoke 脚本环境**

`agentguard-smoke-nono.sh` 设置：

```bash
export DEEPXDR_AGENT_SESSION_TOPIC=${DEEPXDR_AGENT_SESSION_TOPIC:-agent.session.finished}
```

不再设置 raw events、baseline 或 Redis 变量。保留 small/medium/large/real-agent 四种策略和路径校验。

- [ ] **Step 5: 运行完整静态和测试验收**

Run:

```bash
git diff --check
pytest -q
python -m compileall -q ai_agent web_ui scripts
docker compose -f deploy/docker-compose-agentguard.yml config >/dev/null
rg -n -i --glob '!docs/superpowers/**' --glob '!deploy/migrations/**' \
  'falco|openrasp|suricata|short.?ttp|long.?ttp|mitre|baseline.adjudication|elasticsearch' \
  ai_agent web_ui deploy scripts tests README.md README_EN.md
```

Expected: diff check、pytest、compileall 和 Compose config 均成功；最终 `rg` 无输出。

- [ ] **Step 6: 可选执行真实 Compose 冒烟测试**

仅当本机 Docker、nono 和 LLM 凭据可用时：

```bash
./scripts/agentguard-compose up -d --build
./scripts/agentguard-smoke-nono.sh small
./scripts/agentguard-compose ps
./scripts/agentguard-compose logs --no-color ai-agent
```

Expected: small 会话出现在 UI/API，产生 adjudication，回退操作恢复文件。测试后使用：

```bash
./scripts/agentguard-compose down
```

不使用 `down -v`，避免删除持久数据卷。

- [ ] **Step 7: 提交文档与验收调整**

```bash
git add README.md README_EN.md ai_agent/README.md ai_agent/README_EN.md web_ui/README.md web_ui/README_EN.md deploy/AGENTGUARD_SMOKE.md scripts/agentguard-smoke-nono.sh tests
git commit -m "docs:更新AgentGuard单模式部署与使用说明"
```

- [ ] **Step 8: 最终提交审计**

Run:

```bash
git status --short --branch
git log --oneline --decorate -10
git diff origin/main...HEAD --stat
git diff origin/main...HEAD --check
```

Expected: 工作区干净；所有新提交使用允许的前缀；diff check 无错误；变更范围只覆盖设计批准的裁剪工作。

不要自动 push。完成本地验收后汇报测试证据、未运行的外部冒烟项和数据库迁移的显式执行命令，由用户决定何时推送及何时对真实数据库执行删表。
