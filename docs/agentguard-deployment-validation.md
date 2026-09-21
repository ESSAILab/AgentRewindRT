# AgentRewindRT 部署与测试验证手册

本文用于在新服务器部署并验收 AgentRewindRT 智能体安全运行时。文中所有地址、账号和密钥均为示例，请勿把真实凭据提交到 Git。

## 1. 部署边界

运行时包含以下组件：

| 组件 | 用途 | 是否常驻 |
| --- | --- | --- |
| Kafka | 接收会话完成及回退请求事件 | 是 |
| PostgreSQL | 保存会话、裁决和回退记录 | 是 |
| MinIO | 保存代码 diff | 是 |
| ai-agent | 消费事件、调用 LLM 裁决并提供 API | 是 |
| web-ui | 展示会话并提供接受、回退、删除操作 | 是 |
| minio-init | 首次创建 `agent-diffs` bucket | 否，成功后 `Exited (0)` |

数据库使用 `agent_sessions`、`agent_adjudications`、`agent_rollbacks`。

## 2. 推荐环境与端口

推荐使用 Ubuntu 22.04 或同等级 Linux，并准备：

- Docker 20.10+ 和 Docker Compose v2；
- Git、Python 3.10+；
- 可正常执行的 `nono`；
- 可从部署服务器访问的 OpenAI 兼容 LLM 接口。

默认端口为 Web UI `30003`、后端 API `8000`、MinIO `9000/9001`、Kafka 宿主机入口 `29092`、PostgreSQL 宿主机入口 `15432`。部署前用 `docker ps -a` 和 `ss -lntp` 检查冲突。

如服务器上已有其他服务，先确认端口与容器名称是否冲突；只停止明确冲突且可以停止的服务，不要直接删除已有数据卷。

## 3. 获取代码

```bash
git clone <your-gitlab-repository-url> AgentRewindRT
cd AgentRewindRT
git status
```

后续命令均在项目根目录执行。

## 4. 准备 nono 和宿主机目录

确认真实 nono 可执行文件：

```bash
nono --version
command -v nono
```

若它不在 `/usr/local/bin/nono`，设置：

```bash
export DEEPXDR_REAL_NONO='/absolute/path/to/nono'
```

创建两个不同的绝对目录：

```bash
mkdir -p .tmp/agentguard-workspaces .tmp/agentguard-nono-state
export AGENTGUARD_WORKSPACE_ROOT="$(realpath .tmp/agentguard-workspaces)"
export AGENTGUARD_NONO_STATE_ROOT="$(realpath .tmp/agentguard-nono-state)"
```

这两个目录不能相同，也不能是 `/`。启动脚本会把它们以相同绝对路径挂载进 `ai-agent`，以便容器执行回退时能找到宿主机的 workspace 和 nono 快照。

在 Linux 5.15 上，nono 可能报告 `Landlock V1` 和部分 `degraded` 能力。这不妨碍本项目的快照与回退功能，但表示内核无法提供较新 Landlock ABI 的全部隔离能力；生产环境应结合安全要求评估是否升级内核。

## 5. 配置 LLM

建议把部署变量写入仅服务器可读、且不会提交 Git 的环境文件，至少包含：

```bash
export OPENAI_MODEL='your-endpoint-or-model-id'
export OPENAI_API_KEY='your-api-key'
export OPENAI_BASE_URL='https://your-openai-compatible-endpoint/v1'
export BACKEND_API_KEY='replace-with-a-strong-api-key'
```

`OPENAI_MODEL` 必须使用供应商接口实际接受的模型或 endpoint ID。部署前可直接验证接口：

```bash
curl -sS "$OPENAI_BASE_URL/chat/completions" \
  -H "Authorization: Bearer $OPENAI_API_KEY" \
  -H 'Content-Type: application/json' \
  -d "{\"model\":\"$OPENAI_MODEL\",\"messages\":[{\"role\":\"user\",\"content\":\"reply OK\"}],\"max_tokens\":8}"
```

