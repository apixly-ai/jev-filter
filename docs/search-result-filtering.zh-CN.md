# 将 RAG 搜索结果筛成类型化、可回查的证据

[English](search-result-filtering.md)

Jev Filter 可以放在**检索之后、主模型阅读之前**，筛选已经找到的段落。
程序提供稳定的来源 ID、任务上下文和独立的纳入条件；它返回选中 ID、待复核 ID
与精简证据，同时在本地保留传入原文。它不抓取整个语料库，也不替代检索器。

本教程回答：**哪些检索到的 API 段落，既支持重试 HTTP 429，又说明如何避免重复扣费？**
输入是五条固定的合成段落，不是真实 API 文档。下文预期判定是手工编写的教学标签，
不是本次新测的准确率或性能结果。

## 筛选在 RAG 中放在哪里？

典型流程是：

```text
检索器 → 程序校验 → Jev 类型化判断 → 证据包 → 主模型
                                           ↓
                                      原始来源核验
```

保留现有系统中的关键词、向量或混合检索。Elastic 的
[RAG 概述](https://www.elastic.co/docs/solutions/search/rag)介绍这些检索方式；
[语义重排指南](https://www.elastic.co/docs/solutions/search/ranking/semantic-reranking)
说明如何按与查询的语义相似度重新排序候选结果。

重排适合解决相关性顺序。本例要求同时满足两个条件：段落允许这种重试，**并且**
解释如何避免重复扣费。即使段落高度相关，缺少第二项也仍是不完整证据。
Jev 的原子条件分别返回 SUPPORTED / CONTRADICTED / UNKNOWN，随后由程序规则
保留匹配、排除已知矛盾，并将未解决项留待复核。筛选可以与重排配合使用，
但两者的结果回答不同问题。

## 安装并取得固定输入

npm CLI 要求 macOS 或 Linux 上的 Node.js 22+。Windows 可使用 WSL，或参考
[Python 源码安装](getting-started.zh-CN.md#python-工作流继续使用原接口)。

```sh
npm install -g @apixly/jev-filter
jev-filter doctor
git clone https://github.com/apixly-ai/jev-filter.git
cd jev-filter
```

`doctor` 是离线检查。后面的语义调用需要你自己的 Typesafe API key，并会计费。
按[密钥配置指南](getting-started.zh-CN.md#配置-key)设置，不要把凭据放入样例或提示词。

仓库包含 [retrieved.json](../examples/search-filtering/retrieved.json) 和
[analysis.json](../examples/search-filtering/analysis.json)。每条记录都有 `id`、
`text` 与观察到的来源元数据。样例里的 `synthetic://` 引用只标识本地教学来源，
不是真实网页地址。

## 程序负责采集，Jev 负责判定

真实接入中，程序先取得有界候选集，处理访问权限、精确元数据规则和稳定 ID 去重，
再输出 JSON。当版本或租户 ID 已能决定结果时，直接用代码判断。
每个段落要带足够的相邻内容：裁掉例外条款可能改变答案。

共享契约给出目标、API 版本、排除条件和必需上下文；每条标准化记录还必须有
`source.api_version`、`source.source_uri`、`source.revision`。
输入元数据应放在记录顶层，由 CLI 添加 `source` 包装。两个独立条件是：

1. 段落明确允许针对 API v4 的 HTTP 429 重试。
2. 段落说明这种重试如何避免重复扣费。

先离线检查上下文准入和合批，不调用模型：

```sh
jev-filter query --input examples/search-filtering/retrieved.json \
  --analysis examples/search-filtering/analysis.json \
  --task 'Find API v4 passages permitting HTTP 429 retries with duplicate-charge protection' \
  --plan
```

缺少版本的记录会因上下文缺失而延后。规划不会产生语义判定。
当你决定运行计费推理时，去掉 `--plan`：

```sh
jev-filter query --input examples/search-filtering/retrieved.json \
  --analysis examples/search-filtering/analysis.json \
  --task 'Find API v4 passages permitting HTTP 429 retries with duplicate-charge protection' \
  > search-result.json
```

| 来源 ID | 预期判定 | 原因 |
|---|---|---|
| `v4-429-idempotency` | 匹配 | 两个条件都有明确依据 |
| `v4-timeout` | 排除 | 描述的是其他失败阶段 |
| `v4-429-no-retry` | 排除 | 明确禁止这种重试 |
| `v4-429-incomplete` | 复核 | 避免重复扣费的措施未知 |
| `version-missing` | 复核 | 缺少必需的版本元数据 |

## 消费证据，并核验原始来源

一起解析 `selected_ids`、`review_ids` 与 `complete`。本样例包含预期复核项，
语义运行可能以 **2** 退出，同时返回有用的部分 JSON 结果。
不要因为进程返回非零就丢弃 stdout。退出 0 表示处理完成，不证明陈述为真；
退出 1 表示输入、配置或执行错误。详见 [CLI 契约](cli.zh-CN.md)。

把精简证据包交给主模型。复制结果中的 `archive` 路径，按 ID 读取传入原文：

```sh
jev-filter list ARCHIVE_PATH
jev-filter read ARCHIVE_PATH --id v4-429-idempotency
```

应用在把段落作为政策依据前，仍需独立核验权威来源、版本、权限与新鲜度。
归档只保留采集器当时传入的内容，不能证明来源诚实或仍然有效。
共享上下文不足会返回 `NEEDS_CONTEXT`；单条记录缺事实会保留为复核项。
两者都应留在工作流中。

## 什么时候值得增加这一层？

大量检索段落需要按统一语义条件逐条判断时适合使用；精确字段用原生代码，
少量短段落或开放推理继续交给主模型。修改生产链路前，测量检索召回、筛选质量、
复核与失败率、返回上下文、整段耗时和两个模型的用量。
[公开基准](benchmarks.zh-CN.md)同时保留了返回上下文减少、整段变慢和费用估算升高
的情况；这些是固定合成测试，不是普遍提速或降费承诺。

继续阅读[语义代码搜索](semantic-code-search.zh-CN.md)、
[关联日志筛选](log-triage.zh-CN.md)或[上下文契约](context-contract.zh-CN.md)。
