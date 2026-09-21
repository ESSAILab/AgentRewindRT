# AgentRewindRT Web UI

AgentRewindRT 的代码变更审阅界面，用于查看 AI 智能体代码变更风险并执行人工处置。

## 功能

- 智能体会话列表、分页和自动刷新
- 原始请求、风险裁决、文件变更和 diff 预览
- 接受变更、请求 nono 回退、删除告警
- 并发请求防覆盖和重复操作保护

## 配置

| 环境变量 | 说明 | 默认值 |
| --- | --- | --- |
| `API_BASE_URL` | AgentRewindRT 后端地址 | `http://localhost:8000` |
| `BACKEND_API_KEY` | 后端 API Key | 空 |
| `HOST` | 监听地址 | `0.0.0.0` |
| `PORT` | 监听端口 | `30003` |

## 启动

```bash
python run_dashboard.py
```

浏览器访问 `http://localhost:30003`。推荐使用仓库根目录的 AgentRewindRT Compose 完整部署。

## 代理接口

- `GET /api/agent-sessions`
- `GET /api/agent-sessions/{run_id}`
- `POST /api/agent-sessions/{run_id}/accept`
- `POST /api/agent-sessions/{run_id}/rollback`
- `DELETE /api/agent-sessions/{run_id}`
