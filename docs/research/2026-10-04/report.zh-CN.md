# Jev 生态调研与 Jev Filter 改进建议

调研日期：2026 年 10 月 4 日。对照本地 Jev Filter 0.3.0，基线提交 `feb2bc21f34e5a7c918ae6dde8b35780c16e197a`。

建议先修执行循环的错误与未知用量记录，再补统一的不确定性策略、代码检索召回和接入适配。批处理、原文回查、上下文准入、失败保留和程序拥有执行权已经是我们的基础能力；浏览器的 operation 与 target 多头设计也已经吸收了 Jev Ultrafast。新增功能应围绕当前缺口验证收益。

本次检查了 10 个公开仓库的源码快照、TypeSafe 官方文档和近期研究论文。目录与搜索结果仅用于发现项目，结论以源码、许可证和原始研究为依据。所有仓库提交固定在 [sources.json](sources.json)。没有安装这些项目，没有调用付费模型，没有操作真实浏览器或客户数据。

## 已复现的本地行为

使用合成输入直接调用本地实现，结果保存在 [offline-observations.json](offline-observations.json)。这组观察说明程序行为，不构成模型质量、真实事故发生率或性能 A/B。

| 观察 | 结果 | 含义 |
|---|---|---|
| 执行循环收到 `transport_failed_usage_unknown` | 返回 `error=ProviderError`、0 tokens、`usage_complete=true` | 具体原因丢失，未知用量被标为完整，应优先修复 |
| requirements 答案分布为 0.36、0.33、0.31 | `SUPPORTED` 胜出，confidence 0.04，仍归为 `MATCH` | 标签判定与不确定性策略尚未统一 |
| 浏览器目标分布为 0.51、0.49 | target confidence 0.02，仍执行所选导航 | 新鲜度和不可逆检查之外，尚无通用的目标不确定性检查；本例是可逆且验证通过的操作 |
| 实现名为 `consume_quota`，搜索 `billing\|invoice` | 0 条；搜索实际符号则 1 条 | 已文档化的词法检索范围限制；不能据此估算真实语义召回率 |

