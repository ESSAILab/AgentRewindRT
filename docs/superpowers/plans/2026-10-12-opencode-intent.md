# OpenCode Intent Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans to implement task-by-task.

**Goal:** 每条 OpenCode 变更记录自动关联实际多轮用户请求。
**Architecture:** 运行专属插件记录关联，正式导出提供消息，conversation 贯穿已有事件/存储/分析/UI。
**Tech Stack:** Python、OpenCode JavaScript plugin、pytest、Alpine.js。
**Spec:** docs/superpowers/specs/2026-10-12-opencode-intent-design.md

## Global Constraints
在当前服务器编码，不部署远端；保留页面布局和旧事件兼容性；不读取全部历史推测会话；无证据强制 unknown；不使用预置变量覆盖实际输入。

## Review Focus
- 恢复会话和未观测的运行中消息：拒绝假完整。
- env 前缀/XDG 覆盖：导出使用实际 agent 环境。
- 非交互回退查询不能继承终端模式。
- 超长对话/附件：明确不完整状态。
- 模型即使返回 aligned，缺失证据仍强制 unknown。

### Task 1: 会话采集
Files: ai_agent/agent_guard/opencode_session.py, ai_agent/agent_guard/opencode_plugin.mjs, tests/agent_guard/test_opencode_session.py.
Interfaces: prepare_capture(command, env, workspace, run_id) -> Capture | None; Capture.command / finish() / close(); normalize_exports(...) -> conversation.
- [x] 写多轮、恢复、错误关联、容量、插件契约测试并验证失败。
- [x] 实现环境解析、独立文件和钩子、导出校验、运行锁。
- [x] pytest tests/agent_guard/test_opencode_session.py，通过。

### Task 2: 入口与分析
Files: nono_shim.py, event_validation.py, intent_evidence.py, adjudication_graph.py; tests/agent_guard/test_nono_shim.py, test_intent_evidence.py.
Interfaces: intent_input(event) -> str; enforce_intent_evidence(event, adjudication) -> AdjudicationResult.
- [x] 写无证据/全部分析策略/旧记录兼容/交互模式测试并验证失败。
- [x] 接入采集、校验、所有模型输入及最终结果约束。
- [x] 运行上述测试和 tests/agent_guard，修复回归。

### Task 3: 页面与验收文档
Files: web_ui/src/web/templates/dashboard.html, tests/web_ui/, deploy/OPENCODE_INTENT_SMOKE.md.
- [x] 增加页面分轮证据展示及行为测试。
- [x] 提供最终真实环境部署和验收步骤，区分本地模拟与真实测试。
- [x] 运行全套 pytest、JS 语法/行为检查、git diff --check。
- [x] 独立审查变更后修正重要问题，报告验证限制。

## 执行记录
用户已授权开展编码；沿用当前工作目录，不额外要求重复授权，不推送或部署。按本地实现、测试、整体审查连续执行。


## 本地验证结果（2026-10-12）

- Python 3.11 临时环境：`/tmp/agentrewind-intent-py311`，补齐项目锁定的 openai 1.99.2、aiokafka 0.11.0；未修改宿主机全局依赖。
- `python -m pytest -q`：194 passed，3 failed，6 个已有 httpx 弃用警告。
- 三个失败均为 `test_agentguard_docs_define_host_rollback_roots` 的 README.md、README_EN.md、deploy/AGENTGUARD_SMOKE.md 参数项。在 `git archive HEAD` 生成的未修改副本中重跑三项，同样全部失败（文档断言过时/英文 README 已不存在）。本次未修改该组测试，不能将全套标记为全绿。
- 实际 JS 插件钩子 + 模拟 OpenCode/nono 可执行程序的整链测试通过，包含正常退出和退出码 7、两轮请求及旧预设变量隔离。此测试不调用真实智能体或模型。
- Python compileall、node --check、git diff --check 通过；Python wheel 构建成功并包含 agent_guard/opencode_plugin.mjs。
- 独立审查发现的三个重要问题已修复并复核：不支持的命令包装、消息/附件/元数据容量、损坏文本片段静默丢失。
- 代码保留为当前工作区变更，未提交或推送；未部署到 95。
- 真实 OpenCode + nono + Kafka/DB/UI 验收待用户部署后进行，步骤见 deploy/OPENCODE_INTENT_SMOKE.md。

## 实施裁定

- 延续用户授权，在当前目录完成，未额外切换工作树或推送共享分支。
- 原有非 OpenCode 事件保持兼容；可识别但不支持的 OpenCode 包装产生 missing，不能回退旧意图。
- 已有 JSON 列足以承载新结构，不引入数据库迁移。
- 助手/工具输出不视为授权；模型有效要求摘要与来源消息单独展示。
