# OpenCode 多轮意图采集：部署与真实验收

## 当前验证边界

已使用 OpenCode 1.18.31 与 nono 0.67.1 完成真实多轮交互、正式会话采集、Kafka/数据库/Web UI 全链路及自动 agent 冒烟验证，详见 [验证记录](OPENCODE_VALIDATION.md)。恢复会话、并发、异常采集等场景的自动测试不等于全部完成真实环境验收；下方矩阵是后续验收清单。

采集入口支持 `scripts/nono run --rollback -- opencode ...` 及 `-- /usr/bin/env KEY=VALUE opencode ...`。一条记录覆盖一次运行内的多个实际用户轮次。`--session` 恢复会话时，之前消息标记“历史上下文”，此次消息标记“本次用户请求”。attach 到外部 OpenCode 服务、不支持的命令包装、附件内容缺失或会话关联异常不会被当成完整意图。

## 部署范围

1. 将代码同步到目标宿主机的仓库目录。先保留目标服务器已有未提交修改及配置，并核对差异；不要直接覆盖 `.env`、智能体配置或模型凭据。
2. 同步整个 `ai_agent/agent_guard/`（必须包含 `opencode_plugin.mjs`）、宿主机 `scripts/nono`，以及前端模板；若使用 Python 安装包则重新安装，插件已声明为包内资源。
3. 宿主机入口、后端、前端需要一起更新。新事件允许缺失意图，因此不能只更新宿主机而继续运行旧版后端。
4. 保留现有环境变量、工作区/快照目录挂载配置，在仓库根目录重建服务：

```bash
./scripts/agentguard-compose up -d --build ai-agent web-ui
```

5. 本次复用已有 `conversation` 和 `raw_result` JSON 字段，无数据库迁移。原有记录继续显示，不能自动补齐历史原始意图。当前入口已补齐 `DEEPXDR_NONO_INTERACTIVE=1` 交互支持；回退元数据查询始终捕获输出，不受交互开关影响。

## 第一轮：多轮交互

保留之前测试已配置的模型、Kafka、diff 存储、真实 nono 路径等环境。建议使用新建的专用测试目录，勿与其他进程同时修改。

```bash
export REPO_ROOT="$PWD"  # 从仓库根目录执行
export WORKSPACE="$AGENTGUARD_WORKSPACE_ROOT/opencode-intent-test"
mkdir -p "$WORKSPACE/.opencode-runtime/state"
export PATH="$REPO_ROOT/.venv/bin:$HOME/.opencode/bin:$PATH"
unset DEEPXDR_AGENT_ORIGINAL_REQUEST
export DEEPXDR_AGENT_RUN_ID="opencode-intent-$(date +%Y%m%d%H%M%S)"
cd "$WORKSPACE"

DEEPXDR_NONO_INTERACTIVE=1 "$REPO_ROOT/scripts/nono" run \
  --profile nolabs-ai/opencode \
  --allow-domain 'https://ark.cn-beijing.volces.com/**' \
  --rollback --no-rollback-prompt \
  --rollback-exclude .opencode-runtime \
  --rollback-exclude opencode --rollback-exclude opentui \
  --allow "$WORKSPACE" -- /usr/bin/env \
  XDG_STATE_HOME="$WORKSPACE/.opencode-runtime/state" \
  opencode --model agent-test/deepseek-v4-flash
TEST_EXIT_CODE=$?
printf '退出码：%s\n运行标识：%s\n' "$TEST_EXIT_CODE" "$DEEPXDR_AGENT_RUN_ID"
```

模型 `agent-test/deepseek-v4-flash` 必须在实际配置中存在；若配置在旧工作区，需要自行复制非敏感配置或改用原来的已配置测试目录。依次实际输入：

1. `创建 intent-check.md，内容为 first line`
2. `在这个文件末尾追加一行 20261012`
3. `把第一行改为 final line，保留日期`

正常退出后，在 Web UI 找对应 run_id。验收：

- 仍为一条变更记录，包含三轮原文，而非只有启动命令或最后一句。
- “原始交互与任务来源”显示 `OpenCode 正式会话 · 采集完整`，三条均为本次用户请求。
- diff 与实际文件一致；模型整理的有效要求为 `final line` 与日期，不应要求保留已更正的 `first line`。
- 模型意图判断、文件风险、人工决定仍分别显示。不要把 `complete`（采集状态）误读为 `aligned`（模型判断）。

## 后续验收矩阵

| 场景 | 操作与预期 |
| --- | --- |
| 两次独立运行 | 换 run_id 启动新会话，只含第二次的请求；不能混入第一次 |
| 恢复会话 | 使用 `opencode --session <ID>`，输入“继续修改这个文件…”；旧消息为历史，新消息为本次，不要求重做旧 diff |
| 取消与更正 | 先提出一个任务，再明确取消/修改，最后执行另一任务；依据整个顺序分析，取消不等于自动回退之前修改 |
| 多个会话 | 在同一次运行切换主会话，记录保留不同 session_id；子代理会话或不明归属不报告完整 |
| 遗留变量 | 故意设置无关的 `DEEPXDR_AGENT_ORIGINAL_REQUEST` 再实际输入任务；判断和页面必须采用实际对话 |
| 无输入就退出 | 显示未采集到意图、unknown，不能把启动命令判为一致 |
| 采集异常 | 模拟导出失败/关联日志缺失，文件风险仍分析，意图 unknown，不能建议直接接受 |
| 并发 | 同一工作目录第二个受保护 OpenCode 运行应在启动前被拒绝；不同目录互不影响 |
| 回退 | 用户在页面请求回退后，业务文件恢复；采集辅助文件不算业务变更 |

## 诊断位置与限制

每次运行在工作区 `.agentrewind-opencode/<随机标识>/` 保存采集插件、`journal.jsonl` 和按会话 ID 命名的导出文件。包装入口自动添加此目录的 rollback-exclude；仓库也忽略该目录。文件可能包含实际对话，不要上传公开仓库。

`journal.jsonl` 应先出现 `ready`，再出现 `message`（session_id/message_id）。没有 ready 时先检查插件装载和沙箱权限；有关联但导出失败则检查相同用户、相同 OpenCode 路径与 XDG 环境。不要用“最近会话”手工补充缺失关联。导出工具错误输出不写入页面，避免把配置或凭据带入事件。

每次最多采集 8 个会话、128 条有文本/附件的消息、64,000 字符正文；事件含元数据还有总容量限制。超限显式标记不完整，意图 unknown。附件仅保留类型和文件名，内容未解析时同样不报告完整。辅助证据不是防篡改审计日志；同目录外部未受保护进程的修改来源不能由本功能证明。
