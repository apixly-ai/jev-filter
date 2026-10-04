# 为 AI 编程 Agent 增加语义代码搜索

[English](semantic-code-search.md)

Jev Filter 的 `code-search` 先用词法查询采集候选，再把命中扩展为完整函数或方法，
最后按类型化语义条件筛选。AI 编程 Agent 收到选中的来源 ID 和有界证据，
原文仍可回查，返回匹配前还会检查来源版本。

本教程寻找**针对临时超时重试、限制尝试次数，并在尝试间等待的函数**。
三个合成 Python 函数包含一个实际重试循环和两个关键词干扰项。
预期标签用于教学核验，不是本次新测结果。搜索不会执行候选代码。

## 为什么搜索完整函数？

`rg` 命中的 `retry` 可能出现在实现、日志消息或注释中。
完整函数能呈现控制流、异常类型、次数上限和实际等待。
采集步骤把这些观察到的代码符号提供给 Jev；Jev 判断该函数是否满足每个声明的条件。

```text
rg 候选 → 完整代码符号 → 类型化条件 → 精简证据 → 原生核验
```

已经知道精确函数、路径或行号时，直接使用 `rg` 或语言服务。
候选较多且行为不同，才适合语义筛选。候选列表里没有的实现，它无法凭空找回。

## 安装并检查候选

npm CLI 要求 macOS 或 Linux 上的 Node.js 22+；Windows 可使用 WSL，或参考
[Python 源码安装](getting-started.zh-CN.md#python-工作流继续使用原接口)。

```sh
npm install -g @apixly/jev-filter
jev-filter doctor
git clone https://github.com/apixly-ai/jev-filter.git
cd jev-filter
rg -n 'retry|backoff|TimeoutError' examples/search-filtering/code.py
```

`doctor` 与 `rg` 不运行模型推理。后面的语义调用需要你自己的 Typesafe API key，
并会计费；按[密钥指南](getting-started.zh-CN.md#配置-key)设置。
原生 npm 包包含运行时与代码解析器。Python/源码安装需要虚拟环境、`code` extra，
并单独安装 ripgrep。

固定的 [code.py](../examples/search-filtering/code.py) 包含：

| 符号 | 可观察行为 | 预期判定 |
|---|---|---|
| `retry_timeouts` | 捕获 `TimeoutError`、再次调用、等待并受次数上限约束 | 匹配 |
| `report_timeout` | 输出提到超时和重试的消息 | 排除 |
| `run_once` | 单次调用后处理超时 | 排除 |

## 将行为写成独立条件

[code-analysis.json](../examples/search-filtering/code-analysis.json) 声明目标、
固定范围与排除条件，要求观察得到的 `symbol`、`path` 和 `source_sha256` 元数据。
三个原子陈述分别判断：函数是否在 `TimeoutError` 后再次调用操作、是否限制
尝试次数，以及是否在失败之间等待。这些是对传入函数的判断，不是对未见生产环境的运行保证。

在仓库根目录运行按需计费的语义调用：

```sh
jev-filter code-search 'retry|backoff|TimeoutError' \
  --root examples/search-filtering/code.py \
  --analysis examples/search-filtering/code-analysis.json \
  --task 'Find functions retrying TimeoutError with bounded attempts and backoff' \
  > code-result.json
```

本固定文件的预期选中来源 ID 是 `code.py:retry_timeouts:4`。
行号属于观察得到的身份，修改文件或更换样例后应使用实际结果中的 ID。
另两个函数预期为已知不匹配。解析器缺失或来源变化应保留为复核项。

与 `query` 不同，`code-search` 目前没有 `--plan`。
如果要离线验证本样例的采集和契约，在安装了 `.[code,dev]` 的源码虚拟环境中运行
`python examples/search-filtering/verify.py`。这个检查不证明语义准确率。

## 有意识地扩大召回

较大仓库可以使用 `--query` 增加有界词法/BM25 召回，并通过
`--expand-callers` 加入 Python 一跳语法调用者线索：

```sh
jev-filter code-search 'retry|backoff|TimeoutError' \
  --root examples/search-filtering/code.py \
  --query 'transient timeout repeated attempts delay' \
  --expand-callers --max-files 2000 \
  --analysis examples/search-filtering/code-analysis.json \
  --task 'Find functions retrying TimeoutError with bounded attempts and backoff'
```

第二条命令同样会计费，仅用于演示参数；小样例没有测量召回增益。
这些控制扩大候选采集范围，仍不是穷尽的语义索引。
忽略规则、文件与候选上限、不支持的语法和缺少词法交集仍可能造成遗漏。
调用者线索不解析动态分派。[公开基准中的代码 A/B](benchmarks.zh-CN.md)
保留了扩大召回后仍漏掉一个故意无词法交集案例的结果。

## 修改代码前进行核验

一起检查 `selected_ids`、`review_ids`、`complete` 与采集问题。
退出 **2** 表示部分或未解决结果，应解析 stdout，不能当成没有命中。
触及候选上限的搜索无法证明实现不存在。共享上下文缺失会返回 `NEEDS_CONTEXT`，
单条记录缺事实应复核。详见 [CLI 行为](cli.zh-CN.md)。

复制结果里的 `archive` 路径，检查传入的完整函数：

```sh
jev-filter list ARCHIVE_PATH
jev-filter read ARCHIVE_PATH --id 'code.py:retry_timeouts:4'
```

随后使用原生源码审查、调用位置检查和相关测试，核实要修改的行为。
版本守卫会拒绝筛选期间发生变化的来源，但不证明代码正确，也不授权修改。
在 Agent 推理中保留来源 ID，方便后续对照文件核验陈述。

用于真实任务前，比较召回、误选、复核、整段耗时、返回上下文和实际模型用量。
[公开基准](benchmarks.zh-CN.md)包括延迟与费用的负面情况；语义筛选不承诺每个
代码任务都更快或更便宜。也可阅读[检索结果筛选](search-result-filtering.zh-CN.md)
与[日志筛选](log-triage.zh-CN.md)，了解同一证据流程如何用于其他输入。
