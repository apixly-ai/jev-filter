# 筛选关联日志，避免把已恢复的历史失败当成新事故

[English](log-triage.md)

Jev Filter 的 `triage` 按关联字段把 JSON 或 JSONL 事件组成请求历史，
保留每组内观察到的事件顺序，再按类型化条件判定。
它返回匹配与复核 ID，并保留采集证据。语义标签不证明实时事故、恢复或根因。

本教程寻找**当前 DNS/TCP/TLS 建连失败，且尚未收到 HTTP 响应头的请求**。
先前超时、当前尝试已经成功的请求必须排除；失败阶段未知的请求留待复核。
输入是五条固定合成事件，组成四段历史。预期判定是手工教学标签，不是本次新测结果。

## 分开采集、判断与验证

```text
有界日志采集 → 请求历史 → Jev 条件 → 精简证据包
                                     ↓
                              实时/原生核验与诊断
```

现有日志查询应负责时间界限、服务/租户范围与关联身份。
已知请求 ID 或状态字段使用精确过滤。
大量历史需要按照相同语义标准，结合消息、阶段和尝试序号进行判断时，才适合 Jev。
少量精确查询通常不需要模型。

## 安装并检查固定历史

npm CLI 要求 macOS 或 Linux 上的 Node.js 22+。Windows 可使用 WSL，或参考
[Python 源码安装](getting-started.zh-CN.md#python-工作流继续使用原接口)。

```sh
npm install -g @apixly/jev-filter
jev-filter doctor
git clone https://github.com/apixly-ai/jev-filter.git
cd jev-filter
```

`doctor` 是离线检查。下面的语义调用需要你自己的 Typesafe API key，并会计费；
按[密钥指南](getting-started.zh-CN.md#配置-key)配置。本教程不需要真实客户日志或凭据。

仓库的 [events.jsonl](../examples/search-filtering/events.jsonl) 包含
`request_id`、`attempt`、`status`、消息，以及已知时的失败阶段和响应头到达状态。
样例将同一请求中最大的尝试序号定义为当前尝试。
输入已经按采集器观察到的顺序排列，`triage` 不重建缺失的时间线。

| 请求 | 传入证据 | 预期判定 |
|---|---|---|
| `current-tls` | 当前 TLS 失败，尚未收到 HTTP 响应头 | 匹配 |
| `recovered` | 先前 TCP 失败；当前尝试 HTTP 200 且响应体有效 | 排除 |
| `current-http` | 当前 HTTP 503，已经收到响应头 | 排除 |
| `unknown-phase` | 失败，但缺少阶段和响应头证据 | 复核 |

采集器生成 `correlated:current-tls` 这样的 ID，将交错出现的同请求事件放在一起，
并保留组内观察顺序。只有连续、完全相同的重复事件会合并，仍保留出现次数。
格式错误的行保留为采集/复核问题，不会被默默丢弃。

## 为 Jev 提供范围与原子条件

[log-analysis.json](../examples/search-filtering/log-analysis.json) 定义当前尝试规则、
必需共享上下文、成功标准与排除条件。每条分组记录必须有 `source.event_count`。
各事件专属事实保留在该组历史里，不应复制到共享上下文中。

契约包含两个正向原子陈述：

1. 当前尝试在 DNS、TCP 或 TLS 建连阶段失败：预期为 **true**。
2. 当前尝试已收到 HTTP 响应头：预期为 **false**。

这样把纳入与排除条件都写清楚。HTTP 503 是请求失败，却不是响应前的建连失败。
旧尝试里的“timeout”不证明当前尝试仍失败。不能仅凭错误标签猜测缺失阶段。

在仓库根目录运行按需计费的语义操作：

```sh
jev-filter triage --input examples/search-filtering/events.jsonl \
  --group-by request_id \
  --analysis examples/search-filtering/log-analysis.json \
  --task 'Find current unresolved DNS/TCP/TLS failures before HTTP response headers' \
  > triage-result.json
```

预期匹配 `correlated:current-tls`，预期复核 `correlated:unknown-phase`，
`correlated:recovered` 与 `correlated:current-http` 应排除。
这些是用来对照实际输出的样例预期，不是语义判定保证。

`triage` 目前没有 `--plan`。
在虚拟环境中安装 `.[code,dev]` 的源码仓库运行
`python examples/search-filtering/verify.py`，可离线验证分组、契约准入与规划，
不调用推理，也不测分类质量。

## 保留可用的部分结果与可回查原文

解析 `selected_ids`、`review_ids`、`complete` 和 `telemetry.usage_complete`。
本样例预期含有未解决历史，所以语义运行可能以 **2** 退出，同时返回有用 JSON。
保留 stdout 和未知项。退出 0 是处理完成，不是验证恢复；退出 1 表示输入、配置
或执行失败。共享上下文不足会返回 `NEEDS_CONTEXT`。
详见 [CLI 契约](cli.zh-CN.md)与[上下文契约](context-contract.zh-CN.md)。

复制结果中的 `archive` 路径，按 ID 回查分组历史：

```sh
jev-filter list ARCHIVE_PATH
jev-filter read ARCHIVE_PATH --id correlated:current-tls
```

日志采集器会在分组证据中打码常见凭据格式；同时也在另一个仅所有者可读的归档中
保留原始输入，并在本地归档/收据元数据中记录引用。
原始副本可能包含原始密钥，打码也不是穷尽的隐私保证。
归档保持本地，仅分享已检查、允许公开的证据。本地存储用于保留证据，不是推理结果缓存。

## 动作前核验当前系统

用原生监控或只读当前状态查询，检查请求身份、尝试和失败是否仍然相关。
按应用真实成功标准确认实时交付或恢复。Jev 的历史分类不会重启服务，也不证明根因。
如果日志窗口缺少最后一次成功尝试，就不能证明事故仍未解决；扩大或修复采集，并保留不确定性。

生产使用前，以固定人工标签样本比较原生基线：误报事故、漏报、复核、采集失败、
返回上下文、整段延迟和分模型实际用量。
[公开基准](benchmarks.zh-CN.md)同时报告上下文减少与更慢、费用估算更高的情况。
未知用量保留为未知，不算零。继续阅读[检索结果筛选](search-result-filtering.zh-CN.md)
或[语义代码搜索](semantic-code-search.zh-CN.md)。
