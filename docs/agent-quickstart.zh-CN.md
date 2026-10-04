# 面向 agent 的快速接入

[English](agent-quickstart.md) · [完整接入参考](agents.zh-CN.md)

**一次工具调用，返回精简证据包。** AI 提供任务和上下文，Jev Filter 在程序内采集并判断；
主模型负责规划、开放推理和未确定证据。

## 第一步：安装

```sh
npm install -g @apixly/jev-filter
jev-filter doctor
```

在 AI 实际执行工具的环境配置 `TYPESAFE_API_KEY` 或 `TYPESAFE_API_KEY_FILE`，不要把凭据放进提示词。
安装配套 skill：

```sh
mkdir -p ~/.codex/skills
cp -R "$(npm root -g)/@apixly/jev-filter/skills/jev-filter" ~/.codex/skills/
```

Claude Code 使用 `~/.claude/skills/`。已有定制时先检查合并。安装包不会自动改写全局指令。

## 第二步：明确什么时候调用

| 任务 | 使用方式 |
|---|---|
| 精确路径、ID、字段、selector、计算 | 原生工具或确定性程序 |
| 大量记录、标准明确、重复语义判断 | Jev Filter |
| 规划、写作、开放推理 | 主模型 |
| 已有流程内部已经用了 Jev | 直接调用流程，不重复筛选 |

## 第三步：提供精简而充分的上下文

保存为 `analysis.json`：

```json
{
  "mode": "choose",
  "context": {"project": "Beta", "format": "JSON"},
  "required_context": ["project", "format"],
  "required_record_fields": ["source.project", "source.format"]
}
```

运行完整例子：

```sh
jev-filter query --input - --analysis analysis.json \
  --task '选择与上下文中项目和格式匹配的导出' <<'JSON'
[
  {"id":"a","text":"导出记录","project":"Alpha","format":"JSON"},
  {"id":"b","text":"导出记录","project":"Beta","format":"JSON"},
  {"id":"c","text":"导出记录","project":"Beta","format":"CSV"}
]
JSON
```

预期为 `selected_ids=["b"]`、`review_ids=[]`、`complete=true`。接入真实采集器时改用
`exec ... -- YOUR_COMMAND ARGS`，见 [命令配方](recipes.zh-CN.md)。采集应在工具内部完成，
不要先把原文倒进主模型聊天。

## 第四步：使用结果并处理不确定项

- 已完成的类型化判断按原条件使用，不重复让主模型逐条再分类。
- 有 `review_ids` 或 `complete=false` 时，只复核必要原文。
- 退出码 **2** 仍有结构化结果，不要直接丢弃。
- 回读：`jev-filter read ARCHIVE_PATH --id SOURCE_ID`。
- 权限、身份、时效和执行结果继续由原工作流验证。

Jev 不继承聊天历史。提供相关且有来源的事实，各记录自己的历史随记录传入；缺事实保留不确定。
自动合批、最多 30 个并发请求，不用结果缓存。[上下文详细说明](context-contract.zh-CN.md)。

旧命令 `jev-context` 和 Python 的 `jev_context` 导入继续兼容。
新 Python 集成使用 `from jev_filter.batch import run`。

## JavaScript 与 MCP

npm 包同时导出类型化的 Node.js 客户端。在项目中执行
`npm install @apixly/jev-filter`，然后调用同一 CLI 核心：

```js
import { createClient } from '@apixly/jev-filter';

const client = createClient({ timeoutMs: 120_000 });
const { packet, exitCode } = await client.query([
  { id: 'a', text: 'DNS recovered; requests now succeed.' },
  { id: 'b', text: 'DNS lookup still fails before connection.' },
], {
  task: 'Find current unresolved DNS failures',
  analysis: {
    requirements: [
      { id: 'unresolved', statement: 'DNS currently fails and has not recovered.', expected: true },
    ],
  },
});

console.log(packet.selected_ids, packet.review_ids, exitCode);
// 退出码 2 仍返回可用的部分结果/待复核结果包。
```

`query`、`codeSearch`、`triage` 与 `diffReview` 支持 `AbortSignal` 和输出预算；客户端
可配置超时。取消时把执行中状态视为未确定，不当作重新运行采集器的许可。
客户端不再实现第二套提供方 transport。

MCP host 可以启动固定工作区的只读服务：

```sh
jev-filter mcp --root /path/to/workspace
```

常见 host 配置：

```json
{
  "mcpServers": {
    "jev-filter": {
      "command": "jev-filter",
      "args": ["mcp", "--root", "/path/to/workspace"]
    }
  }
}
```

通过 host 的密钥机制，在其实际进程环境中配置凭据。服务仅提供 `filter_records`、
`search_code`、`triage_events` 和 `read_evidence`。代码采集限制在工作区内；证据回读
仅接受当前服务会话产生且未发生变化的收据。没有 shell 执行、浏览器操作或任意文件读取工具。
推理仍产生费用，准入的输入仍发送到 TypeSafe。[完整适配层契约](integrations.zh-CN.md) ·
[命令参考](cli.zh-CN.md)。

## 用测量结果改善流程

代码任务需要超出精确关键词命中的候选时，可以启用检索扩展：

```sh
jev-filter code-search 'quota|billing' --root . \
  --query 'deduct balance after a completed request' --expand-callers \
  --max-files 100 --task 'Find implementations that deduct the user balance'

jev-filter diff-review --root . --base main \
  --task 'Find changes that weaken authorization checks'
```

采集器返回审查候选和范围收据。扩大候选池可能提高召回，也会增加无关结果与返回上下文。
差异的语义判断用于定位值得检查的变更，编译、测试和代码审查仍由对应工具与人员完成。

已保存的标注判断可以离线评测，不调用模型：

```sh
# 在仓库源码目录运行；实际评估请替换为自己的数据集。
jev-filter eval --input examples/evaluation.json --threshold 0.5 --threshold 0.8
```

按[评测指南](integrations.zh-CN.md#离线评测保存的判断)准备输入。校准与测试数据按组分开，检查失败和复核覆盖，测量
完整流程后再改变路由。报告诊断概率，不拟合概率校准模型，也不向生产判断应用校准概率。
