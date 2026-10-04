# npm and native distribution

[简体中文](distribution.zh-CN.md)

The primary installation is `npm install -g @apixly/jev-filter`. Python users keep
the release wheel/library interface. Both call the same semantic core.

## Design

A small Node launcher chooses a platform package through `optionalDependencies`.
The platform package contains an executable plus its private interpreter/libraries,
code parsers and a pinned ripgrep binary. No user Python environment is modified;
there are no postinstall scripts. This follows the distribution pattern used by
[Codex](https://github.com/openai/codex/blob/main/codex-cli/scripts/build_npm_package.py)
and [esbuild](https://github.com/evanw/esbuild/blob/main/npm/esbuild/package.json),
with platform packages on npm and mirrored tarballs on GitHub Releases.

The launcher preserves argument boundaries, streams and exit status. It does not
pass user input through an implicit shell. Linux bundles require glibc; Alpine/musl
is not currently supported by the bundled Python runtime. macOS Intel/Apple Silicon
and Linux x64/ARM64 are built and smoke-tested separately. Windows uses WSL for the npm launcher; the Python package runs natively on Windows.

## What is verified

- Install actual npm tarballs with lifecycle scripts disabled.
- Remove system Python and ripgrep from PATH.
- Run `doctor` and a real code-search fixture using the bundled runtime/parser/rg.
- Run source tests independently on Python 3.10–3.14 and macOS.
- Verify ripgrep assets against checked-in upstream SHA-256 digests before packaging.
- Ship package licenses, Python license and bundled dependency notices.

Native distribution improves installation, not semantic quality. Startup, disk size
and install downloads are extra costs; no speedup is inferred from bundling.

## Release order

1. Merge the version PR after required source/security/native checks.
2. Create `v<version>` on that reviewed commit. Protected tags cannot be rewritten.
3. GitHub Actions rebuilds all four platform tarballs, wheel/sdist and the main npm
   package, checks them, then publishes checksums and provenance with the release.
4. Successful `Release` runs automatically trigger `publish-npm.yml` on protected
   `main`. Manual dispatch with an existing stable `vMAJOR.MINOR.PATCH` tag supports recovery.
5. The publisher validates exactly five package identities/versions, every SHA-256 and
   every GitHub attestation against the release tag, commit and signing workflow.
6. Publish four native packages before the main package through npm OIDC. Existing
   versions are skipped only when registry SHA-512 integrity matches the release bytes.
   Collisions, lookup failures and uncertain uploads stop; no blind upload retries occur.
7. Install from the registry into a new directory, then verify `doctor` and dashboard export.

## One-time npm trust setup

GitHub is configured to use the existing `npm` environment (protected branches only),
Node 24 and pinned npm 11.20.0. There is no long-lived npm secret or enablement variable.
The workflow runs automatically but publication cannot succeed until npm trusts it.

npm requires each package to already exist before its Trusted Publisher can be configured.
Bootstrap the four platform packages and main package once using the release tarballs and
an authenticated maintainer session. The account must have 2FA enabled to configure trust;
a bypass-2FA granular token does not authorize trust/account-governance changes.

For **each of the five packages**, configure npm Settings → Trusted Publisher:

| Field | Value |
|---|---|
| Provider | GitHub Actions |
| Organization/user | `apixly-ai` |
| Repository | `jev-filter` |
| Workflow filename | `publish-npm.yml` |
| Environment | `npm` |
| Allowed action | Direct publishing (`npm publish`), not stage-only |

The package names are `@apixly/jev-filter` and the four suffixes `-darwin-arm64`,
`-darwin-x64`, `-linux-arm64`, `-linux-x64`. With npm 11.15+ the equivalent command is:

```sh
npm trust github PACKAGE --repo apixly-ai/jev-filter \
  --file publish-npm.yml --environment npm --allow-publish --yes
```

Complete the interactive account verification when requested. Once trust is established,
future CI publication uses short-lived OIDC credentials without a human 2FA prompt.
Do not select stage-only permission if unattended direct publication is intended.

To publish/resume the existing release after setup:

```sh
gh workflow run publish-npm.yml --ref main -f tag=v0.4.1
```

A green GitHub Release is not proof of npm publication; check the separate Publish npm
run and registry installation result. Missing npm trust remains a failed publish with a
setup explanation in the job summary. [npm trust prerequisites](https://docs.npmjs.com/cli/v11/commands/npm-trust/)
· [Trusted publishing](https://docs.npmjs.com/trusted-publishers/).

Each platform package includes `BUILDINFO.json` with runtime versions and file hashes; installer-origin paths are removed and package contents checked before publication.