复现：

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[code,dev]'
.venv/bin/python docs/research/2026-10-04/check_gaps.py
```

源码定位：[Run.ask](../../../src/jev_context/act/kernel.py)、[Run.run](../../../src/jev_context/act/kernel.py)、[analysis.decision](../../../src/jev_context/analysis.py)、[collect_code](../../../src/jev_context/tools.py)。脚本完全离线，模型响应由程序构造。

## 外部项目中值得吸收的部分

下表的接入判断是本次分析建议；它不代表这些项目已集成或已在我们的工作流上验证。

| 项目 | 源码可确认的能力 | 对我们的建议 |
|---|---|---|
| [browser-use/jev-ultrafast](https://github.com/browser-use/jev-ultrafast/tree/1231850a0bf1a0c0341fe408ef1668dbbfdfac46) | 一次请求同时预测操作和各操作的候选目标；程序消费匹配的目标头 | 已吸收主要架构，持续对照观察与等待逻辑；不需要再整体引入一个执行器 |
| [jonathanavis96/jev-kit](https://github.com/jonathanavis96/jev-kit/tree/c1a236b0b717c85ff5cd6e5f12cc1f63663e949b) | 确定性预筛、工具 hooks、shadow 观察模式、完成声明复核、连接常驻 | 吸收按需判断和只记录建议的接入方式；其错误时放行策略不应变成我们的执行授权来源 |
| [keiffff/jev-kit](https://github.com/keiffff/jev-kit/tree/3f84bcfa9887a897e7383a36027d1c4331115edc) | 版本化 decision contract、语义 fingerprint、defer、独立校准与留出集、hook 输入适配 | 值得借鉴最小契约、规则版本检查和显式降级；适配器是否匹配目标代理版本还需逐个核验 |
| [TrustifAI/typed_evals](https://github.com/TrustifAI/typed_evals/tree/ab9fc8a5c3e032ca5732cc0afa318cdd44d331af) | 按证据评测、按 group 切分、isotonic 校准、Brier/ECE 等诊断、模型与指标绑定 | 先作为可选评测依赖或离线校准工具，接入我们已有的标签评测；避免替换现有执行或统计层 |
| [lightsifter/sift-light](https://github.com/lightsifter/sift-light/tree/2f87cb23356ffa4e0af8b58c81d532b52fb4fa0f) | 精确与本地概念检索合并、来源修订检查、有限候选的 Jev 分类、MCP | 借鉴候选召回和证据定位思路，自行实现适合我们的最小方案；当前源码许可证为 AGPL-3.0-only，并有概念缓存，不能直接按旧目录标记或当前无缓存设计整体搬入 |
| [supercorp-ai/supercov](https://github.com/supercorp-ai/supercov/tree/c0ad877c3f92149be4f9ed1d520887e3493fab15) | 版本前后差异、文件级可复核的代码属性和风险问题、程序计算汇总 | 给现有 query/triage 增加 diff collector 和评测规则，帮助主模型定位值得审查的变更 |
| [tamaratran/fast-jev-compaction](https://github.com/tamaratran/fast-jev-compaction/tree/e3f262a7f4d42bd8dd32ced30d26176f7cb545b0) | 独立决定保留调用或结果，固定近期消息与 pinned 条目，原样保留选中内容 | 可借鉴对原文和调用关系的保留；整段会话裁剪的适用面、数据外发和重跑副作用较大，建议先做工具结果筛选 |
| [huzeyfe07/jev-route](https://github.com/huzeyfe07/jev-route/tree/4730aeebe08e87d3a1b2899fd0e95d229b0c4adf) | 封闭的 handler 注册表、fallback、middleware；当前底层走 Chat Completions 并解析生成的 JSON | 借鉴注册表与显式 fallback；生成式 confidence 的来源与我们原生接口不同，不作为底层直接替代 |
| [typesafe-ai/typesafe-sdk-python](https://github.com/typesafe-ai/typesafe-sdk-python/tree/f078f1e208a0d885154dc758344ae4fce77ac168) | 官方同步与异步客户端，可选 HTTP/2 | 做协议兼容对照和异步接入参考；是否替换自有 transport 取决于测量，并需保留当前凭据、重试、固定来源与用量约束 |
| [typesafe-ai/system-one-adapter-python](https://github.com/typesafe-ai/system-one-adapter-python/tree/e1d4cc938204b22fc5a3c3aca7044072fe3f712d) | 用同一种问题接口比较其他 LLM；记录重试总用量与未上报项 | 优先接入 benchmark 可选依赖，让 Jev 与小模型在相同输入上比较；不同提供方的概率语义需分别标注 |

许可证以固定提交的实际 LICENSE 为准。`sift-light` 已从旧仓库名称迁移；其 [package.json](https://github.com/lightsifter/sift-light/blob/2f87cb23356ffa4e0af8b58c81d532b52fb4fa0f/package.json) 和 [LICENSE](https://github.com/lightsifter/sift-light/blob/2f87cb23356ffa4e0af8b58c81d532b52fb4fa0f/LICENSE) 均明确当前许可证。其他九个检查快照的根许可证为 MIT；正式复用仍需保留相应声明和检查引入文件。

## 建议的开发顺序

### P0 错误与未知用量

在 hosted `ask` 和 verifier 失败路径保留经过清洗的 ProviderError.code，并将网络未知用量标为 incomplete；已成功请求的已知用量继续累计，未知部分单独计数。程序不能把未知金额展示为确定的零。先为“首请求失败”和“成功后请求失败”写失败行为测试，再修 runtime，并检查 CLI、archive 和 stats 接收的同一份结果。

这是当前复现确认的实现缺陷，无需依赖外部项目或付费模型证明。错误记录修复后，再评估有界、无副作用的判断请求重试；执行动作仍必须受现有幂等与新鲜度控制。

### P0 按问题定义不确定性策略

给 filter、requirements、choose、hosted operation/target/value 建立一致的可配置策略。保留完整分布，检查必要的问题是否足够确定，并输出具体的复核原因。要求不充分的选择进入 REVIEW、补充观察或主模型接管；不把阈值直接变成对外动作的授权。

TypeSafe 官方文档明确：Choice 的 confidence 是从选项分布计算的统计量，不是该任务实测正确率。相同胜出概率可以有不同的第二名，所以还应评估第一与第二名的差距。阈值需按问题与数据域验证，不能统一承诺“0.8 就可靠”。见 [官方 confidence 说明](https://docs.typesafe.ai/confidence)。

我们的 survey 已有标签准确率、置信分组和建议 floor，下一步应扩展为可独立复用的 eval/calibration 工具，加入训练、校准、测试分离，误报、漏报、复核率及每一类的自动正确率。新增更严格检查可能增加复核、延迟或降低自动完成率，应保留这些负面结果。

### P1 浏览器观察和验证

沿用当前执行器，优先解决已在仓库真实网站审计中暴露的问题：角色缺失或透明输入造成候选遗漏、滚动容器和新标签页、页面变化的 settle 竞争，以及验证器看不到 checked/pressed/selected。观察阶段需要完整性与遗漏原因，验证阶段需要读取控件状态；两个阶段分别测量。

仓库 [既有审计](../../benchmarks.zh-CN.md) 在 48 次运行中记录 16 次到达目标，排除机器人检查、登录墙和提供方故障后是 16/34。这个 2026-09-30 的特定环境结果不是本次新测量，也不是开放网站成功率承诺。它足以说明完善既有执行器比新增移动端更有直接价值。

### P1 代码搜索召回

让 collector 可合并关键词、符号结构、调用关系和可选语义候选，再让 Jev 对有限候选判断。精确命中作为独立证据保留，分类区分“实现”“调用者”“提及”“文档”“测试”“未知”。输出继续带路径、行号、source hash 和原文回查引用。

先做无新模型依赖的 BM25、符号与调用线索基线，再评估本地 embedding 是否值得其下载、启动和内存成本。`sift-light` 的本地模型方案不是免费无成本的替代。任何缓存方案不属于当前建议，须另行设计；语义筛选仍无结果缓存。

### P1 接入适配与版本契约

核心保持 Python 实现。可以加薄的 TypeScript 调用层和可选 MCP，复用现有规范化、分析、收据与退出状态，不再实现第二套 Jev transport。

建议首批 MCP 仅提供 `filter_records`、`search_code`、`triage_events` 和受范围限制的 `read_evidence`。适配层应正确处理 exit 2 的部分结果、取消、输出预算、允许的路径和来源。程序枚举并拥有收集器与执行能力，模型不能经适配层新增任意 shell 命令、selector 或坐标。

再为分析规则增加稳定的 contract ID、版本、语义 fingerprint 和模型标识。当前 archive 已保存分析规则，新增契约用于发现“同一版本下题意已改变”和校准不再适用，不能让旧收据获得执行权。hook 接入先只记录建议，并限制到确实需要语义判断的调用；不增加全量拦截开销。

### P1 差异审查与多模型评测

添加 program-owned git diff collector，输出完整 before/after、相关测试和明确来源，然后用现有 query/triage 分类“授权检查变弱”“测试约束减少”“迁移”“新增敏感目的地”等有限审查问题。主要结果是需要主模型查证的候选，编译与测试结果仍由确定性工具提供。

将官方 System One Adapter 放在 benchmark extra 内，比较确定性规则、现有 Jev、候选改进和其他小模型。模型切换不默认进入生产自动回退；一旦更换提供方或题意，概率、校准、失败与用量语义都需要重新验证。

### P2 技能选择和分层候选

官方已有 [skill suggestion](https://docs.typesafe.ai/cookbooks/skill_suggestion) 和 [hierarchical classification](https://docs.typesafe.ai/cookbooks/hierarchical_classification) 示例。我们 choose 超过 253 个实际候选会返回 NEEDS_NARROWING；可以在程序先限定范围后做两阶段 shortlist 与复核，并保留是否完整、哪些候选尚未判断。

适合先在“根据短任务从已安装 skill/tool 清单选择候选”的独立例子中验证。选中结果只表示建议，不能改变权限、自动安装或生成可执行命令。

## 研究中应保留的负面结果

[Typed Evals 的原始报告](https://github.com/TrustifAI/typed_evals/blob/ab9fc8a5c3e032ca5732cc0afa318cdd44d331af/docs/BENCHMARK.md) 记录：645 个测试答案的 ECE 从 0.0982 降到 0.0313，但用验证集选择阈值后 F1 只从 0.5833 到 0.5877，准确率约 72%。默认 0.5 阈值下校准后的 F1 反而更低。校准的收益是改善概率解释，不能声称质量普遍提升。

[Jev-Mobile](https://arxiv.org/html/2609.30186v1) 展示了主模型定局部目标、Jev 根据当前 accessibility tree 执行多步的可行性。论文报告成功率 79%，逐步 VLM 为 84%；时间和费用优势按成功轨迹统计。这是移动任务证据，迁移到网页与我们的费用口径仍需测量。

[JevSpawn](https://arxiv.org/html/2610.00437v1) 可借鉴组合动作、反馈和保留替代分支，但主要实现涉及自托管 Qwen 与四张 H100。论文中的 TypeSafe Jev 变体在八个任务上比 Qwen scoring 慢约 1.4–2.1 倍。模型生成动作字段、推测执行和共享计算的设计不能直接搬入我们的观察枚举、固定来源和无结果缓存契约。

因此暂不建议整体接入会话裁剪、全工具权限判断、交易类自动化、移动端或复杂分支规划。这些方向需要单独的目标、验证标准和业务执行器。

## 后续 A/B 的统一验收

| 改动 | 固定输入 | 首要质量指标 | 必须保留的成本和失败 |
|---|---|---|---|
| 不确定性策略 | 近似候选、缺事实、否定证据、多语种、注入内容 | 错误自动选择、遗漏、复核覆盖、正确自动处理率 | 复核与主模型接管开销，不只计算已成功样本 |
| 检索召回 | 手工标注的真实实现位置、同义词、跨文件调用、无关测试 | collector recall@k 与最终筛选 precision/recall 分开 | 索引/模型启动、收集、推断、主模型续答完整耗时 |
| 浏览器 | 同一页面与控件状态，动态刷新、菜单、滚动、新标签页 | 独立观察召回、无错误动作、状态后验验证、完整目标完成 | 超时、登录/机器人墙、提供方故障、未核实终态 |
| 适配层 | 同一 analysis contract 与 CLI/SDK/MCP 入口 | 输出与部分失败一致、范围控制、退出状态一致 | 冷/热启动、通信、取消、额外上下文 |
| 校准与替代模型 | 按来源或会话 group 分离的标注样本 | 留出集 Brier/ECE、误报/漏报、自动覆盖率 | 各模型实际 usage、未知请求、全操作耗时、明确费率与日期 |

每项保存 baseline、treatment、固定输入、期望结果、逐例失败和源码版本。费用分别列 Jev、小模型、主模型及未知部分；估算 token 输入价值不作为已实现账单节省。独立推断并发不超过 30，不使用结果缓存。

本次交付是源码调研与离线复现。生产 runtime 尚未修改，新增方向的质量、速度和费用收益仍待上述 A/B 验证。