返回 `404 Not Found` 通常表示 base URL、模型 ID 或 endpoint ID 不正确，或该账号无权访问；这不是 AgentRewindRT diff 流程故障。

## 6. 构建镜像

检查 Compose 配置：

```bash
./scripts/agentguard-compose config --quiet
```

`version is obsolete` 是新版 Compose 对旧格式的提示，不影响启动。

直接构建：

```bash
./scripts/agentguard-compose build ai-agent web-ui
docker images | grep deepxdr-agentguard
```

在需要代理的环境中，可显式传递代理和 Python 镜像源：

```bash
export HTTP_PROXY='http://proxy.example:port'
export HTTPS_PROXY="$HTTP_PROXY"
export NO_PROXY='localhost,127.0.0.1,kafka,postgres,minio,ai-agent,web-ui'
export PIP_INDEX_URL='https://pypi.tuna.tsinghua.edu.cn/simple'

./scripts/agentguard-compose build \
  --build-arg HTTP_PROXY="$HTTP_PROXY" \
  --build-arg HTTPS_PROXY="$HTTPS_PROXY" \
  --build-arg NO_PROXY="$NO_PROXY" \
  --build-arg PIP_INDEX_URL="$PIP_INDEX_URL" \
  ai-agent web-ui
```

若 Alpine 构建 `aiokafka==0.11.0` 时提示找不到 Cython，说明隔离构建环境无法取得构建依赖。优先检查代理和 Python 镜像源是否传入构建阶段，不要在宿主机全局安装 Python 包来绕过镜像问题。

## 7. 启动及基础检查

```bash
./scripts/agentguard-compose up -d
./scripts/agentguard-compose ps
./scripts/agentguard-compose logs --tail=200 ai-agent web-ui
```

预期 Kafka 为 `healthy`，ai-agent 最终为 `healthy`，其余常驻服务为 `Up`，`agentguard-minio-init` 为 `Exited (0)`。Kafka 启动初期短暂出现 Topic 或 GroupCoordinator 未就绪日志通常可自动恢复；应以最终健康状态和持续日志为准。

`LangChainPendingDeprecationWarning` 是依赖库未来默认值变化提示，不影响当前服务运行。

健康及接口检查：

```bash
curl -fsS http://127.0.0.1:8000/health
curl -fsS -H "X-API-Key: $BACKEND_API_KEY" \
  http://127.0.0.1:8000/agent-sessions
curl -fsS -H "X-API-Key: $BACKEND_API_KEY" \
  http://127.0.0.1:30003/api/agent-sessions
```

注意：端口 `8000` 是后端原生路径 `/agent-sessions`；端口 `30003` 由 Web UI 代理为 `/api/agent-sessions`。

浏览器访问：

- `http://<server-ip>:30003`：AgentRewindRT 页面；
- `http://<server-ip>:9001`：MinIO Console。

## 8. 准备宿主机 shim

shim 在宿主机上接收 nono 执行结果、上传 diff 并发布 Kafka 事件。使用虚拟环境，避免影响系统 Python：

```bash
python3 -m venv .venv
.venv/bin/pip install 'boto3>=1.35,<2.0' 'aiokafka==0.11.0'
export PATH="$PWD/.venv/bin:$PATH"

export KAFKA_BOOTSTRAP_SERVERS='localhost:29092'
export DEEPXDR_AGENT_SESSION_TOPIC='agent.session.finished'
export DEEPXDR_NONO_STATE_HOME="$AGENTGUARD_NONO_STATE_ROOT"
export AGENT_GUARD_DIFF_STORAGE='minio'
export AGENT_GUARD_DIFF_BUCKET='agent-diffs'
export AGENT_GUARD_DIFF_ENDPOINT_URL='http://localhost:9000'
export AGENT_GUARD_DIFF_ACCESS_KEY_ID='minioadmin'
export AGENT_GUARD_DIFF_SECRET_ACCESS_KEY='minioadmin'
```

验证依赖：

```bash
PYTHONPATH="$PWD:$PWD/ai_agent" \
  .venv/bin/python -c \
  "import agent_guard.nono_shim, boto3, aiokafka; print('shim OK')"
```

