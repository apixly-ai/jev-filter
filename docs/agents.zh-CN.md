# 接入 AI 与已有工作流

[English](agents.md) · [中文文档首页](index.zh-CN.md)

Jev Filter 提供 CLI 与 Python library。能执行命令的 AI 即可使用，不要求 MCP 服务或另一个代理。
核心要求是：**采集 → 判断 → 精简结果，在程序内部完成**。

宿主需要相应接口时，可使用[带类型的 JavaScript 客户端或限定范围的只读 MCP](integrations.zh-CN.md)，保留部分结果与证据而不重复推断。`eval` 离线评测保存的概率；问题策略与版本化契约让路由决策可查证。

## 安装 skill

先完成 [npm 安装](getting-started.zh-CN.md)，再选择对应目录：

| AI | skill 目录 | 项目指令文件 |
|---|---|---|
| Codex | `~/.codex/skills/jev-filter/` | `AGENTS.md` |
| Claude Code | `~/.claude/skills/jev-filter/` | `CLAUDE.md` |
| 其他工具 | 其支持的 skill 目录 | 系统或工具指令 |

```sh
# Claude Code 将路径换为 ~/.claude/skills。
mkdir -p ~/.codex/skills
cp -R "$(npm root -g)/@apixly/jev-filter/skills/jev-filter" ~/.codex/skills/
```

已有同名目录时先检查并合并本地定制。源码仓库中的位置是 `skills/jev-filter/`。
按 AI 工具要求重新加载 skill。在实际执行工具的环境运行 `jev-filter doctor`，不只检查交互终端。

## 可直接加入项目指令的规则

```text
大量记录需要标准明确、重复的语义判断时使用 jev-filter。
精确 ID、路径、selector、计算、短结果和延迟敏感任务优先用原生工具。

传入目标、范围、排除条件、成功标准和有来源的已知事实。
共享事实放 context，每条记录自己的历史放在记录里。
声明 required_context 与 required_record_fields；缺事实返回 REVIEW/NEEDS_CONTEXT。

采集、分析和精简输出在一次工具调用内部完成。
不要先把原始输出放入主模型对话，再加一遍筛选。
已有流程内部用了 Jev 时直接调用流程，不重复包装。
只在需要时回读待复核 ID。类型化判断不能代替行动授权。

自动合批，独立请求最多并发 30，不使用结果缓存。
新增语义流程必须配对比较质量、失败、整段耗时、返回上下文和分模型实际用量。
```

## 应该给多少上下文

| 内容 | 例子 | 作用 |
|---|---|---|
| 目标与范围 | 当前结算请求，Beta 项目 | 避免选错对象 |
| 有来源的已知事实 | 部署为 r17，来源是部署清单 | 区分观察与假设 |
| 排除条件 | 忽略随后已成功的历史故障 | 保持用户真正想要的范围 |
| 成功标准 | 唯一、可用、JSON 格式的导出 | 定义何时可以完成选择 |
| 对象自己的历史 | 同一请求的过去与当前尝试 | 避免串用其他对象的上下文 |
| 所需输出 | 选中 ID、复核 ID、类型化答案 | 减少无用生成 |

从 [完整采集配方](recipes.zh-CN.md) 开始，再读 [上下文契约](context-contract.zh-CN.md)。
Jev 不会自动继承主模型聊天，不要整段复制聊天或把猜测伪装成事实。

## 处理返回结果

1. 退出码为 **2** 时仍解析 stdout，部分结果有价值。
2. 使用 `selected_ids`，保留 `review_ids`；`complete=false` 需要继续处理。
3. 用 `jev-filter read ARCHIVE_PATH --id SOURCE_ID` 回读必要原文。
4. 身份、时效、授权、幂等和执行结果验证继续由原程序负责。

等待真实在运行的进程，不要因输出缺失就重新执行采集命令；命令可能已经产生作用。

## Python 程序接入

已有 Python 工作流可继续使用原接口，无需绕到 Node。安装 `.[code]` 或 Release wheel：

```python
from jev_filter.batch import run

result = run([{
    "id": "request-17",
    "request": {
        "model": "jev-1.13.0",
        "state": {"signal": "DNS 仍失败，尚未建立连接。"},
        "questions": {
            "route": {
                "type": "choice",
                "instructions": "只分类已观察到的信号。",
                "criteria": {
                    "NETWORK": "DNS、TCP 或 TLS 建连故障",
                    "OTHER": "其他已确认故障",
                    "REVIEW": "证据不足"
                }
            }
        }
    }
}], workers="auto")

for row in result["results"]:
    if not row["ok"]:
        continue  # 交回原有的失败或复核路径，不丢弃该记录。
    print(row["id"], row["answers"]["route"]["choice"])
```

其他语言把相同 JSON 数组传给 `jev-filter batch --input -` 即可。一次处理整个批次，
不要每条记录启动一次进程。[首个用户验收记录](benchmarks.zh-CN.md)。
