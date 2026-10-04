# 同一决策核心接入你的代理工作流

[English](integrations.md)

原生 CLI、Python API、带类型的 JavaScript 客户端和只读 MCP 共用同一核心，保留选中与待复核 ID、私有证据收据和真实的用量状态。程序负责采集与判断，业务执行器继续负责身份、授权、幂等和结果验证。

## JavaScript 和 TypeScript

```sh
npm install @apixly/jev-filter
```

```js
import { createClient } from '@apixly/jev-filter';

const client = createClient({ timeoutMs: 120_000 });
const abortController = new AbortController();
const records = [
  { id: 'a', text: 'fixture-r17：DNS 已恢复，当前请求成功。' },
  { id: 'b', text: 'fixture-r17：当前请求仍在任何 HTTP 响应之前发生 DNS 解析失败。' },
];
const { packet, exitCode } = await client.query(records, {
  task: '筛出当前请求在收到 HTTP 响应前发生的连接故障。',
  analysis: {
    required_context: ['deployment'],
    context: { deployment: 'fixture-r17' },
    uncertainty: { min_top_probability: 0.7, min_margin: 0.15 },
  },
  signal: abortController.signal,
});
// exit 2 也要解析：packet.review_ids 保留需要继续查证的证据。
```

`codeSearch`、`triage` 和 `diffReview` 对应固定 CLI 入口，没有任意 `exec` 方法。参数以字面 argv 传入，`shell:false`；分析文件临时且私有。输出限制字节数，超时和取消终止子进程，失败不返回原始 stderr。

默认使用已安装的原生发行包。以 Python 为主的应用可用 `createClient({command:['jev-filter']})` 配置可信执行程序。这个程序属于应用配置，不由模型生成。取消时提供方用量可能未知，不能把中断调用记成零费用。

## 只读 MCP

```json
{
  "mcpServers": {
    "jev-filter": {
      "command": "jev-filter",
      "args": ["mcp", "--root", "/path/to/your/workspace"]
    }
  }
}
```

通过宿主环境或凭据文件配置提供 TypeSafe 测试或应用凭据，不能把密钥放入命令参数或提交的 JSON。

| 工具 | 输入与范围 |
|---|---|
| `filter_records` | 提供的记录、任务和可选分析契约 |
| `search_code` | 正则与可选查询/调用者扩展，仅在配置的根目录内 |
| `triage_events` | 提供的事件，由程序关联与脱敏 |
| `read_evidence` | 本次服务会话生成且未变化的归档中的一条有限原文 |

MCP 不暴露 shell、浏览器写操作、任意文件读取或对外发消息工具。符号链接不能越过工作区边界。原文回查验证归档哈希，不复用推断结果。stdio 顺序处理请求，断开或终止进程可结束运行，但不保证中止已发出的网络请求。

适配器实现 2024-11-05 至 2025-11-25 的连接会话协议并协商其中一个版本，不声称支持较新的 2026-07-28 无状态协议。发版 E2E 使用独立的官方 MCP 客户端验证。

## 为决策定义版本

```json
{
  "contract": {"id":"incident.connection", "version":"1"},
  "requirements": [
    {"id":"current", "statement":"当前请求在收到任何 HTTP 响应头之前失败。", "expected":true}
  ],
  "uncertainty": {
    "min_top_probability":0.7,
    "min_margin":0.15,
    "questions":{"current":{"min_confidence":0.4}}
  }
}
```

结果记录与规则/模型绑定的语义 fingerprint；提供预期 fingerprint 可以发现契约不匹配。它支持审计和评测，旧收据不能变成执行授权。confidence 是分布统计量，并非任务实测正确率，阈值须以本领域独立标注验证。

为兼容已有工作流，过滤不确定性策略按需开启。浏览器/桌面托管默认在执行操作、目标和值选择前要求胜出概率至少 0.55、前两名差距至少 0.10。`needs_review` 返回未达标项和供规划代理查证的证据。`--uncertainty FILE` 可配置每个问题，阈值全设零可复现旧行为。

## 离线评测保存的判断

在仓库源码目录中，不调用模型即可跑通公开的合成示例：

```sh
jev-filter eval --input examples/evaluation.json --output local-results/evaluation.json
```

替换成你自己分为校准与留出组的已标注概率。评测器只用校准组选择阈值，再报告留出组准确率/覆盖率、误报漏报、复核失败数、Brier 与可靠性分组。它不调用模型，也不拟合概率校准器；混合模型/契约和跨组泄漏会被拒绝。

可复现命令与限制见[示例数据](../examples/evaluation.json)、[CLI](cli.zh-CN.md)和[发版 benchmark](benchmarks.zh-CN.md)。
示例的概率与标签由人工设定，结果展示接口和复核行为，不代表模型准确率。

## 比较其他模型

在仓库源码目录中运行；以下 benchmark 属于开发工具：

```sh
pip install '.[code,dev,bench-llm]'
python -m benchmarks.providers --provider jev --model jev-1.13.0 --output plan.json
# 明确开启后计费，使用新输出文件和指定测试凭据：
python -m benchmarks.providers --live --provider openai --model YOUR_TEST_MODEL --output llm.json
```

可选 benchmark 使用 TypeSafe 官方 System One Adapter，与 Jev 使用相同合成 state/questions。报告包含重试总用量、失败和未知项，原始提供方 debug 不输出，并区分生成式 LLM 概率与 Jev 原生输出。各提供方需相应 SDK extra 和明确凭据。该比较仅覆盖过滤操作，不含主模型后续推理，也不会自动改成生产回退。
