# AgentGuard 单模式裁剪设计

## 1. 目标

将 DeepXDR 从同时支持“网络安全分析”和“智能体安全分析”的混合系统，裁剪为只支持智能体安全分析的 AgentGuard 系统。

裁剪完成后：

- 删除网络安全探针、数据汇聚、行为基线、Short TTP、Long TTP、MITRE 调查及其展示能力。
- AgentGuard 不再依赖 `baseline_adjudication`、Redis 或 Elasticsearch。
- 保留 nono 会话采集、diff 证据存储、LLM 风险裁决、人工接受、回退和删除能力。
- 只部署 Kafka、PostgreSQL、MinIO、ai-agent 和 web-ui。

## 2. 范围边界

### 2.1 保留能力

- `scripts/nono` PATH shim 调用真实 nono。
- nono rollback session、diff 提取和恢复。
- diff 写入 MinIO/S3 或现有本地存储实现。
- 智能体会话事件通过 Kafka 传递。
- 基于规则和 LLM 的意图一致性、越权修改、敏感路径及高风险操作分析。
- PostgreSQL 持久化会话、裁决和回退状态。
- AgentGuard 会话列表、详情、接受、回退和删除 API。
- 单模式 Web UI 及 AgentGuard 测试、路径安全策略和冒烟测试。

### 2.2 删除能力

- Falco、OpenRASP、Suricata 及 Filebeat、Logstash 数据采集。
- 示例受保护应用 dotCMS 及传统 app 侧部署。
- 行为基线构建、Redis 基线存储和异常事件裁决。
- 通用安全事件解析、动态事件窗口和传统 Kafka `agent` 消费链路。
- Short TTP、Long TTP、MITRE ATT&CK/RAG、深度研究和人工调查反馈。
- Elasticsearch 数据读写和 MCP 防御/调查集成。
- 网络安全统计、事件详情、TTP API、WebSocket 统计推送及网络模式 UI。
- 网络分析数据库表和未被 AgentGuard 使用的 LangGraph checkpoint 表。

## 3. 目标架构

```text
AI 智能体
    |
    v
nono PATH shim
    |-- diff evidence ----------------------> MinIO
    |
    `-- agent session event
            |
            v
       Kafka: agent.session.finished
            |
            v
       AgentGuard Runtime
            |-- rule analysis
            |-- LLM adjudication
            `-- rollback worker <---------- Kafka: agent.rollback.requested
            |
            v
        PostgreSQL
            |
            v
       AgentGuard REST API
            |
            v
          Web UI
```

回退 API 先在 PostgreSQL 建立持久化请求记录，再向 `agent.rollback.requested` 发布。ai-agent 内的回退消费者调用 nono restore，更新 PostgreSQL，并向 `agent.rollback.completed` 发布完成事件。现有防重复执行和 fail-closed 行为保持不变。

## 4. 事件链路设计

### 4.1 直接发布

当前 shim 默认向 `events` 发布，`baseline_adjudication` 识别 `agent_session` 后仅规范化并转发到 `agent.session.finished`。裁剪后 shim 直接发布到 `agent.session.finished`。

统一使用以下 Topic：

- `agent.session.finished`
- `agent.rollback.requested`
- `agent.rollback.completed`

删除传统 `events` 和 `agent` Topic 配置。shim 的 Topic 配置名称统一为 `DEEPXDR_AGENT_SESSION_TOPIC`，默认值为 `agent.session.finished`。

### 4.2 输入校验

删除基线服务前，将其对智能体事件的有效校验固化到 AgentGuard 消费边界。会话事件至少需要：

- `type == "agent_session"`
- `event_type == "finished"`
- 非空 `run_id`
- 非空 `original_request`
- 非空绝对路径 `workspace`
- `diff_ref.uri` 和 `diff_ref.sha256`
- `nono.session_id`
- `nono.state_home`

无效事件不得写入数据库，也不得触发 LLM；消费者按照现有可靠性策略记录失败并停止或重试，不静默提交无效消息。

## 5. 后端设计

### 5.1 进程入口

`ai_agent/main.py` 重构为唯一的 `AgentGuardSystem`：

