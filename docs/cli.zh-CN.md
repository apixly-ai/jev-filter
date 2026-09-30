# CLI 参数参考

[English](cli.md) · [中文文档首页](index.zh-CN.md)

使用 `jev-filter --help` 和 `jev-filter <command> --help` 查看准确参数。

| 命令 | 用途 |
|---|---|
| `query --input FILE --task TEXT` | 判断已有 `{id,text,...}` 记录 |
| `exec --task TEXT -- COMMAND ARGS` | 程序内部执行采集命令，再判断输出 |
| `search PATTERN --root PATH --task TEXT` | rg 搜索候选，保留相邻上下文 |
| `code-search PATTERN --root PATH --task TEXT` | 将命中扩展到完整函数或方法 |
| `locate --session S --tab T --origin URL --task TEXT` | 只读选择 Camofox 控件并检查时效 |
| `triage --input FILE --task TEXT` | 关联 JSON/JSONL 事件后判断 |
| `batch --input FILE` | 自动合并兼容的原生类型化请求 |
| `read ARCHIVE --id ID` / `list ARCHIVE` | 不调用模型，回读保留的原始记录 |
| `doctor [--live]` | 检查安装；可选真实 API 测试 |

## 分析模式

`choose` 在完整候选集中选择，支持 NONE/REVIEW；超过 253 个候选或请求过大时需要缩小范围。
`filter` 保留多个匹配项；`analyze` 返回调用者定义的类型化判断；`passthrough` 不进行推理。
通用入口的 `auto` 只在未传入自定义分析且输入不超过 1,200 字符时跳过推理，不自动猜测任务语义。

`--analysis FILE` 控制上下文、必要字段、问题、原子条件、筛选、排序和输出投影。
通用入口的 `--batch-size auto` 按完整请求大小合批，`--workers auto` 根据独立请求数和机器资源
选择并发数，上限 30。`--budget-chars` 限制展示文本，不截断完整的选中/复核 ID 集合。

通用入口的 `--plan` 会采集一次并规划，但不调用模型；它仍然会执行采集命令。
专用入口有哪些参数以各自 `--help` 为准；专用分析模式通过 `--analysis` 传入。

## 执行与输出

退出码 `0` 表示操作完成（包括通用入口的明确透传）；`2` 表示采集或判断仍有部分/复核项，
仍需解析 stdout；`1` 表示输入、配置或执行错误；`130` 表示中断。专用入口的透传没有完成
语义判断时仍可能返回 `2`。

`exec` 不隐式启动 shell。可信管道可显式使用 `sh -c`；命令执行一次，超时或超出字节上限时
终止其进程组，不自动重试。未知执行状态需要检查，不能盲目再跑。

默认输出保留 `selected_ids`、`review_ids`、`complete`、来源、本地凭据和已知用量。
`ok` 表示执行状态，不证明答案为真。共享上下文缺失时，在采集前返回 `NEEDS_CONTEXT`。
通用入口的 `--diagnostics` 会显示更多元数据，应结合输入敏感程度使用。

`exec --split auto` 接受 JSON 记录数组，否则按段落拆分；其他选项为 `json`、`whole`、
`paragraphs`、`lines`。仅当每行都有充分上下文时使用 `lines`。
`--accept-exit 0 1` 可接受 rg 没找到结果时的预期退出码。

## 专用采集器

代码搜索不执行源代码。支持 Python，以及可选 JS/JSX/TS/TSX/Go 解析器；不支持或解析失败的
文件保留待复核，重叠范围去重，返回前拒绝已变化的文件版本。这是词法候选集，不是完整语义索引。

网页定位使用已有的 `127.0.0.1:9377` Camofox 服务，必须明确 session、tab、origin。
只观察可触达的控件，不读取输入值，移除 URL 凭据、查询与片段；选中后校验节点是否变化。
重复不可区分控件、过期节点、模糊范围均转复核。不会点击、输入或跳转。

日志分流保留同一请求内的事件顺序和重复次数，脱敏常见凭据格式，保留格式错误记录。
复合筛选条件优先使用原子判断。分类不能证明实时恢复或根因。
