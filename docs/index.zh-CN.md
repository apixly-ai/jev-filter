<p><img src="assets/hero.zh-CN.svg" alt="Jev Filter：把关键信号交给 AI。采集一次，结合上下文判断，返回可回查的证据。"></p>

# 把关键信号交给 AI。

**把大量工具输出，变成有证据的判断。** Jev Filter 在程序内部采集，根据你提供的任务与上下文进行类型化语义判断，只返回相关记录与待复核 ID。主模型把注意力留给规划、推理与需要它接管的情况。

<p class="home-actions"><a class="primary" href="getting-started.zh-CN.md">快速开始 →</a><a href="agent-quickstart.zh-CN.md">接入你的 AI</a><a href="benchmarks.zh-CN.md">核对实测证据</a></p>

## 三个值得接入的理由

| 聚焦上下文 | 判断有出处 | 执行有验证 |
|---|---|---|
| 2026-09-23 的整段测试中，48 次合成 agent 运行**返回工具上下文减少 88–97%**。 | 来源 ID、本地完整原文与判断收据；未知项和部分失败明确保留。 | 托管浏览器或桌面目标中，Jev 选择观察到的控件，程序拥有执行权和终态校验。 |

同一核心支持 **CLI、Python、JavaScript / TypeScript 与只读 MCP**，并提供可移植的 agent skill。自动合批减少重复输入，并发不超过 30，不缓存推理结果。[性能与费用的得失](benchmarks.zh-CN.md)属于各自日期的实验，不作为你的任务收益保证。

## 0.4：更完整的判断核心

按问题配置不确定性策略，采集代码候选与 Git 差异，先评测已保存判断再改变自动化。
JavaScript 与只读 MCP 适配层把这些能力接入现有 agent，复用同一推理核心。
[接入示例](agent-quickstart.zh-CN.md#javascript-与-mcp)。

当前离线判断 A/B 达成 **13/13 预期行为**，固定基线为 **3/13**；错误夹具动作
**3 → 0**。这测的是构造响应下的程序行为，不是模型准确率。复核与返回诊断上下文增加。
[公开结果](../benchmarks/results/2026-10-04-decisions.json) ·
[全部测量与限制](benchmarks.zh-CN.md)。

## 从实际任务开始

| 你想完成什么 | 下一步 |
|---|---|
| 安装并看到第一个选中结果 | [快速开始](getting-started.zh-CN.md) |
| 让 coding agent 使用 Jev Filter | [五分钟接入](agent-quickstart.zh-CN.md) |
| 采集工具输出、定位代码或排查日志 | [可复制的任务配方](recipes.zh-CN.md) |
| 使用浏览器、桌面或调研托管执行 | [托管执行](hosted-execution.zh-CN.md) · [录制回放](showcase.zh-CN.md) |
| 定义上下文、判断与复核策略 | [上下文契约](context-contract.zh-CN.md) |
| 在现有程序里嵌入推理 | [完整接入指南](agents.zh-CN.md) |
| 接入 JavaScript/MCP 或评测已保存判断 | [适配层与评测](integrations.zh-CN.md) |
| 核对质量、耗时、用量与费用 | [测试报告与原始数据](benchmarks.zh-CN.md) |

## 参考与项目

[CLI 参考](cli.zh-CN.md) · [架构](architecture.zh-CN.md) · [本地用量看板](statistics.zh-CN.md) · [发行包](distribution.zh-CN.md) · [开发与发布](development.zh-CN.md) · [首页设计](readme-design.zh-CN.md)

推理输入会发送到 TypeSafe。`exec` 执行你的可信命令；托管执行只允许程序枚举的动作。身份、授权、新鲜度与结果验证仍由现有流程负责。[信任边界](architecture.zh-CN.md)。

Jev Filter 由 Apixly / JIA-ss 独立维护，采用 MIT 许可证。[GitHub 仓库](https://github.com/apixly-ai/jev-filter) · [English](index.md)