1. 读取 AgentGuard、数据库、Kafka、对象存储和 LLM 配置。
2. 初始化 PostgreSQL 和 AgentGuard 三张业务表。
3. 启动 `AgentGuardRuntime`。
4. 创建只包含 AgentGuard 路由的 FastAPI 应用。
5. 启动 Uvicorn。
6. 关闭时先停止消费者和生产者，再释放数据库连接。

不再创建事件窗口、Short TTP 生成器或传统 Kafka 消费器。AgentGuard 是唯一模式，因此删除 `AGENT_GUARD_ENABLED` 功能开关。

### 5.2 API

保留：

- `GET /health`
- `GET /agent-sessions`
- `GET /agent-sessions/{run_id}`
- `POST /agent-sessions/{run_id}/accept`
- `POST /agent-sessions/{run_id}/rollback`
- `DELETE /agent-sessions/{run_id}`

删除所有 stats、event、Short TTP、Long TTP、generation、feedback、queue 和传统 system status 接口。

`create_app()` 只接收 AgentGuard repository provider 和 rollback publisher，不再接收窗口管理器或 TTP 生成器。现有 API Key 校验继续用于受保护接口。

### 5.3 源码边界

保留：

- `ai_agent/agent_guard/`
- 精简后的 `ai_agent/api_server/`
- PostgreSQL 连接、日志和 AgentGuard 实际使用的少量共享代码

物理删除：

- `ai_agent/data_consumer/`
- `ai_agent/ttp_generator/`
- `ai_agent/mitre_attck_agent/`
- `ai_agent/defense/`
- `ai_agent/data/`
- `ai_agent/.cache/mitre_attack/`

优先保持 AgentGuard 内部已有模块边界，避免在功能裁剪时混入无关重构。共享数据库代码先就地精简，只有在导入边界明显改善时才移动文件。

## 6. 数据库设计

### 6.1 保留表

- `agent_sessions`
- `agent_adjudications`
- `agent_rollbacks`

保留已有外键、索引、防重复回退账本和兼容性迁移。

### 6.2 删除表

- `events`
- `short_ttps`
- `long_ttps`
- `short_ttp_events`
- `long_ttp_events`
- `long_ttp_short_ttps`
- `processing_status`
- `system_metrics`
- `long_ttp_generations`
- `langgraph_checkpoints`
- `langgraph_writes`
- `langgraph_blobs`

AgentGuard 使用 LangGraph 构建内存裁决图，但当前不使用数据库 checkpointer，因此三个 `langgraph_*` 表不保留。

### 6.3 物理迁移

从 SQLAlchemy metadata 删除模型不会自动删除旧表，因此提供独立、显式、幂等的 PostgreSQL 清理迁移。迁移必须：

1. 只包含上节列出的精确表名。
2. 按外键依赖顺序删除，必要时使用 `DROP TABLE IF EXISTS ... CASCADE`。
3. 执行前输出目标表并提示备份。
4. 不删除或改写三张 AgentGuard 表。
5. 提供迁移后查询，用于验证业务表只剩 AgentGuard 表。

迁移文件可以提交并测试，但不由自动测试或应用启动隐式执行。对真实数据库执行属于单独、显式的运维步骤。

## 7. Redis 与配置清理

AgentGuard 不使用 Redis。删除：

- Compose 中的 Redis 服务和卷。
- `REDIS_URL` 及基线相关环境变量。
- Python `redis` 依赖。
- `DatabaseManager.redis_client`、`get_redis()`、`RedisKeyBuilder` 和 `CacheTTL`。
- `init_database()` 和 `init_db_manager()` 的 `redis_url` 参数。

配置加载器仅要求 AgentGuard 实际需要的配置，不允许通过无意义的 Elasticsearch 或 Redis 占位值才能启动。

## 8. Web UI 设计

首页直接展示 AgentGuard 会话，不再存在模式切换或网络分析 DOM。

保留：

- 会话列表和分页。
- 会话详情及原始请求。
- 风险等级、裁决摘要、发现列表和建议动作。
- 文件变更预览。
- 接受变更、执行回退和删除告警。
- 加载、空数据、错误、过期请求和重复操作保护。

删除：

- `analysisMode`、模式菜单和本地模式持久化。
- Short/Long TTP 页面、状态和请求。
- 统计卡片、Chart.js、事件类型映射和时间筛选。
- 传统网络接口代理和 WebSocket 统计轮询。

