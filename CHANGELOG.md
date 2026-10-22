# Changelog

本项目遵循 [语义化版本](https://semver.org/lang/zh-CN/)。

## [0.1.0] - 2026-10-22

首个可用版本。

### 新增

- 10 条确定性检测规则（`ISG001`–`ISG010`），覆盖远程脚本执行、缺校验、硬编码仓库地址、`releases/latest`、root 执行、缺 errexit、临时目录不清理、curl 缺失败保护、`rm -rf` 未加引号、下载失败无提示。
- 四种输出格式：Markdown、JSON、SARIF 2.1.0、Codex 提示词。
- `--repo owner/name` 一致性检查：发现脚本里硬编码的 owner 与当前仓库不一致。
- `--fail-on high|medium|low|none` 出口码门槛，可直接用作 CI 合并条件。
- 复合型 GitHub Action（`action.yml`），支持 SARIF 上传到 Code Scanning。
- 41 个单元测试，含一个真实部署过的一键安装脚本作为回归样本。
- CI 矩阵：Ubuntu / Windows / macOS × Python 3.8 / 3.12，外加 self-audit 与 shellcheck。

### 已知局限

- 仅静态文本分析，不追踪跨文件数据流。
- 对 `eval "$(...)"` 这类动态拼接会漏报。
