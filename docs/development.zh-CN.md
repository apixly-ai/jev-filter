# 开发、发布与保护规则

[English](development.md) · [中文文档首页](index.zh-CN.md)

```sh
python -m venv .venv
. .venv/bin/activate
pip install -e '.[code,dev]'
./scripts/check.sh
npm test
```

CI 检查 Python 版本矩阵、macOS、格式、至少 80% 行覆盖率、包构建/安装、公开内容检查、离线规划、
文档示例和浏览器行为。真实模型测试必须显式启用，不在外部 PR 中运行。
桌面测试（`-m desktop`）会打开真实窗口并抢占键盘焦点，所以默认跳过，只有设置 `JEV_DESKTOP_TESTS=1`
才运行；CI 的 `desktop-windows` 和 `desktop-macos` 作业会设置它。请在没人使用的机器上运行。

## 发布流程

1. PR 更新 Python/npm 版本和更新记录；语义变更附相应 A/B 证据。
2. 必要检查通过后合并，在已验证提交打 `v<version>` 标签。
3. 发布流水线检查版本，构建 Python 与四个平台 npm 包，运行安装测试，产出校验和、依赖清单和来源证明。
4. 发布到 Registry 后，从实际下载的安装包再次验收。已发布的版本或标签不覆盖，修正使用新版本。

GitHub Releases 提供所有安装包；npm 是 CLI 的主要安装渠道。PyPI 尚未配置。
依赖更新由 Dependabot 提交，通过 CI 后再处理。安全问题走私密报告入口，不承诺企业级 SLA。

## 仓库保护

`main` 必须通过 PR、最新的必要检查并解决讨论后才能合并。管理员同样受保护。
禁止强推和删除，要求线性历史。必要检查包括 `ci`、`audit`、`codeql`、`native`、`docs`。

初始化阶段只有一位维护者，所以审核批准数为 0，不设置无法完成的自我批准要求。
CODEOWNERS 指向 JIA-ss；有第二位维护者后应要求独立审核。自动检查通过不等于独立人工审查。

`v*` 发布标签禁止更新和删除；单独的创建规则仅允许发布负责人建标签。
默认工作流 token 只读，不能批准 PR；发布和 CodeQL 仅申请各自必要权限。
已启用密钥扫描、推送保护、Dependabot 告警/更新和私密漏洞报告。
`npm` 发布环境限制为受保护分支。更多步骤见 [发行包说明](distribution.zh-CN.md)。


## GitHub 各工作流的用途

| 工作流 | 触发与作用 |
|---|---|
| CI | PR、main 更新和版本标签；检查 Python 矩阵、浏览器、包与启动器。功能分支 push 不再与 PR 重复运行。 |
| Native packages | PR 和正式发布构建；验证四个平台，只取消被新提交替代的 PR 构建。 |
| Security | PR、main 与每周检查；运行依赖审计（含 tokenizer 依赖）和 CodeQL。 |
| Documentation | PR 检查文档；main 构建并部署文档站。 |
| Release | 版本标签触发；构建并签署不可变发行资产。 |
| Publish npm | Release 成功后自动运行，也可手动续办；验证资产、OIDC 发布并测试注册表安装。 |

同一 PR/分支的新提交会取消旧的 CI、安全和文档检查。正式 Release 和 npm 发布不会被新运行中途取消。
Dependabot 每周分组提交 Python 和 GitHub Actions 更新。必要合并检查保持 ci、audit、codeql、native、docs。
可以为已审阅的单个 PR 开启自动合并，但仍须满足分支保护和必要检查；合并后自动删除分支。
已关闭或已合并的 PR 保留为历史，不是待处理队列。