现有模板较大，裁剪以删除无关区域为主；是否拆分模板只由可测试性和可维护性决定，不进行额外 UI 重设计。

## 9. 部署与依赖

唯一 Compose 文件以 `deploy/docker-compose-agentguard.yml` 为基础，只包含：

- Kafka
- PostgreSQL
- MinIO
- MinIO 初始化任务
- ai-agent
- web-ui

删除 baseline、Redis、Elasticsearch、RASP 云服务、探针、示例应用和对应网络/数据卷。ai-agent 只依赖 Kafka、PostgreSQL 和 MinIO 初始化完成。

删除：

- `deploy/docker-compose-app.yml`
- `deploy/docker-compose-agent.yml`
- `deploy/docker-compose-agent-all-in-one.yml`
- `baseline_adjudication/`
- 整个 `third_party/`

保留并更新 `scripts/agentguard-compose`、nono shim、路径策略、冒烟脚本和 AgentGuard 部署说明。

Python 依赖以实际 import 为依据收缩，预期保留 Pydantic、SQLAlchemy、asyncpg、aiokafka、FastAPI、Uvicorn、LangGraph、OpenAI SDK、python-dotenv 和 boto3；删除 Redis、Elasticsearch、MITRE、MCP、搜索、研究和文档处理依赖。

## 10. 测试策略

### 10.1 删除的测试

删除只覆盖基线、探针、传统消费者、TTP、MITRE、MCP 防御和传统事件模型的测试。

### 10.2 保留并调整的测试

- AgentGuard 规则、diff 解析、上下文规划和 LLM 裁决测试。
- Kafka 消费可靠性及优雅关闭测试。
- PostgreSQL repository 和回退幂等性测试。
- nono shim、wrapper、路径策略和端到端回退测试。
- AgentGuard API 和 Web UI 测试。
- Compose 配置与真实冒烟测试。

### 10.3 新增验收测试

- shim 默认直接发布到 `agent.session.finished`。
- 无 baseline 和 Redis 时会话可以完成分析。
- 无效会话事件在消费边界被拒绝。
- SQLAlchemy metadata 只注册三张 AgentGuard 业务表。
- OpenAPI 中不存在网络分析接口。
- UI 中不存在模式切换、TTP、网络事件和统计代码。
- Compose 中不存在 baseline、Redis、Elasticsearch 或探针服务。
- 依赖清单中不存在被删除子系统的包。

## 11. 文档与命名

根 README、ai-agent README、web-ui README 和冒烟文档改为 AgentGuard 单模式说明。删除网络遥测、基线、TTP、MITRE、app 侧部署和双模式描述。

代码和 UI 中使用 `AgentGuard` / “智能体安全分析”。仓库名和顶层产品名暂不强制改名，避免把品牌决策混入功能裁剪。

## 12. 实施顺序与提交边界

1. 让 shim 直接发布 AgentGuard 专用 Topic，并把输入校验移到消费边界。
2. 将后端进程和 API 裁剪为 AgentGuard 单模式。
3. 精简数据库模型与连接层，增加显式旧表清理迁移。
4. 将 Web UI 裁剪为智能体安全单模式。
5. 精简 Compose 和依赖，删除 baseline、探针、TTP、MITRE 及第三方目录。
6. 更新测试、文档并执行完整验收。

提交信息使用仓库要求的 `feat`、`fix`、`docs`、`style`、`refactor`、`perf`、`test`、`chore` 或 `revert` 前缀。

## 13. 验收标准

- 仓库不存在网络安全探针、基线、Short/Long TTP 和 MITRE 调查实现。
- 应用启动不要求 Redis 或 Elasticsearch 配置。
- Compose 不启动 baseline 或 Redis。
- nono shim 直接向 `agent.session.finished` 发布。
- API 只包含健康检查和 AgentGuard 会话操作。
- Web UI 打开即进入智能体安全分析且没有模式切换。
- PostgreSQL ORM 只注册 `agent_sessions`、`agent_adjudications`、`agent_rollbacks` 三张业务表。
- 网络分析旧表存在明确、可审计且不自动执行的物理删除迁移。
- 分析、接受、回退和删除流程均有自动化测试覆盖。
- 全部保留测试通过，AgentGuard Compose 配置验证通过。
