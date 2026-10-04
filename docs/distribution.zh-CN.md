# npm 与原生发行包

[English](distribution.md) · [中文文档首页](index.zh-CN.md)

主要安装方式是 `npm install -g @apixly/jev-filter`。Python 用户继续使用 wheel 和 library，
两种方式调用相同的语义内核。

## 打包方式

小型 Node 入口通过 `optionalDependencies` 选择平台包。平台包包含可执行文件、私有 Python
运行时与依赖、代码解析器和固定版本 ripgrep。不修改用户 Python 环境，没有 postinstall 脚本。
平台包发布到 npm，tarball 同时保存在 GitHub Releases。

这个模式参考了 [Codex](https://github.com/openai/codex/blob/main/codex-cli/scripts/build_npm_package.py)
与 [esbuild](https://github.com/evanw/esbuild/blob/main/npm/esbuild/package.json) 的平台依赖设计。

入口保留参数边界、输入输出流与退出状态，不把输入拼成 shell 命令。支持 macOS Intel/Apple Silicon
和 Linux x64/ARM64。Linux 的 Python 运行时需要 glibc，暂不支持 Alpine/musl；npm 启动器在 Windows 上使用 WSL；Python 包可在 Windows 原生运行。

## 安装验收

- 安装真实 npm tarball，并禁用生命周期脚本。
- 从 PATH 中移除系统 Python 与 ripgrep。
- 用包内运行时、解析器和 rg 完成 `doctor` 与代码搜索测试。
- 独立运行 Python 3.10–3.14、macOS 的源码测试。
- 对照仓库中固定的上游 SHA-256 校验 ripgrep 下载内容。
- 随平台包附带 Python、启动器和所含依赖的许可证。

原生包改善安装体验，不自动提高语义质量。启动、磁盘占用与下载都有额外成本，不能推导速度收益。

## 发布顺序

1. 版本 PR 通过源码、安全和原生包检查后合并。
2. 在已验证提交创建 `v<version>` 标签；标签不允许改写。
3. GitHub Actions 重建四个平台包、Python 包和 npm 主包，发布校验和与来源证明。
4. `Release` 成功后，自动触发受保护 `main` 上的 `publish-npm.yml`；也可以手动指定已有稳定标签 `vMAJOR.MINOR.PATCH` 续办。
5. 发布器核验五个包的名称/版本、全部 SHA-256，以及绑定发布标签、提交和签名工作流的 GitHub 来源证明。
6. 通过 npm OIDC 先发四个平台包，再发主包。已有版本仅在 Registry 的 SHA-512 与发行包字节一致时跳过；冲突、查询失败或不确定上传立即停止，不盲目重发。
7. 在新目录从 Registry 安装，验证 `doctor` 和看板 HTML 导出。

## 首次 npm 信任配置

GitHub 端使用已有 `npm` 环境（仅受保护分支）、Node 24 和固定 npm 11.20.0；不保存长期 npm 密钥，也不需要启用变量。工作流会自动运行，但 npm 信任尚未建立时无法完成上传。

npm 要求先有包，才能配置该包的 Trusted Publisher。先使用正式发行 tarball 和已认证的维护者会话完成一次首次发布。建立信任时账号必须启用 2FA；带 bypass 2FA 的 granular token 不能代替信任配置等账号治理操作的验证。

**五个包分别**在 npm Settings → Trusted Publisher 配置：

| 字段 | 值 |
|---|---|
| Provider | GitHub Actions |
| Organization/user | `apixly-ai` |
| Repository | `jev-filter` |
| Workflow filename | `publish-npm.yml` |
| Environment | `npm` |
| Allowed action | 允许直接 `npm publish`，不是仅 stage |

五个包为 `@apixly/jev-filter` 及后缀 `-darwin-arm64`、`-darwin-x64`、`-linux-arm64`、`-linux-x64`。npm 11.15+ 的等价命令：

```sh
npm trust github PACKAGE --repo apixly-ai/jev-filter \
  --file publish-npm.yml --environment npm --allow-publish --yes
```

按提示完成账号身份验证。信任建立后，CI 使用临时 OIDC 身份，后续发布无需人工输入 2FA。不要选择仅 stage 权限，否则每版仍需人工批准。

配置完成后，续发当前版本：

```sh
gh workflow run publish-npm.yml --ref main -f tag=v0.4.1
```

GitHub Release 成功不代表 npm 已发布，必须查看单独的 Publish npm 运行及 Registry 安装验收。未建立 npm 信任时发布会失败，并在摘要说明首次设置条件。参考 [npm trust 前提](https://docs.npmjs.com/cli/v11/commands/npm-trust/) 和[可信发布文档](https://docs.npmjs.com/trusted-publishers/)。

每个平台包附带 `BUILDINFO.json`，记录运行时版本与文件哈希；发布前移除安装来源路径并检查包内容。
