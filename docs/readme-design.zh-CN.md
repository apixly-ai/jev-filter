# README 与文档设计

[English](readme-design.md)

首页先给明确结果：**把关键信号交给 AI，把判断证据留给你**。接着展示聚焦上下文、
判断有出处、程序验证执行三个实际优势，再提供安装、带日期的测量与接入路线。
命令目录折叠展示，为产品叙事服务。

## 视觉体系

- 仓库原创、中英双语 SVG hero：深蓝背景、薄荷色信号、紫色判断，以可运行的 DNS 例子展示精简证据包。
- 使用 GitHub 支持的 HTML、相对资源与标准 Markdown，README 不依赖脚本或托管渲染器。
- 响应式文档首页沿用同一视觉体系，提供明确的主操作、按任务组织的入口、窄屏横向导航和键盘焦点样式。
- 数据同时写入正文与表格，链接到原始来源。历史图表保留在折叠区域，不用装饰图虚构性能结果。

Hero 展示接口例子与醒目的证明条：最新返回上下文减少 91.6–97.2% 的数字旁，直接标明
「24 次真实 agent 运行 · 2026-10-04」。旁边以 **1.31 秒**展示 96 条记录的 Jev API
筛选路径，标明三次中位耗时。另保留 24/24 组 ID 正确与 13/13 项付费接入验证。
双语主图展示 Jev API 与已登录 Codex CLI 路径的同结果对照，旁边明确进程开销与小样本
限制；独立的 **2.58 倍合批速度**图比较两个 Jev 并发臂。两者均不表述成原生推理或
整轮 agent 的加速。
中英文的主张、日期、范围与限制必须同步。
首页不承诺所有任务都加速、节省费用、自动判断正确或在开放网络上完成目标。

## 证据与口径

最强实测开场是 2026-10-04 整段任务 benchmark 的返回工具上下文减少 91.6–97.2%。同一张表
保留费用范围、耗时退步与合成数据范围。托管夹具通过率旁同时展示更弱的真实网站审计。
新发行版实验须公开 baseline、treatment、失败、复核率、返回上下文、整段耗时与每个模型的
实际用量；离线重放和真实推理分别标明。

可选混合检索用于扩大候选池，召回、精度与上下文的取舍不能表述成无条件提升。
离线评测诊断概率，并只从提供的校准组选择阈值；它不拟合生产概率校准模型。

## 维护与验证

直接修改 `docs/assets/hero.svg` 和 `hero.zh-CN.svg`。文档样式位于
`docs/assets/docs.css`，由 `scripts/build_docs.py` 复制到构建目录。
安装 `.[docs,browser-test]` 后，用 `python scripts/render_live_assets.py` 复现最新图表与社交预览。
`scripts/render_assets.py` 只重建历史图表，不覆盖维护中的 hero。

```sh
python scripts/build_docs.py
python scripts/check_docs.py
```

发布前渲染桌面与移动页面，检查双语 hero 可读性、表格与代码是否造成整页溢出，
跑通安装和接入示例，并逐项对照指标原始文件。截图保存在未发布的 `local-results/`。

保留以前参考的设计资料：[uv](https://github.com/astral-sh/uv/blob/main/README.md)、
[bat](https://github.com/sharkdp/bat/blob/master/README.md)、
[GitHub README 指南](https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/customizing-your-repository/about-readmes)和
[GitHub 图片与链接语法](https://docs.github.com/en/get-started/writing-on-github/getting-started-with-writing-and-formatting-on-github/basic-writing-and-formatting-syntax)。
未使用第三方图片素材。
