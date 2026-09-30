# 更新记录

[English](CHANGELOG.md)

## 0.3.0 — 2026-09-30

- 托管执行：Jev Filter 不只过滤，也能执行。Jev 在程序枚举的动作里选择，程序执行，执行前重新核对目标，执行后校验结果。
- `browse`：通过标准库实现的 DevTools 客户端（私有无头 Chrome/Edge/Chromium，或 `--cdp-port` 挂接已有浏览器）或本机 Camofox 完成网页目标。每步一次请求同时问操作和各操作的目标（设计来自 browser-use/jev-ultrafast，MIT）。支持具名值 `--value`、可选文字模型 `--text-model`、来源限制、弹窗处理、`--verify-text/--verify-url/--verify-question`、`--dry-run`，以及不可逆动作的暂停与凭绑定页面状态和动作的 `confirm_token` 续跑（`--keep-open`、`--cdp-port`/`--target-id`、`--confirm`）。
- `extract`：把页面结构化成带表头的表格行、文本块和链接，再按 `query` 契约判断。
- `desktop`：在一个 Windows（UI Automation）或 macOS（辅助功能）应用里运行同样的循环，自绘界面用 OCR（Windows.Media.Ocr、Vision）兜底，`--list` 列出窗口。确定性安全门禁会拒绝终端、凭据管理器和系统设置，拒绝已锁定的会话和已提权的目标，并在出现 STOP 文件或鼠标停在左上角时停止。
- `survey`：对 JSONL/CSV/JSON/文本输入做类型化判断，可选先筛选，打包并发推理，由代码汇总（分布、交叉表、代表样本、不确定与失败 ID），运行前预算检查（`--max-usd`、`--max-requests`），`--labels` 校准，可选用固定种子样本提出类别。
- `doctor` 报告托管执行是否就绪；`desktop` 可选依赖安装桌面后端（从 Git 标签安装；没有 PyPI 包）。
- 录制回放：交互式回放页（浏览器、桌面、调研，中英文）、由真实 Jev 在夹具上的真实运行生成的 GIF 和视频，以及 README 中带真实输出的用法示例；可用 `python -m benchmarks.showcase.record` / `render` 复现。
- agent skill：新增 `skills/jev-filter/references/hosted.md`，说明 `browse`、`desktop`、`extract`、`survey` 的输入怎么构造（值文件、survey 规格、标注文件），以及每种输出状态该怎么处理。
- 基准：`python -m benchmarks.hosted --live` 用合成的浏览器、桌面、survey 夹具，结果由程序校验，数据在 `benchmarks/results/2026-09-30-hosted.json`。
- 修复：Camofox 改用 `127.0.0.1` 访问，去掉 Windows 上每次请求约 2 秒的 IPv6 回退（`locate` 教程 5059 ms → 1192 ms）；基准清理标签页时按 Camofox 2.4.8 的要求把 `userId` 放进 DELETE 请求体；Windows 提权检测改用指针宽度的句柄，读不到自身令牌时不再拒绝所有已提权目标；未安装 `winrt` 时 `doctor` 不再报错；`needs_value` 的输出保留全部被跳过的 `fields`；macOS 查找窗口时能看到首次查询之后才启动的应用。
- 范围说明：托管执行适合步骤短、结果可观测的目标；开放网络的长任务应由规划 agent 拆解。macOS 在离线测试中用模拟的无障碍树验证，并在可授权辅助功能的 CI runner 上运行，没有在实体 Mac 上跑过。

## 0.2.4 — 2026-09-24

- `--input -` 与 JSON 输出强制 UTF-8，不再受控制台代码页影响；Windows（GBK）下管道传入记录此前会报 `JSONDecodeError`。

- npm 发布对每个包最多等待约 15 分钟让 registry 完成异步处理（原约 4 分钟，导致 0.2.3 每发一个平台包就中止）；工作流超时相应提高到 90 分钟。

## 0.2.3 — 2026-09-24

- Python 包可在 Windows 原生运行：`pool` 不再强制导入 POSIX 专有的 `resource`；key 文件读取不依赖 `O_NOFOLLOW`/`getuid`（仍拒绝符号链接，Unix 权限位检查仅 POSIX）；`exec` 在没有 `select()`/`killpg` 的平台用读线程接管道、用 `taskkill /T` 结束整棵进程树。
- 看板在 Windows 上不再设置 `SO_REUSEADDR`，避免第二个实例绑到已占用端口而不报 `EADDRINUSE`；端口占用回退与 `PortInUse` 各平台行为一致。
- 所有文本文件（看板模板、定位脚本、`--input` JSON、统计配置与导出）显式按 UTF-8 读写，不再依赖进程区域设置。
- CI 增加 `windows-latest` 测试。
- 文档：Windows 原生安装改为 GitHub Release wheel 或 git 源安装，未发布到 PyPI。

## 0.2.2 — 2026-09-23

- 看板启动后自动用默认浏览器打开带访问令牌的本机链接，无界面环境可用 `--no-open`。
- 浏览器打开失败时继续提供服务和终端链接；浏览器启动与 HTTP 服务分开执行。
- 发布后等待 npm 异步处理及包索引可见，再执行安装验收，不重复上传。

## 0.2.1 — 2026-09-23

- 默认 8765 端口被占用时，看板自动选择空闲本机端口并返回链接。
- 显式指定的端口冲突返回明确 `PortInUse` 提示；`--port 0` 可选择空闲端口，非法端口在启动前拒绝。
- 不同看板实例不共享监听端口，兼容 Python 的端口复用默认值变化。

## 0.2.0 — 2026-09-23

- 新增显式启用的私有 SQLite 统计账本，覆盖 CLI 筛选及内部批处理成本。
- 记录输入 token 减少量、美元输入价值、Jev 成本与当时价格；保留未知和负收益。
- 支持本地字节粗估、可选 tiktoken 文本计数及显式启用的 OpenAI/Anthropic 官方计数接口。
- 新增只读本地看板，支持模型/日期/计数方式筛选、每日与工具汇总、筛选 JSON 和独立 HTML 导出。
- 增加计算、隐私、失败、接口适配、并发写入及桌面/手机界面测试。
- 仅估算一次规范化候选 JSON 与返回包的差值，不宣称整轮 Agent 或订阅账单节省；不改变语义判断、合批、授权和无结果缓存规则。

## 0.1.0

- 发布 Jev Filter 独立 CLI 与 Python library；旧 `jev-context` 命令和 `jev_context` 导入兼容。
- 提供命令采集、JSON 判断、代码搜索、只读网页定位、关联日志分流及类型化批处理。
- 支持自定义上下文、必要字段、原子条件、输出投影；自动合批、并发上限 30、不使用结果缓存。
- 原文与判断凭据本地保留，未知和失败项可复核；固定 API 地址、严格响应校验和受限凭据权限。
- macOS/Linux x64 与 ARM64 的 npm 平台包包含运行时、解析器与固定版本 ripgrep。
- 提供分开的中英文文档和配图、agent 快速接入、可复现测试、原始数据与负面结果。
- 配套受保护分支、不可改写标签、持续集成、安全检查、校验和与来源证明。
