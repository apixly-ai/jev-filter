<p align="center">
  <img src="docs/assets/hero.zh-CN.svg" alt="Jev Filter：把关键信号交给 AI。采集一次，结合上下文判断，返回可回查的证据。" width="100%">
</p>

<p align="center">
  <a href="https://github.com/apixly-ai/jev-filter/actions/workflows/ci.yml"><img src="https://github.com/apixly-ai/jev-filter/actions/workflows/ci.yml/badge.svg" alt="CI"></a>
  <a href="https://github.com/apixly-ai/jev-filter/releases"><img src="https://img.shields.io/github/v/release/apixly-ai/jev-filter?color=10b981" alt="最新版本"></a>
  <a href="https://www.npmjs.com/package/@apixly/jev-filter"><img src="https://img.shields.io/npm/v/%40apixly%2Fjev-filter?color=8b5cf6" alt="npm 版本"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-64748b" alt="MIT 许可证"></a>
</p>
<p align="center">
  <a href="README.md">English</a> · <a href="#快速开始">快速开始</a> · <a href="https://apixly-ai.github.io/jev-filter/docs/index.zh-CN.html">中文文档</a> · <a href="docs/agent-quickstart.zh-CN.md">接入 AI</a> · <a href="docs/benchmarks.zh-CN.md">Benchmark</a> · <a href="https://github.com/apixly-ai/jev-filter/releases">版本发布</a>
</p>

**把关键信号交给 AI，把判断证据留给你。** Jev Filter 在整批工具输出进入主模型之前，将它变成精简、类型化的判断结果。命令、代码、日志和网页记录保留在程序内部；主模型只接收相关证据，以及需要它接管的 ID。

