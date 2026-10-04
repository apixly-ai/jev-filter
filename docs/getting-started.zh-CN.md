# 安装、运行与结果解读

## 推荐：npm CLI

需要 Node.js 22+，支持 macOS / Linux；Windows 可用 WSL，或原生安装 Python 包（见下文「Python 工作流继续使用原接口」一节；未发布到 PyPI）。
平台包包含 Python 运行时和代码解析器，无需自己配置 Python 环境。

```sh
npm install -g @apixly/jev-filter
jev-filter doctor
```

固定版本：`npm install -g @apixly/jev-filter@0.4.0`。
项目内安装：`npm install @apixly/jev-filter`，使用 `npx jev-filter` 运行。
不要使用 `--omit=optional`，对应平台的二进制通过 optional dependencies 安装。
安装不会执行 postinstall 脚本，也不会自动改写 AI 配置。

也可以安装 GitHub Release 中的相同 npm 包：

```sh
npm install -g https://github.com/apixly-ai/jev-filter/releases/download/v0.4.0/apixly-jev-filter-0.4.0.tgz
```

## 配置 key

```sh
export TYPESAFE_API_KEY='your-key'
jev-filter doctor --live
```

单独 `doctor` 不联网推理；`--live` 会执行一次小额真实测试。
避免在历史命令里存放 key 时，可用自己创建的密钥文件：

```sh
export TYPESAFE_API_KEY_FILE="$HOME/.config/jev-filter/api-key"
```

通过密钥管理器或编辑器写入文件，设置为仅自己可读的 0600 权限；不能是符号链接。
不要把 key 放入 Git、聊天或模型指令。为兼容旧安装，未指定变量时仍读取 `~/.config/jev-context/api-key`
（也支持 `XDG_CONFIG_HOME`）；上面的显式变量会改为新目录。

## 在任意目录尝试

```sh
jev-filter query --input - --mode choose \
  --task '选择当前仍未恢复的 DNS 故障' <<'JSON'
[
  {"id":"a","text":"DNS 已恢复，请求成功。"},
  {"id":"b","text":"DNS 仍失败，无法建立连接。"}
]
JSON
```

预期选中 `b`。加 `--plan` 可只做本地规划。小例子用于了解接口，这类短输入通常
不值得额外调用模型。[命令采集、代码搜索、网页与日志配方](recipes.zh-CN.md)。

## 读懂结果

| 字段 | 怎么处理 |
|---|---|
| `selected_ids` | 本次判断符合要求的记录 |
| `review_ids` | 信息不足、失败或不确定，需要复核 |
| `complete` | 为 `false` 时，判断或采集范围仍不完整 |
| `archive` | 本地原文，可按 ID 读取 |
| `receipt` | 本地判断与诊断信息 |
| `telemetry.usage` | 已知输入/输出 token，结合 `usage_complete` 使用 |

```sh
jev-filter list ARCHIVE_PATH
jev-filter read ARCHIVE_PATH --id SOURCE_ID
```

把占位符替换成返回的路径和 ID。原文文件权限为 0600，用于证据保留，不是推理缓存。

退出码 `0` 表示完成或明确透传，`2` 表示部分结果/待复核，仍需解析 stdout；
`1` 表示输入、配置或执行错误，`130` 表示中断。不要因中断就自动重跑采集命令，
它可能已经执行过。[完整参数与契约](cli.zh-CN.md)。

## Python 工作流继续使用原接口

需要 Python 3.10+；源码安装的搜索功能需要另外安装 ripgrep。

```sh
python -m venv .venv
. .venv/bin/activate
python -m pip install 'jev-filter[code] @ git+https://github.com/apixly-ai/jev-filter.git@v0.4.0'
```

也可使用 Release wheel。目前不假设已经发布到 PyPI。[Python 接入示例](agents.zh-CN.md)。

## 常见问题

- 找不到命令：重开终端，检查 npm 全局 bin 是否在 PATH 中。
- 缺平台包：不要省略 optional dependencies，核对系统和架构。
- 没读到 key：检查实际运行 AI 工具的进程环境，而不只是交互终端。
- 没有搜索结果：检查 `doctor`、ignore 规则和关键词；源码安装需要 rg。
- 退出码 2：查看缺失上下文、`review_ids` 和采集边界，不当作空结果成功。
- 简单任务变慢：回到原生工具，不要为精确查询增加语义推理。
