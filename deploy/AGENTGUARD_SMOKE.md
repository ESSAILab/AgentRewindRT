# AgentRewindRT 智能体接入与冒烟测试指南

本指南介绍真实项目中的智能体任务接入，以及专用测试工作区中的冒烟验证。日常接入直接操作指定项目；冒烟脚本会删除并重建测试目录，两者应使用不同的工作区。

## 前置准备

先完成 [README 的环境配置与服务启动](../README.md#1-环境配置与服务启动)，保留同一终端中的环境变量。以下命令从仓库根目录执行。

- Kafka、PostgreSQL、MinIO、ai-agent 与 web-ui 已启动；`minio-init` 正常完成后退出。
- 宿主机已安装集成入口的 Python 依赖，并将真实 nono 路径配置到 `DEEPXDR_REAL_NONO`。
- 工作区位于 `AGENTGUARD_WORKSPACE_ROOT` 内，快照状态目录位于 `AGENTGUARD_NONO_STATE_ROOT` 内。两个根目录必须不同，且以相同绝对路径挂载到后端。不要将这两个变量设为 `/`。
- 接入真实智能体时，另行安装并配置该智能体的模型、凭据及所需 nono 权限。

`OPENAI_BASE_URL`、`OPENAI_MODEL` 和 `OPENAI_API_KEY` 配置后端的变更分析模型。它们不会自动指定实际执行开发任务的智能体或其模型。

详细环境准备、镜像构建与故障排查见 [部署与测试验证手册](../docs/agentguard-deployment-validation.md)。

## 真实项目中的智能体接入

OpenCode 自由交互及多轮真实意图采集见 [OpenCode 多轮意图验收](OPENCODE_INTENT_SMOKE.md)。OpenCode 自动采集模式读取实际会话，不依赖预置任务变量；下方变量示例仍用于向命令行传入任务。

以下示例以编码智能体修改项目文件为场景。将待修改的项目放入工作区根目录下，例如 `$AGENTGUARD_WORKSPACE_ROOT/my-project`，并将示例命令替换为实际智能体命令。

```bash
export REPO_ROOT="$PWD"
export WORKSPACE="$AGENTGUARD_WORKSPACE_ROOT/my-project"
mkdir -p "$WORKSPACE"
cd "$WORKSPACE"

export DEEPXDR_AGENT_ORIGINAL_REQUEST='为项目添加单元测试'
export DEEPXDR_AGENT_RUN_ID="run-$(date +%Y%m%d%H%M%S)"

"$REPO_ROOT/scripts/nono" run --rollback --no-rollback-prompt \
  --allow "$WORKSPACE" -- your-agent-command

cd "$REPO_ROOT"
```

`your-agent-command` 是待替换的智能体命令。其前方独立的 `--` 是参数分隔符：前面是 nono 的选项，后面是实际执行的智能体程序及其参数。使用哪个智能体由这里的命令决定。具体文件与网络授权应按智能体需求配置。

例如，使用 OpenCode 执行“为项目添加单元测试”任务，可将上面的占位命令替换为 `opencode run "$DEEPXDR_AGENT_ORIGINAL_REQUEST"`。在已完成上述环境配置、安装 OpenCode 并配置其模型与凭据后，执行：

```bash
cd "$WORKSPACE"
export DEEPXDR_AGENT_ORIGINAL_REQUEST='为项目添加单元测试'
export DEEPXDR_AGENT_RUN_ID="run-$(date +%Y%m%d%H%M%S)"

"$REPO_ROOT/scripts/nono" run --rollback --no-rollback-prompt \
  --allow "$WORKSPACE" -- opencode run "$DEEPXDR_AGENT_ORIGINAL_REQUEST"

cd "$REPO_ROOT"
```

这里的 `opencode` 指定智能体程序，`run` 是 OpenCode 执行任务的子命令，后面的字符串是实际传给它的任务。`DEEPXDR_AGENT_ORIGINAL_REQUEST` 在本例中用于向 OpenCode 命令传入任务；新版包装入口的 OpenCode 分析依据来自正式会话，不会使用该变量覆盖实际交互。命令用法见 [OpenCode CLI 文档](https://opencode.ai/docs/cli/#run)。nono 还需授权 OpenCode 访问其配置、运行目录及模型服务；需根据本机安装的 nono 版本和 OpenCode 配置设置相应 profile 与权限。

省略 run ID 时入口会自动生成标识。通过 `scripts/nono run --rollback` 运行的命令进入证据发布流程；非零退出也会尝试采集已产生的变更，若未生成可读取快照则报告发布失败。

## 专用工作区中的冒烟测试

### 选择测试用例

| 用例 | 文件修改方式 | 验证重点 |
| --- | --- | --- |
| `small` | 复制预设 README 文件 | 小规模文本变更链路 |
| `medium` | 复制预设代码与配置文件 | 多文件代码与配置变更链路 |
| `large` | 复制预设的大型文件 | 较大数据文件变更链路 |
| `agent` | OpenCode 接收任务并修改 README | 真实智能体接入流程 |

前三个用例通过 `cp` 模拟变更，不启动真实智能体，但仍会调用后端模型分析变更。当前默认阈值下三者均可能采用 `file_level`；名称不等于策略。若专门验证策略切换，可在独立测试部署中临时将后端四项 token 配置设为 200 / 800 / 300 / 80，重建后端并检查记录的 `context_plan.strategy`，测试后移除覆盖恢复默认值。仅在宿主机 export、却未将变量传入 Compose 服务，不会改变容器内阈值。

### 执行模拟变更用例

**冒烟脚本每次都会删除并重建 `AGENTGUARD_SMOKE_WORKSPACE`，必须使用可丢弃的专用目录，不能指向真实项目。**

```bash
export AGENTGUARD_SMOKE_WORKSPACE="$AGENTGUARD_WORKSPACE_ROOT/smoke-workspace"
unset DEEPXDR_AGENT_RUN_ID DEEPXDR_AGENT_ORIGINAL_REQUEST

./scripts/agentguard-smoke-nono.sh small
./scripts/agentguard-smoke-nono.sh medium
./scripts/agentguard-smoke-nono.sh large
```

清除前一次任务的 run ID 和原始请求，使脚本为每次测试生成对应的会话标识并使用用例任务描述。每次运行都会创建 nono 快照、上传 diff 并发布 `agent.session.finished`；后端完成分析后，Web UI 显示对应会话。

### 执行真实智能体用例

`agent` 用例通过 `/usr/bin/env XDG_STATE_HOME=... opencode run ...` 直接启动真实 OpenCode，自动请求为 README 添加 `Agent Result` 小节。它是单轮自动任务；自由多轮交互见 [OpenCode 多轮意图验收](OPENCODE_INTENT_SMOKE.md)。脚本不再使用 shell 字符串包装 OpenCode，也不再传入旧的 `--auto` 参数。

| 配置变量 | 默认值 |
| --- | --- |
| `AGENTGUARD_SMOKE_MODEL` | `agent-test/deepseek-v4-flash`，格式为 provider/model |
| `AGENTGUARD_SMOKE_BASE_URL` | `https://ark.cn-beijing.volces.com/api/coding/v3` |
| `AGENTGUARD_SMOKE_PROFILE` | `nolabs-ai/opencode` |
| `AGENTGUARD_SMOKE_ALLOW_DOMAIN` | `https://ark.cn-beijing.volces.com/**` |
| `OPENAI_API_KEY` | 必须设置，用于生成配置中的环境变量引用，不写入配置文件 |

脚本会生成专用工作区的 `opencode.json`，保留当前 HOME 和模型访问环境，只将 XDG_STATE_HOME 放入 `.opencode-runtime/state`。更换接口时必须同步设置网络授权。后端 OPENAI_MODEL 不会改变此测试的 OpenCode 模型。

```bash
export AGENTGUARD_SMOKE_WORKSPACE="$AGENTGUARD_WORKSPACE_ROOT/smoke-agent"
unset DEEPXDR_AGENT_RUN_ID DEEPXDR_AGENT_ORIGINAL_REQUEST
./scripts/agentguard-smoke-nono.sh agent
```

**脚本会删除并重建指定测试目录，仅使用专用可丢弃目录。** 每次 agent 运行主动清除遗留的原始任务变量，以正式会话导出为分析依据。检查新记录的 `conversation.source=opencode_export`、`status=complete`、用户请求包含本次任务，且 README diff 出现 `Agent Result`。仅命令退出成功不足以证明完整链路通过。若采集失败，应显示意图证据不足，而不能回退为预置任务并判定一致。

## 验证分析结果与人工处置

```bash
./scripts/agentguard-compose logs --since=5m ai-agent
```

打开 `http://localhost:30003`，根据脚本输出的 run ID 查找会话，检查变更文件、风险和分析结果。使用不同测试会话分别验证接受与回退：接受后文件保留修改，回退完成后工作区文件应恢复至对应快照状态。

HTTP 404 时，先根据日志区分是后端分析模型请求失败，还是 OpenCode 模型请求失败，再检查对应接口地址、模型标识和权限。修改后端模型环境变量后，执行 `./scripts/agentguard-compose up -d --force-recreate ai-agent` 加载新配置，再生成新的测试会话。

出现 `nono: Session not found` 时，核对事件中的 `workspace`、`nono.state_home` 是否位于配置的两个根目录内，并确认容器内外使用相同绝对路径。

测试完成后，可从仓库根目录停止服务并保留数据卷：

```bash
./scripts/agentguard-compose down
```

已验证场景见 [验证记录](OPENCODE_VALIDATION.md)。同一冒烟目录每轮重建；若验证回退，应在下一轮开始前完成，或为每轮指定独立目录。