48 次整段任务测试中，**返回工具上下文减少 88–97%**。所有原文仍可按 ID 回查。[带日期的证据与代价 →](#实测优势)

## 让主模型的每一分注意力都更有价值

| **聚焦关键内容** | **每个判断都有出处** | **让程序完成并验证目标** |
|---|---|---|
| 按任务与上下文筛选大量记录，主模型把注意力放在选中的证据与困难项。 | 类型化答案、来源 ID、本地原文和收据。缺事实、不确定与部分失败都明确保留。 | 对短浏览器或桌面目标，Jev 在观察到的控件中选择；程序拥有执行权、安全门禁与终态验证。 |

形成清楚的分工：**程序采集与验证，Jev 做重复语义判断，主模型规划、推理与写作。** 自动合批减少重复输入，最多 30 个请求并发，不用结果缓存掩盖新观察。

## 0.4：判断更可靠，接入更完整

- **明确处理模糊情况。** 可按问题配置概率、候选差距与 confidence 复核策略；未知的提供方用量保持不完整。
- **查行为，也查变更。** 可选混合代码检索合并词法候选、符号和一跳调用者线索。`diff-review` 采集有界 Git 差异，带来源收据交给语义判断。
- **同一核心，多种接入。** 类型化 JavaScript 客户端与只读 MCP 服务复用已有 CLI 和证据核心，保留可用的部分结果。
- **先评测，再自动化。** 离线 `eval` 提供错误、复核与概率诊断，并检查按组分离的留出集。评测适配器比较提供方，不新增生产自动回退。

[接入示例 →](docs/agent-quickstart.zh-CN.md#javascript-与-mcp) · [命令参考 →](docs/cli.zh-CN.md)

## 快速开始

**Node.js 22+ · macOS / Linux · npm 发行包内置 Python。** Windows 可用 WSL，或[原生安装 Python 包](docs/getting-started.zh-CN.md#python-工作流继续使用原接口)。安装与 `doctor` 可离线完成；推理需要 TypeSafe Jev API key。

```sh
npm install -g @apixly/jev-filter
jev-filter doctor
```

在任意目录运行：

```sh
export TYPESAFE_API_KEY='your-key'

jev-filter query --input - --mode choose \
  --task '选择当前仍未恢复的 DNS 故障' <<'JSON'
[
  {"id":"a","text":"DNS 已恢复，请求成功。"},
  {"id":"b","text":"DNS 仍失败，无法建立连接。"}
]
JSON
```

预期选中 `b`，以下省略诊断元数据：

```json
{"selected_ids":["b"],"review_ids":[],"complete":true}
```

处理实际批量数据时，在原文进入聊天之前，让 CLI 在**一次调用**内完成采集与筛选：

```sh
jev-filter exec --task '找出尚未恢复的网络故障' \
  --analysis analysis.json -- your-collector --json
```

从[可复制的分析契约](docs/recipes.zh-CN.md)开始。退出码 **2** 仍需解析结果包：`complete=false` 与 `review_ids` 表示需要关注。小例子用于了解接口；精确路径、ID、selector、计算和少量短输出通常使用原生工具。[安装、密钥与结果处理 →](docs/getting-started.zh-CN.md)

## 实测优势

我们公开输入、方法、逐次数据与退步项。每个数字都属于下面标明的实验；是否更快、更省，请对自己的任务测量。

| 实验 | 实测结果 | 测了什么 |
|---|---|---|
| **0.4 判断契约** · 2026-10-04 | 预期行为 **3/13 → 13/13**；错误夹具动作 **3 → 0**。 | 离线构造的概率分布与失败响应，**未调用模型**。复核 **0 → 6**，返回上下文 **4,104 → 7,087 bytes**。[数据](benchmarks/results/2026-10-04-decisions.json) |
| **0.4 浏览器观察** · 2026-10-04 | 本地夹具检查 **3/15 → 15/15**；类型化状态召回 **20% → 100%**。 | 程序拥有动作，**没有 Jev 推理**。整段耗时与计划上下文增加；未测模型驱动的完成率。[数据](benchmarks/results/2026-10-04-browser-observation.json) |
| **0.4 混合代码候选** · 2026-10-04 | 采集召回均值 **27.8% → 66.7%**，精度 **66.7% → 47.2%**。 | 固定合成用例，**没有语义推理**。候选上下文与采集耗时增加；检索须主动启用，无法解决词法完全无交集的情况。[数据](benchmarks/results/2026-10-04-retrieval.json) |
| **主模型整段任务** · 2026-09-23 | **返回工具上下文减少 88–97%**；所有运行选对预期 ID。 | 48 次运行、2 个主模型、4 类合成任务。冷输入 API 等价费用从**下降 20.8% 到上升 0.6%**，耗时有升有降。 |
| **Jev 合批** · 2026-09-22 | **输入 token 减少 56.5%**；合批并发比单条并发**快 32.4%**。 | 96 条合成记录 × 2 个条件，每组 2 轮。测量 Jev 阶段，不是主模型整轮加速。 |
| **浏览器与桌面夹具** · 2026-09-30 | 浏览器：**Camofox 15/15**、**CDP 18/18**；桌面：**12/12**。 | 小规模本地合成夹具，每任务 3 轮，终态由程序校验。 |
| **真实公开网站** · 2026-09-30 | 只读运行中 **16/48** 达成目标；排除人机验证、登录墙与接口故障后为 **16/34**。 | 一个环境中的 24 个目标，自定义控件和验证仍是弱项；不代表开放网络成功率。 |

<details>
<summary><strong>查看整段任务图表与复现数据</strong></summary>

![两个主模型、四类任务中的整段收益与退步项](docs/assets/operations.zh-CN.png)

[方法与完整结果](docs/benchmarks.zh-CN.md) · [逐次 JSON](benchmarks/results/2026-09-23-operations.json) · [CSV](benchmarks/results/2026-09-23-operations.csv) · [Jev 阶段数据](benchmarks/results/2026-09-22-live.json)

</details>

## 看程序如何把目标变成可验证的结果

<p align="center">
  <a href="https://apixly-ai.github.io/jev-filter/docs/assets/showcase/index.html?lang=zh"><img src="docs/assets/showcase/browse.zh-CN.gif" alt="合成商店的真实录制：Jev 选择观察到的控件，程序在下单前暂停，确认后再验证结果" width="100%"></a>
</p>

每一步先观察页面或窗口，让 Jev 在程序枚举的操作与控件里选择，重新核对目标，再执行和验证。模型输出不会变成 selector、坐标、命令或未经检查的文字。不可逆动作会暂停等待确认。

```sh
jev-filter browse --url https://shop.example/ \
  --goal 'Find in-stock red shoes in size 42' \
  --value query='red shoes' --verify-text 'Search results'
```

把示例网址替换成允许测试的页面，并提供有意义的校验条件。`browse`、`desktop` 只有 `status: done` 才成功；`extract`、`survey` 要求 `ok` 且 `complete`。选中动作不等于已经完成目标。

[交互式回放：浏览器、桌面、调研](https://apixly-ai.github.io/jev-filter/docs/assets/showcase/index.html?lang=zh) · [录制方法](docs/showcase.zh-CN.md) · [安全门禁与限制](docs/hosted-execution.zh-CN.md)

## 一套核心，接入现有 AI

**CLI · Python · JavaScript / TypeScript · MCP。** 可以调用 shell、嵌入 `jev_filter.batch.run`、从 `@apixly/jev-filter` 导入 `createClient`，或向 MCP host 提供四个只读工具。每条接入路线复用同一核心，保留证据与部分结果。[JavaScript 与 MCP 示例 →](docs/agent-quickstart.zh-CN.md#javascript-与-mcp)

配套 skill 支持 Codex、Claude Code 或兼容的工具框架：

```sh
# Codex；Claude Code 使用 ~/.claude/skills。
mkdir -p ~/.codex/skills
cp -R "$(npm root -g)/@apixly/jev-filter/skills/jev-filter" ~/.codex/skills/
```

给 agent 一段明确的使用规则：

```text
大量记录需要标准明确的语义判断时使用 jev-filter。
传入任务、范围、排除条件、成功标准和有来源的已知事实。
让采集 → 分析 → 精简输出在一次工具调用内部完成。
复核未确定的 ID；精确查询和少量短结果使用原生工具。
不重复已完成判断，不再次封装已有 Jev 流程。
```

Jev 不会自动继承聊天历史。共享事实放 `context`，历史随各记录传入，并声明必要字段。授权与执行验证继续由现有程序负责。[五分钟接入 →](docs/agent-quickstart.zh-CN.md) · [完整接入指南 →](docs/agents.zh-CN.md)

<details>
<summary><strong>按任务选择入口</strong></summary>

| 任务 | 命令 / API | 指南 |
|---|---|---|
| 采集可信命令的输出 | `exec` | [采集命令](docs/recipes.zh-CN.md) |
| 筛选或分类 JSON 候选 | `query` | [结合上下文选择](docs/recipes.zh-CN.md) |
| 定位代码行为 | `code-search` | [完整代码符号](docs/recipes.zh-CN.md) |
| 检查有界 Git 变更 | `diff-review` | [命令参考](docs/cli.zh-CN.md) |
| 归类关联的 JSON/JSONL 事件 | `triage` | [关联日志](docs/recipes.zh-CN.md) |
| 选择本地 Camofox 页面控件 | `locate` | [网页选择](docs/recipes.zh-CN.md) |
| 完成短网页目标或采集页面记录 | `browse` · `extract` | [浏览器托管执行](docs/hosted-execution.zh-CN.md) |
| 完成 Windows/macOS 应用目标 | `desktop` | [桌面](docs/hosted-execution.zh-CN.md#桌面desktop) |
| 对大量记录分类汇总 | `survey` | [大量记录](docs/hosted-execution.zh-CN.md#大量记录survey) |
| 在 Python 中嵌入类型化推理 | `jev_filter.batch.run` | [Python 接入](docs/agents.zh-CN.md) |
| 离线评测标注判断 | `eval` | [评测示例](docs/integrations.zh-CN.md#离线评测保存的判断) |
| 接入 Node.js 程序或 MCP host | `createClient` · `mcp` | [接入示例](docs/agent-quickstart.zh-CN.md#javascript-与-mcp) |

</details>

## 从输入到发行，每一步都可核对

- **有界推理，无结果缓存。** 自动合批，最多 30 个请求并发；不缓存判断结果。
- **本地证据与数值统计。** 私有原文可按 ID 回查；可选[本地看板](docs/statistics.zh-CN.md)展示用量、未知项和负净值，输入等价值估算不作为账单节省。
- **明确的信任边界。** 推理输入会发送到 TypeSafe；`exec` 执行你的可信命令，不是沙箱。托管执行保留新鲜度、来源和桌面安全门禁。[安全策略](SECURITY.zh-CN.md)
- **可移植、可核验的发行包。** Python 核心、内置运行时的 npm 平台包、校验和与构建来源。[发行与恢复](docs/distribution.zh-CN.md)

旧 `jev-context` 命令与 Python imports 保持兼容。Jev Filter 由 **Apixly / JIA-ss** 独立维护，与 TypeSafe 无隶属关系。

## 参与开发

```sh
git clone https://github.com/apixly-ai/jev-filter.git
cd jev-filter
python -m venv .venv && . .venv/bin/activate
python -m pip install -e '.[code,dev]'
sh scripts/check.sh
npm test
```

[贡献指南](CONTRIBUTING.zh-CN.md) · [开发与发布](docs/development.zh-CN.md) · [更新日志](CHANGELOG.zh-CN.md) · [反馈问题](https://github.com/apixly-ai/jev-filter/issues/new/choose) · [MIT 许可证](LICENSE)
