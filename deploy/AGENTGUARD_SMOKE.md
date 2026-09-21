# AgentRewindRT 智能体接入与冒烟测试指南

本指南介绍真实项目中的智能体任务接入，以及专用测试工作区中的冒烟验证。日常接入直接操作指定项目；冒烟脚本会删除并重建测试目录，两者应使用不同的工作区。

## 前置准备

先完成 [README 的环境配置与服务启动](../README.md#1-环境配置与服务启动)，保留同一终端中的环境变量。以下命令从仓库根目录执行。

- Kafka、PostgreSQL、MinIO、ai-agent 与 web-ui 已启动；`minio-init` 正常完成后退出。
- 宿主机已安装集成入口的 Python 依赖，并将真实 nono 路径配置到 `DEEPXDR_REAL_NONO`。
- 工作区位于 `AGENTGUARD_WORKSPACE_ROOT` 内，快照状态目录位于 `AGENTGUARD_NONO_STATE_ROOT` 内。两个根目录必须不同，且以相同绝对路径挂载到后端。
- 接入真实智能体时，另行安装并配置该智能体的模型、凭据及所需 nono 权限。

`OPENAI_BASE_URL`、`OPENAI_MODEL` 和 `OPENAI_API_KEY` 配置后端的变更分析模型。它们不会自动指定实际执行开发任务的智能体或其模型。

详细环境准备、镜像构建与故障排查见 [部署与测试验证手册](../docs/agentguard-deployment-validation.md)。

## 真实项目中的智能体接入

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

这里的 `opencode` 指定智能体程序，`run` 是 OpenCode 执行任务的子命令，后面的字符串是实际传给它的任务。`DEEPXDR_AGENT_ORIGINAL_REQUEST` 本身只记录任务供后端分析；本例通过命令参数显式将同一任务传给 OpenCode。命令用法见 [OpenCode CLI 文档](https://opencode.ai/docs/cli/#run)。nono 还需授权 OpenCode 访问其配置、运行目录及模型服务；需根据本机安装的 nono 版本和 OpenCode 配置设置相应 profile 与权限。

省略 run ID 时入口会自动生成标识。通过 `scripts/nono run --rollback` 运行且成功退出的命令才会进入该入口的证据发布流程。

## 专用工作区中的冒烟测试

### 选择测试用例

| 用例 | 文件修改方式 | 验证重点 |
| --- | --- | --- |
| `small` | 复制预设 README 文件 | 文件级分析策略 `file_level` |
| `medium` | 复制预设代码与配置文件 | 摘要策略 `hunk_summary` |
| `large` | 复制预设的大型文件 | 风险优先策略 `risk_only` |
| `agent` | OpenCode 接收任务并修改 README | 真实智能体接入流程 |

前三个用例通过 `cp` 模拟变更，不启动真实智能体，但仍会调用后端模型分析变更。策略覆盖依赖当前 Compose 中的上下文阈值配置。

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

`agent` 用例需要安装 OpenCode，并准备与所安装 nono 版本兼容的 OpenCode profile。当前脚本的配置如下：

| 配置项 | 当前脚本使用的值 |
| --- | --- |
| 智能体程序 | `opencode` |
| 模型 | `deepxdr/deepseek-v3-2-251201` |
| 模型接口 | `https://ark.cn-beijing.volces.com/api/v3` |
| 模型凭据 | 从 `OPENAI_API_KEY` 读取 |
| nono profile | `always-further/opencode` |
| 网络授权 | `https://ark.cn-beijing.volces.com/**` |

这些设置来自 [启动脚本](../scripts/agentguard-smoke-nono.sh) 和 [用例生成代码](../scripts/agentguard_smoke_cases.py)，其中模型、接口与 profile 是固定值。运行前应确认其适用于本地环境；若使用其他模型或接口，需同步调整启动命令与生成的 OpenCode 配置，以及对应的网络授权。仅修改 `OPENAI_MODEL` 和 `OPENAI_BASE_URL` 不会改变该用例的 OpenCode 配置。

完成准备后，从仓库根目录执行：

```bash
export AGENTGUARD_SMOKE_WORKSPACE="$AGENTGUARD_WORKSPACE_ROOT/smoke-workspace"
unset DEEPXDR_AGENT_RUN_ID DEEPXDR_AGENT_ORIGINAL_REQUEST
./scripts/agentguard-smoke-nono.sh agent
```

该用例要求 OpenCode 为测试 README 添加 `Agent Result` 小节，并将运行数据放入测试工作区中的 `.opencode-runtime` 目录。

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
