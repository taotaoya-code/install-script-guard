# install-script-guard

> 一键安装脚本的供应链风险审计器。零依赖，单文件，可离线。

[English](README.md) · 中文

[![CI](https://github.com/taotaoya-code/install-script-guard/actions/workflows/ci.yml/badge.svg)](https://github.com/taotaoya-code/install-script-guard/actions/workflows/ci.yml)
![python](https://img.shields.io/badge/python-3.8%2B-blue)
![dependencies](https://img.shields.io/badge/dependencies-none-brightgreen)
![license](https://img.shields.io/badge/license-MIT-blue)

---

## 为什么做这个

`bash <(curl -fsSL ...)` 这类一行安装脚本到处都是。它们的共同问题是：**执行发生在校验之前**。

一个真实的例子（来自我自己维护的仓库，不是编的）：

```bash
RELEASE_REPO="${VPS_RELEASE_REPO:-oldaccount/vps-benchmark-public}"
RELEASE_TAG="${VPS_RELEASE_TAG:-}"
if [[ -n "$RELEASE_TAG" ]]; then
  BASE_URL="https://github.com/${RELEASE_REPO}/releases/download/${RELEASE_TAG}"
else
  BASE_URL="https://github.com/${RELEASE_REPO}/releases/latest/download"
fi
curl -fL "${BASE_URL}/${ASSET_TGZ}" -o "${TMP_DIR}/${ASSET_TGZ}"
```

三处问题，任何一处都能让安装静默失败：

1. **写死了旧账号名** —— 账号改名后全靠 GitHub 的 301 重定向兜着；重定向一旦被回收，所有已发出去的命令当场全挂，且没有任何提示。
2. **走了 `releases/latest`** —— 同一份脚本在不同时间装出不同版本，用户报的问题复现不了。
3. **那个 release 其实不存在** —— 上游从未发布过该资产，用户只会看到 curl 的原始错误。

这些不是理论风险，是真实发生过的事故。`isg` 把它们变成可以在 CI 里拦住的东西。

## 快速开始

```bash
git clone https://github.com/taotaoya-code/install-script-guard
cd install-script-guard

# 扫当前目录
python3 isg.py .

# 扫指定脚本，并声明当前仓库用于一致性检查
python3 isg.py install.sh scripts/*.sh --repo owner/name

# 只看 high 级问题
python3 isg.py . --fail-on high --format json
```

无需 `pip install`。Windows 上用 `python isg.py`。

## 检测规则

| 规则 | 级别 | 检测内容 |
|---|---|---|
| `ISG001` | high | 把网络内容直接交给 shell 执行（`curl \| bash`、`bash <(curl ...)`） |
| `ISG002` | high | 下载了归档文件，但全文没有任何 sha256 校验 |
| `ISG003` | high | 硬编码的 owner 与当前仓库不一致（改名即静默失效）；无 `--repo` 时降为 medium |
| `ISG004` | medium | 存在 `releases/latest` 分支（可用 `RELEASE_TAG` 覆盖时降为 low） |
| `ISG005` | high | 先要求 root，再执行刚从网络取回的内容 |
| `ISG006` | medium | 缺少 errexit（`set -e`）；已有 `-e` 但缺 `pipefail` 时为 low |
| `ISG007` | low | 用了 `mktemp` 但没有 `trap` 清理 |
| `ISG008` | medium | `curl` 缺少 `-f`（404 被当成功）或缺 `--max-time` |
| `ISG009` | medium | `rm -rf` 后的变量未加引号 |
| `ISG010` | low | 从 release 下载但缺少「资产不存在」的显式提示 |

规则实现都在 `isg.py` 的 `RULES` 列表里，每条一个独立函数，可以单独测试或替换。

## 在 CI 里用

```yaml
name: install-script-audit
on: [pull_request]

jobs:
  isg:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: taotaoya-code/install-script-guard@v0.1.0
        with:
          paths: "."
          fail-on: high        # high 级问题直接让 CI 失败
          format: sarif
          upload-sarif: "true" # 结果进入 Code Scanning
```

只想要报告不想卡流程：`fail-on: none`。

## 输出格式

四种，同一个扫描引擎：

| `--format` | 用途 |
|---|---|
| `md`（默认） | 给人看的 Markdown 表格 + 修复建议 |
| `json` | 给脚本/其他工具消费 |
| `sarif` | GitHub Code Scanning，可在 PR 的 Files changed 里直接标行 |
| `codex` | 生成可投喂给 Codex 的提示词，用于产出具体补丁 |

### 与 Codex 配合

`--format codex` 输出一份带约束的任务说明（要求给出行号、给出可应用的 diff、不得引入新依赖、误报必须说明理由）。典型用法：

```bash
python3 isg.py . --format codex > /tmp/isg-prompt.md
codex exec "$(cat /tmp/isg-prompt.md)"
```

分工是刻意的：**确定性规则负责「找出问题」，Codex 负责「解释并写补丁」**。让模型判断「有没有漏洞」是不可靠的，所以它不参与判断。

## 退出码

| 退出码 | 含义 |
|---|---|
| `0` | 没有达到 `--fail-on` 阈值的问题 |
| `1` | 存在问题，达到或超过阈值 |

`--fail-on` 取 `high`（默认）/ `medium` / `low` / `none`。

## 设计取舍

- **零依赖**：只用 Python 标准库。CI 里不用装任何东西，离线能用。审计工具本身不该成为供应链风险。
- **单文件核心**：`isg.py` 独立可跑，方便复制进别人的仓库当脚本用。
- **规则而非模型**：判定靠正则与结构化解析。误报率可量化、结果可复现，不用 API key。
- **不自动修复**：只报告。自动改别人的安装脚本风险太高，修复交给人或 Codex。

## 局限（明确说清）

- 只做**静态文本分析**。不解析 shell 语义，不追踪跨文件数据流（例如变量在 A 文件赋值、B 文件使用）。
- 对高度混淆或动态拼接（`eval "$(...)"`）的脚本会漏报。
- 规则集是**已知模式**，不是完备的漏洞检测。它拦的是常见事故，不是所有攻击。
- `--repo` 一致性检查依赖传入的仓库名，CI 里用 `${{ github.repository }}` 才有意义。

## 开发

```bash
python3 -m unittest discover -s tests -v
```

测试包含真实样本：`tests/fixtures/real-vps-benchmark-quick-install.sh` 是一个实际部署过的一键安装脚本，CI 里会断言它至少触发一条 high 级告警——保证规则不是只在玩具样本上有效。

当前状态：43 个测试，在 Ubuntu / Windows / macOS × Python 3.8 / 3.12 上全部通过。

## 贡献

见 [CONTRIBUTING.md](CONTRIBUTING.md)。新增规则需要两个测试：一个必须命中，一个必须不命中。

## License

MIT，见 [LICENSE](LICENSE)。
