# OpenCode 实际交互意图采集

用户已批准方案并要求在 172.18.8.212 编码、本地验证；172.18.8.95 部署及真实交互验收由用户配合完成。本次不部署远端。

## 范围与数据流
一次 nono run --rollback 的 diff 对应一条记录，允许多个实际用户轮次。通过运行专属 OpenCode 本地插件的 chat.message 钩子记录 sessionID/messageID，退出后执行 opencode export 精确导出对应会话。禁止选择最近会话或使用 prompt-history 推断归属。正式导出已经在 1.18.31 验证，插件装载及沙箱兼容性仍需最终真实验收。

将插件经 OPENCODE_CONFIG_CONTENT 的 plugin 列表注入，保留已有配置，不修改用户全局配置。辅助文件位于工作区 .agentrewind-opencode/<随机标识>，显式排除回退及业务 diff。包装入口支持直接 opencode 和 env KEY=VALUE opencode；不支持的包装/远程 attach 必须明确报告缺失，不猜测。保留原始启动命令用于展示。

## 关联与边界
conversation 是版本化对象，source=opencode_export，status 为 complete/partial/missing/ambiguous，包含 run_id、开始/结束毫秒时间、sessions、messages、errors。每条消息包含会话和消息 ID、角色、时间、scope=current/history、正文及附件描述。只把实际 user 文本视为授权；忽略 synthetic/ignored 文本，助手文本仅作为上下文。导出中的当前消息必须与钩子记录相符；运行期间出现未关联 user 消息、重复 ID、目录不符、子会话或导出不全均不得标记 complete。恢复历史会话保留之前消息，但不要求本次重复完成历史变更。同目录受保护 OpenCode 运行用进程锁拒绝重叠，避免 diff 归属混杂；外部未受保护进程的修改无法由本功能证明来源。

## 分析与页面
所有分析路径使用同一意图格式化函数。按顺序理解指代、补充、更正和取消；取消不自动要求撤销此前修改。原始证据与模型摘要分离。原始请求字段只保留兼容摘要，OpenCode 模式忽略遗留预设变量；无证据时为空，不使用启动命令。缺失、不完整或歧义由代码强制 unknown，risk 最低 medium，不能建议自动接受；保留独立文件风险结论。旧事件保留兼容行为，不补历史证据。

复用 conversation JSON，无数据库迁移。前端保持布局，运行证据展示采集来源、状态、会话及分轮请求，分析部分展示意图依据。使用 x-text 转义原始文本。长对话有明确容量限制，超过限制标记不完整而非静默截断；这也控制事件和模型输入体积。

## 验收
本地自动测试：新会话多轮、恢复会话、两次不混淆、多会话、钩子缺失、导出失败、目录不符、未关联消息、合成文本、容量上限、变量覆盖、交互终端、所有分析策略 unknown、页面转义及旧记录兼容。最终远端验证：真实 OpenCode 插件、nono 沙箱权限、Kafka/数据库/UI 全链路。模型对复杂取消语义的正确性需用真实样例验收，单元测试仅保证证据及指令传递。