## 9. 端到端 smoke 验证

```bash
export AGENTGUARD_SMOKE_WORKSPACE="$AGENTGUARD_WORKSPACE_ROOT/smoke-workspace"
./scripts/agentguard-smoke-nono.sh small
```

smoke 脚本会删除并重建专用工作区，请勿将该变量指向真实业务项目。

正确的数据流是：nono 修改文件并创建快照；shim 提取 diff、上传 MinIO、发送 `agent.session.finished`；ai-agent 消费事件、调用 LLM 并把结果写入 PostgreSQL；Web UI 展示该 run ID。

执行后检查：

```bash
./scripts/agentguard-compose logs --since=5m ai-agent
./scripts/agentguard-compose exec postgres \
  psql -U security_user -d security_db -c \
  'select run_id,status,created_at from agent_sessions order by created_at desc limit 5;'
```

如果日志中的 LLM 请求为 HTTP 200，页面应显示裁决结果。若为 404，先修正第 5 节配置，然后重建容器配置：

```bash
./scripts/agentguard-compose up -d --force-recreate ai-agent
```

仅执行 `restart` 不会加载新环境变量。已失败的旧会话不会自动重新裁决，应重新运行 smoke 生成新的 run ID。

还可依次执行：

```bash
./scripts/agentguard-smoke-nono.sh medium
./scripts/agentguard-smoke-nono.sh large
```

三种用例分别覆盖 `file_level`、`hunk_summary`、`risk_only` 裁决策略。

## 10. 接受、回退和删除验收

打开 Web UI，确认：

- 页面宽度、Logo 和统计卡片图标显示正常；
- 新会话能看到风险、文件变更及操作按钮；
- 待处理会话显示“接受变更”“执行回退”和删除按钮。

“接受”和“回退”是互斥的终态操作，建议用两个独立 smoke 会话验证：

1. 对第一个会话执行“接受变更”，检查状态更新且 workspace 保留修改；
2. 再生成一个会话并执行“执行回退”，检查状态更新且 workspace 恢复到修改前；
3. 另建测试会话验证删除，不要删除需要留档的验收记录。

出现 `nono: Session not found` 时，核对事件中的 `workspace` 和 `nono.state_home` 是否分别位于两个配置 root 下，并确认容器内外挂载路径完全一致。

## 11. 更新代码或配置

更新后端和前端代码：

```bash
git pull --ff-only
./scripts/agentguard-compose build ai-agent web-ui
./scripts/agentguard-compose up -d --force-recreate ai-agent web-ui
./scripts/agentguard-compose ps
```

只更新 Web UI 时仅构建并重建 `web-ui`。浏览器使用 `Ctrl+F5` 强制刷新，避免旧静态资源缓存。

只改变环境变量时无需重新构建镜像，但必须用 `up -d --force-recreate <service>` 重建相应容器。

## 12. 停止与数据维护

停止并保留数据卷：

```bash
./scripts/agentguard-compose down
```

不要在未备份前增加 `-v`。备份应覆盖 PostgreSQL、MinIO 数据以及宿主机 nono state 目录，任何删除操作都应先确认目标和恢复方式。

## 13. 验收清单

- [ ] 仅 AgentRewindRT 所需容器运行，`minio-init` 正常退出；
- [ ] `/health`、后端原生 API 和 Web UI 代理 API 可访问；
- [ ] shim 导入检查输出 `shim OK`；
- [ ] smoke 产生新 run ID，diff 存入 MinIO，三张业务表有对应记录；
- [ ] LLM 请求返回成功，页面显示实际裁决结果；
- [ ] 接受、回退、删除分别用独立测试会话完成验证；
- [ ] 回退后宿主机文件恢复；
- [ ] 页面布局、Logo、统计图标和三个操作按钮显示正常；
- [ ] 日志中没有持续性的 Kafka、数据库、MinIO 或 LLM 错误；
- [ ] 部署文档和 Git 中不包含真实密码或 API Key。
