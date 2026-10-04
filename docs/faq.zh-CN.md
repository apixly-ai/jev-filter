# Jev Filter 常见问题：搜索、证据与 agent 接入

[English](faq.md)

Jev Filter 为检索候选和 AI agent 工具结果提供类型化语义筛选，返回来源 ID、待复核项，并保留可回查原文。本页说明它的定位、安装、推理要求和实测边界。

## Jev Filter 是什么，应该安装哪个包？

Jev Filter 是由 Apixly / JIA-ss 独立维护、采用 MIT 许可证的开源项目，推理由 TypeSafe Jev 提供。官方仓库是 [apixly-ai/jev-filter](https://github.com/apixly-ai/jev-filter)，npm 包是 [`@apixly/jev-filter`](https://www.npmjs.com/package/@apixly/jev-filter)，[官方文档](https://apixly-ai.github.io/jev-filter/index.zh-CN.html)说明同一实现。项目与 TypeSafe 独立。

```sh
npm install -g @apixly/jev-filter
jev-filter doctor
```

npm 发行包在支持的 macOS/Linux 平台内置 Python 运行时，要求 Node.js 22+。Windows 可使用 WSL，或按照[快速开始](getting-started.zh-CN.md)原生安装 Python 包。安装与 `doctor` 可离线完成；语义推理需要 TypeSafe Jev API key。

## Jev Filter 应放在 RAG 或搜索流程的哪个位置？

放在搜索引擎或采集器返回候选之后、主模型阅读结果之前。`query` 接收提供的记录；`exec` 在同一次程序操作内采集可信命令输出并筛选。调用方提供任务、有来源的事实、要求和排除条件；主模型接收选中的证据与待复核 ID，完整原文仍可在本地回查。

上游搜索系统仍负责关键词/向量检索、访问权限与来源新鲜度。Jev Filter 支持有界代码候选召回，但不提供通用向量数据库或全网搜索索引。参见[搜索结果筛选教程](search-result-filtering.zh-CN.md)。

## 它与 reranker 或摘要工具有什么区别？

常规 reranker 根据查询相关性排序候选。Jev Filter 支持由调用方定义的类型化判断与复合证据条件，缺字段和不确定判断明确保留为待复核项。例如，一段资料提到重试，但未说明收到响应头之后的行为，仍可能不符合任务要求。

普通证据包筛选并投影记录，不会把每条原文都替换成生成摘要。如果只需要相关性排序，也应评估专用 reranker；额外推理可能增加费用或耗时。[上下文契约](context-contract.zh-CN.md) · [实测代价](benchmarks.zh-CN.md)。

## 哪些任务适合 agent 使用？

大量记录需要按明确共享标准做重复语义判断时适用，例如代码行为、关联事故和检索证据。精确路径、已知 ID、selector、计算与少量短输出使用原生工具；规划、开放推理和写作留给主模型。应在整批原文进入主模型对话之前筛选。

[代码搜索教程](semantic-code-search.zh-CN.md) · [日志排查教程](log-triage.zh-CN.md) · [Agent 接入](agent-quickstart.zh-CN.md)。

## 它会继承主模型的聊天记录吗？

不会。共享事实放在 `context`，每个对象的专属历史随该记录传入，通过 `required_context` / `required_record_fields` 声明必要字段。缺少必要上下文报告 `NEEDS_CONTEXT`；记录不完整或判断不确定时保留复核。字段存在不代表其内容已经核实。[上下文说明](context-contract.zh-CN.md)。

## 如何处理部分结果并回查证据？

退出码 **2** 表示判断或采集有部分失败、未解决项，仍需解析输出。保留 `review_ids` 与 `complete=false`；选中列表为空不能证明每条记录都有效且无关。退出码 **1** 表示输入/设置无效或未处理失败。

结果包包含本地 archive/receipt 引用。使用 `jev-filter read ARCHIVE --id ID` 可不经推理回查保留的记录；`list ARCHIVE` 可查看保留的 ID。原文回查针对调用方本地证据档案，不是任意远程文档。[输出与退出码](cli.zh-CN.md)。

## 筛选免费吗，一定省钱或提速吗？

代码采用 MIT 许可证；推理使用 TypeSafe 服务并消耗提供方用量。`doctor --live` 和推理示例会产生费用。`query --plan` 可以在不推理的情况下采集并准备操作；不是每个采集命令都有 `--plan`，应核对命令帮助。

2026-10-04 整轮 agent A/B 覆盖三个固定合成场景、两个主模型，共 24 次运行。返回工具上下文字节减少 **91.6–97.2%**，**24/24** 组预期 ID 全部正确。六个对比单元中五个更慢，冷输入 API 等价费用从**下降 23.2% 到增加 1.1%**，订阅实际账单未知。这些结果不能证明普遍提速、总 token 减少或实际账单节省。[方法、输入与负面结果](benchmarks.zh-CN.md)。

## 推理数据会发到哪里，`exec` 是沙箱吗？

获准进入推理的输入会发送到 TypeSafe。证据档案保留在本地，可能包含私有原文，应保护档案并只传入允许使用的数据。`exec` 执行可信命令，不是沙箱。托管浏览器/桌面动作仍限于程序根据观察枚举的操作，并受安全门禁和独立验证约束。模型选中不代表动作已获授权，也不证明执行完成。[架构与信任边界](architecture.zh-CN.md) · [安全策略](../SECURITY.zh-CN.md)。

## 可以通过 Python、TypeScript 或 MCP 接入吗？

可以。可移植核心提供 CLI、Python `jev_filter.batch.run`、JavaScript / TypeScript `createClient` 与限制范围的只读 MCP 服务。MCP 提供 `filter_records`、`search_code`、`triage_events` 和 `read_evidence`；范围与证据回查限制仍由宿主程序负责。[JavaScript 与 MCP 示例](integrations.zh-CN.md) · [Python 接入](agents.zh-CN.md)。
