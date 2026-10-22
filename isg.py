#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""install-script-guard (isg)

一键安装脚本的供应链风险审计器。

用途：在 PR / CI 里对 `.sh` / `.bash` / `.bats` 安装脚本做确定性规则检测，
输出 Markdown / JSON / SARIF 报告，可配置退出码作为合并门槛。

零第三方依赖，Python 3.8+。

检测规则集中在 RULES 列表里，每条规则独立、可单独测试。
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Callable, Iterable, List, Optional, Sequence, Tuple

__version__ = "0.1.0"

SEVERITY_ORDER = {"high": 0, "medium": 1, "low": 2}

# 扫描的脚本扩展名
SCRIPT_SUFFIXES = (".sh", ".bash", ".bats")

# 默认跳过的目录
SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv", "dist", "build"}


@dataclass(frozen=True)
class Finding:
    rule_id: str
    severity: str
    title: str
    path: str
    line: int
    message: str
    snippet: str
    fix: str

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Context:
    """一次扫描的运行上下文。"""

    path: str
    text: str
    # (起始行号, 合并续行后的逻辑行)
    logical: List[Tuple[int, str]]
    # 形如 "owner/repo"；用于检测硬编码 owner 与当前仓库不一致
    repo: Optional[str] = None

    @property
    def owner(self) -> Optional[str]:
        if not self.repo or "/" not in self.repo:
            return None
        return self.repo.split("/", 1)[0]

    def raw_lines(self) -> List[Tuple[int, str]]:
        return list(enumerate(self.text.splitlines(), 1))


def _iter_logical_lines(text: str) -> List[Tuple[int, str]]:
    """合并反斜杠续行与 && / || 之后的换行，保留起始行号。"""
    lines = text.splitlines()
    out: List[Tuple[int, str]] = []
    buf: List[str] = []
    start = 0
    for i, line in enumerate(lines, 1):
        if not buf:
            start = i
        stripped = line.rstrip()
        if stripped.endswith("\\"):
            buf.append(stripped[:-1].rstrip())
            continue
        buf.append(line)
        joined = " ".join(x.strip() for x in buf if x.strip())
        out.append((start, joined))
        buf = []
    if buf:
        out.append((start, " ".join(x.strip() for x in buf if x.strip())))
    return out


def _first_match(ctx: Context, pattern: re.Pattern) -> Optional[Tuple[int, str]]:
    for lineno, line in ctx.logical:
        m = pattern.search(line)
        if m:
            return lineno, line.strip()
    return None


def _all_matches(ctx: Context, pattern: re.Pattern) -> List[Tuple[int, str]]:
    hits = []
    for lineno, line in ctx.logical:
        if pattern.search(line):
            hits.append((lineno, line.strip()))
    return hits


# --------------------------------------------------------------------------
# 规则实现
# --------------------------------------------------------------------------

def check_pipe_to_shell(ctx: Context) -> List[Finding]:
    """ISG001：把远程内容直接喂给 shell 解释器。"""
    pat = re.compile(
        r"(?:bash|sh|zsh)\s*<\s*\(\s*(?:curl|wget)"
        r"|(?:curl|wget)\b[^|]*\|\s*(?:sudo\s+)?(?:bash|sh|zsh)\b",
        re.IGNORECASE,
    )
    out = []
    for lineno, line in _all_matches(ctx, pat):
        out.append(Finding(
            rule_id="ISG001", severity="high",
            title="直接执行远程脚本", path=ctx.path, line=lineno,
            message="脚本把网络内容直接交给 shell 解释执行，中间没有任何落盘与校验步骤。上游被篡改或返回错误页面时，本机立刻执行未知代码。",
            snippet=line, fix="先下载到临时文件并校验 sha256，再执行；或固定 tag 而非分支/最新版。",
        ))
    return out


def check_missing_checksum(ctx: Context) -> List[Finding]:
    """ISG002：下载了归档文件，却没有做完整性校验。"""
    downloads = _all_matches(ctx, re.compile(
        r"(?:curl|wget)\b[^\n]*?(?:-o|-O|--output)\s*\S+.*?\.(?:tar\.gz|tgz|zip|tar\.xz)\b",
        re.IGNORECASE))
    if not downloads:
        return []
    has_verify = re.search(
        r"(?:sha256sum|shasum\s+-a\s*256|openssl\s+dgst|Get-FileHash|sha256\s+-c)",
        ctx.text, re.IGNORECASE)
    if has_verify:
        return []
    lineno, line = downloads[0]
    return [Finding(
        rule_id="ISG002", severity="high",
        title="下载归档但无完整性校验", path=ctx.path, line=lineno,
        message="脚本下载了压缩包，全文找不到 sha256sum / shasum / Get-FileHash 之类的校验动作。传输错误与内容替换都无法被发现。",
        snippet=line, fix="随包发布 .sha256 文件，下载后执行 sha256sum -c 并在失败时 exit 1。",
    )]


def check_hardcoded_owner(ctx: Context) -> List[Finding]:
    """ISG003：硬编码仓库 owner，改名即静默失效。"""
    pat = re.compile(r"github\.com[/:]([A-Za-z0-9][A-Za-z0-9-]{0,38})/([A-Za-z0-9._-]+)")
    out = []
    seen = set()
    cur_owner = ctx.owner
    for lineno, line in ctx.logical:
        for m in pat.finditer(line):
            owner, repo = m.group(1), m.group(2).rstrip(".git")
            key = f"{owner}/{repo}"
            if key in seen:
                continue
            seen.add(key)
            if cur_owner and owner != cur_owner:
                out.append(Finding(
                    rule_id="ISG003", severity="high",
                    title="硬编码 owner 与当前仓库不一致", path=ctx.path, line=lineno,
                    message=f"脚本里写死了 `{key}`，而当前仓库属于 `{cur_owner}`。仓库改名后这类地址只剩 GitHub 的重定向兜底，一旦重定向被回收，安装链路会当场断掉且没有提示。",
                    snippet=line, fix=f"改为 `{cur_owner}/{repo}`，或把 owner 提成可覆盖的变量并加注释。",
                ))
            elif not cur_owner:
                out.append(Finding(
                    rule_id="ISG003", severity="medium",
                    title="硬编码仓库地址", path=ctx.path, line=lineno,
                    message=f"脚本写死了 `{key}`。仓库改名或转移后需要人工改脚本，无重定向时会直接 404。",
                    snippet=line, fix="提成变量，或用 --repo 参数传入以便 CI 检查一致性。",
                ))
    return out


def check_latest_tag(ctx: Context) -> List[Finding]:
    """ISG004：使用 releases/latest，构建不可复现。"""
    pat = re.compile(r"releases/latest(?:/download)?", re.IGNORECASE)
    hits = _all_matches(ctx, pat)
    if not hits:
        return []
    # 若脚本支持用 RELEASE_TAG 覆盖并显式判断非空，说明固定版本这条路存在，降为 low
    overridable = bool(re.search(
        r"\[\s+-n\s+\"?\$\{?RELEASE_TAG", ctx.text))
    severity = "low" if overridable else "medium"
    out = []
    for lineno, line in hits[:1]:
        out.append(Finding(
            rule_id="ISG004", severity=severity,
            title="存在 releases/latest 分支", path=ctx.path, line=lineno,
            message=("处于 else 分支：未传 RELEASE_TAG 时会走 latest，同一份脚本在不同时间装出不同版本，出问题无法复现。"
                     if overridable else
                     "指向 latest 的下载地址会随上游发版漂移，同一份脚本在不同时间装出不同版本，出问题无法复现。"),
            snippet=line, fix="固定具体 tag（可用 RELEASE_TAG 环境变量覆盖，默认写死一个已验证版本）。",
        ))
    return out


def check_root_exec(ctx: Context) -> List[Finding]:
    """ISG005：以 root 身份执行下载来的内容。"""
    if not re.search(r"EUID|id\s+-u|\$\(id\s+-u\)", ctx.text):
        return []
    execs = _all_matches(ctx, re.compile(
        r"(?:exec\s+)?(?:sudo\s+)?(?:bash|sh|zsh)\s+\"?\$\{?(?:UNPACK_DIR|TMP_DIR|INSTALL_DIR)", re.IGNORECASE))
    if not execs:
        return []
    lineno, line = execs[0]
    return [Finding(
        rule_id="ISG005", severity="high",
        title="root 身份执行下载内容", path=ctx.path, line=lineno,
        message="脚本先要求 root，再执行刚从网络取回的内容。校验环节一旦缺失或写错，等于把 root 直接交给上游。",
        snippet=line, fix="校验必须在提权之前完成；执行前打印将执行的绝对路径与 sha256，便于人工确认。",
    )]


def check_strict_mode(ctx: Context) -> List[Finding]:
    """ISG006：缺少 errexit；有 -e 但缺 pipefail 时降级提示。"""
    if not ctx.text.strip():
        return []
    has_errexit = False
    has_pipefail = False
    for _lineno, line in ctx.logical:
        m = re.match(r"\s*set\s+-([a-zA-Z]+)", line)
        if m:
            flags = m.group(1)
            if "e" in flags:
                has_errexit = True
            if "E" in flags and "e" in flags and "u" in flags:
                pass
        if re.match(r"\s*set\s+-o\s+errexit", line):
            has_errexit = True
        if "pipefail" in line:
            has_pipefail = True
    if not has_errexit:
        return [Finding(
            rule_id="ISG006", severity="medium",
            title="缺少 errexit", path=ctx.path, line=1,
            message="未开启 errexit（set -e）。任何命令失败都会被静默忽略，后续步骤在错误状态上继续跑，最终表现为“装成功了但用不了”。",
            snippet="(文件开头)", fix="在 shebang 之后加 `set -Eeuo pipefail`。",
        )]
    if not has_pipefail:
        return [Finding(
            rule_id="ISG006", severity="low",
            title="缺少 pipefail", path=ctx.path, line=1,
            message="已开启 errexit，但未设置 pipefail。管道中间的命令失败不会中断脚本（例如 `curl ... | tar -xz` 里 curl 失败时仍会继续）。",
            snippet="(文件开头)", fix="补上 `set -o pipefail`，或在 set 行里写全 `set -Eeuo pipefail`。",
        )]
    return []


def check_trap_cleanup(ctx: Context) -> List[Finding]:
    """ISG007：用了 mktemp 但没有 trap 清理。"""
    m = _first_match(ctx, re.compile(r"mktemp|tmpdir=|TMP_DIR=", re.IGNORECASE))
    if not m:
        return []
    if re.search(r"^\s*trap\s+", ctx.text, re.MULTILINE):
        return []
    lineno, line = m
    return [Finding(
        rule_id="ISG007", severity="low",
        title="临时目录无 trap 清理", path=ctx.path, line=lineno,
        message="创建了临时目录但没注册 trap。脚本中途失败或被杀掉时，临时文件会残留在本机。",
        snippet=line, fix="创建后立刻 `trap 'rm -rf \"$TMP_DIR\"' EXIT`。",
    )]


def check_curl_flags(ctx: Context) -> List[Finding]:
    """ISG008：curl 缺 -f（失败静默）或缺超时。"""
    out = []
    for lineno, line in _all_matches(ctx, re.compile(r"\bcurl\b")):
        missing = []
        if not re.search(r"(?:^|\s)-[a-zA-Z]*f", line):
            missing.append("-f")
        if not re.search(r"--max-time|--connect-timeout|-m\s+\d", line):
            missing.append("--max-time")
        if missing:
            out.append(Finding(
                rule_id="ISG008", severity="medium",
                title="curl 缺少失败/超时保护", path=ctx.path, line=lineno,
                message=f"这条 curl 缺少 {' / '.join(missing)}。没 -f 时 404 页面会被当成功保存；没超时会在网络异常时长时间挂住。",
                snippet=line, fix="补上 `-f`（或 `--fail`）与 `--max-time 60`。",
            ))
    return out


def check_rm_rf_unquoted(ctx: Context) -> List[Finding]:
    """ISG009：rm -rf 变量未加引号。"""
    pat = re.compile(r"rm\s+-[a-zA-Z]*[rf][a-zA-Z]*\s+\$[A-Za-z_][A-Za-z0-9_]*\s*(?:$|[;&|])")
    out = []
    for lineno, line in _all_matches(ctx, pat):
        if '"' in line or "'" in line:
            continue
        out.append(Finding(
            rule_id="ISG009", severity="medium",
            title="rm -rf 变量未加引号", path=ctx.path, line=lineno,
            message="变量为空或含空格时，这条命令会删掉意料之外的路径（经典事故：变量未定义时变成 `rm -rf` 后接空值）。",
            snippet=line, fix="写成 `rm -rf -- \"$VAR\"`，并在使用前校验变量非空。",
        ))
    return out


def check_asset_missing_hint(ctx: Context) -> List[Finding]:
    """ISG010：下载 asset 但没有针对 404 的显式提示。"""
    if not re.search(r"releases/(?:download|latest)", ctx.text, re.IGNORECASE):
        return []
    has_hint = re.search(r"(?:404|not found|不存在|未找到|资产|asset)", ctx.text, re.IGNORECASE)
    if has_hint:
        return []
    return [Finding(
        rule_id="ISG010", severity="low",
        title="下载失败缺少明确提示", path=ctx.path, line=1,
        message="脚本从 release 拉资产，但没有针对“资产不存在 / 无可用 release”的显式报错。上游漏发 release 时，用户只会看到 curl 的原始错误。",
        snippet="(release 下载段)", fix="下载后检查文件存在与非空，失败时提示“上游未发布该资产”并给出仓库地址。",
    )]


Def = Tuple[str, str, str, Callable[[Context], List[Finding]], str]

RULES: List[Def] = [
    ("ISG001", "high", "直接执行远程脚本", check_pipe_to_shell, "供应链"),
    ("ISG002", "high", "下载归档但无完整性校验", check_missing_checksum, "完整性"),
    ("ISG003", "high", "硬编码仓库地址", check_hardcoded_owner, "可维护性"),
    ("ISG004", "medium", "引用 releases/latest", check_latest_tag, "可复现性"),
    ("ISG005", "high", "root 身份执行下载内容", check_root_exec, "提权"),
    ("ISG006", "medium", "缺少 set -euo pipefail", check_strict_mode, "健壮性"),
    ("ISG007", "low", "临时目录无 trap 清理", check_trap_cleanup, "整洁性"),
    ("ISG008", "medium", "curl 缺少失败/超时保护", check_curl_flags, "健壮性"),
    ("ISG009", "medium", "rm -rf 变量未加引号", check_rm_rf_unquoted, "安全"),
    ("ISG010", "low", "下载失败缺少明确提示", check_asset_missing_hint, "体验"),
]


# --------------------------------------------------------------------------
# 扫描与报告
# --------------------------------------------------------------------------

def scan_text(path: str, text: str, repo: Optional[str] = None) -> List[Finding]:
    ctx = Context(path=path, text=text,
                  logical=_iter_logical_lines(text), repo=repo)
    findings: List[Finding] = []
    for _rid, _sev, _title, fn, _cat in RULES:
        try:
            findings.extend(fn(ctx))
        except Exception as exc:  # 规则不该让整次扫描失败
            findings.append(Finding(
                rule_id=_rid, severity="low", title=f"规则异常: {_title}",
                path=path, line=0, message=f"{type(exc).__name__}: {exc}",
                snippet="", fix="该规则在本次输入上抛错，请上报。",
            ))
    return findings


def iter_scripts(root: Path, excludes: Sequence[str] = ()) -> Iterable[Path]:
    if root.is_file():
        yield root
        return
    root_s = str(root)
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for name in sorted(filenames):
            if not name.endswith(SCRIPT_SUFFIXES):
                continue
            full = Path(dirpath) / name
            full_s = str(full).replace("\\", "/")
            rel_s = full_s
            if root_s.replace("\\", "/") in full_s:
                rel_s = full_s.split(root_s.replace("\\", "/") + "/", 1)[-1]
            if any(_is_excluded(p, full_s, rel_s) for p in excludes):
                continue
            yield full


def _is_excluded(pattern: str, full: str, rel: str) -> bool:
    """--exclude 支持两种写法：目录前缀（tests/fixtures）与通配（*_vendor.sh）。"""
    pat = pattern.replace("\\", "/").rstrip("/")
    if not pat:
        return False
    if any(ch in pat for ch in "*?["):
        import fnmatch
        return fnmatch.fnmatch(rel, pat) or fnmatch.fnmatch(full, pat)
    return rel == pat or rel.startswith(pat + "/") or full.startswith(pat)


def scan_paths(paths: Sequence[str], repo: Optional[str] = None,
               excludes: Sequence[str] = ()) -> List[Finding]:
    findings: List[Finding] = []
    for raw in paths:
        p = Path(raw)
        if not p.exists():
            findings.append(Finding(
                rule_id="ISG000", severity="low", title="路径不存在",
                path=str(p), line=0, message="给定的路径不存在，已跳过。",
                snippet="", fix="检查参数拼写。",
            ))
            continue
        for script in iter_scripts(p, excludes):
            try:
                text = script.read_text(encoding="utf-8", errors="replace")
            except OSError as exc:
                findings.append(Finding(
                    rule_id="ISG000", severity="low", title="读取失败",
                    path=str(script), line=0, message=str(exc),
                    snippet="", fix="检查文件权限。",
                ))
                continue
            if p.is_dir():
                rel = str(script.relative_to(p)).replace("\\", "/")
            else:
                rel = script.name
            findings.extend(scan_text(rel, text, repo))
    findings.sort(key=lambda f: (SEVERITY_ORDER.get(f.severity, 9), f.path, f.line))
    return findings


def render_markdown(findings: Sequence[Finding], scanned: int) -> str:
    counts = {k: sum(1 for f in findings if f.severity == k) for k in ("high", "medium", "low")}
    lines = ["# install-script-guard 报告", ""]
    lines.append(f"扫描文件：{scanned} 个　·　high {counts['high']}　medium {counts['medium']}　low {counts['low']}")
    lines.append("")
    if not findings:
        lines.append("✅ 未发现已知风险模式。")
        return "\n".join(lines) + "\n"
    lines.append("| 级别 | 规则 | 位置 | 说明 |")
    lines.append("|---|---|---|---|")
    for f in findings:
        loc = f"{f.path}:{f.line}" if f.line else f.path
        msg = f.message.replace("|", "\\|")
        lines.append(f"| {f.severity} | `{f.rule_id}` {f.title} | `{loc}` | {msg} |")
    lines.append("")
    lines.append("## 修复建议")
    lines.append("")
    seen = set()
    for f in findings:
        if f.rule_id in seen:
            continue
        seen.add(f.rule_id)
        lines.append(f"- **{f.rule_id} {f.title}**（{f.path}:{f.line}）→ {f.fix}")
    return "\n".join(lines) + "\n"


def render_json(findings: Sequence[Finding], scanned: int) -> str:
    payload = {
        "tool": "install-script-guard",
        "version": __version__,
        "scanned_files": scanned,
        "summary": {k: sum(1 for f in findings if f.severity == k) for k in ("high", "medium", "low")},
        "findings": [f.to_dict() for f in findings],
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


def render_sarif(findings: Sequence[Finding]) -> str:
    rules = {}
    for rid, sev, title, _fn, cat in RULES:
        rules[rid] = {
            "id": rid,
            "name": title,
            "shortDescription": {"text": title},
            "defaultConfiguration": {"level": "error" if sev == "high" else "warning" if sev == "medium" else "note"},
            "properties": {"category": cat},
        }
    results = []
    for f in findings:
        results.append({
            "ruleId": f.rule_id,
            "level": "error" if f.severity == "high" else "warning" if f.severity == "medium" else "note",
            "message": {"text": f"{f.title}: {f.message}"},
            "locations": [{
                "physicalLocation": {
                    "artifactLocation": {"uri": f.path.replace("\\", "/")},
                    "region": {"startLine": max(1, f.line)},
                }
            }],
        })
    doc = {
        "$schema": "https://json.schemastore.org/sarif-2.1.0.json",
        "version": "2.1.0",
        "runs": [{
            "tool": {"driver": {
                "name": "install-script-guard",
                "version": __version__,
                "informationUri": "https://github.com/",
                "rules": list(rules.values()),
            }},
            "results": results,
        }],
    }
    return json.dumps(doc, ensure_ascii=False, indent=2)


def render_codex(findings: Sequence[Finding], scanned: int) -> str:
    """输出可直接投喂给 Codex 的提示词。

    设计目标：把确定性扫描结果转成一份带约束的任务说明，让 Codex 在 PR 里
    针对 high/medium 问题产出具体补丁建议，而不是自由发挥。
    """
    counts = {k: sum(1 for f in findings if f.severity == k) for k in ("high", "medium", "low")}
    head = [
        "你是一名开源项目维护助手。下面是对本仓库安装脚本的确定性静态扫描结果。",
        "请只针对 high 与 medium 级问题给出修改方案；low 级只需一句话说明是否需要处理。",
        "要求：",
        "1. 每条建议必须给出具体文件、行号、以及可直接应用的 diff 或替换片段。",
        "2. 不要引入新的第三方依赖。",
        "3. 不要改动与本报告无关的代码。",
        "4. 若某条告警是误报，请明确指出理由，不要静默忽略。",
        "",
        f"扫描文件数：{scanned}　high {counts['high']}　medium {counts['medium']}　low {counts['low']}",
        "",
        "## 扫描结果",
        "",
    ]
    if not findings:
        head.append("（无告警）")
        return "\n".join(head) + "\n"
    for f in findings:
        head.append(f"### [{f.severity.upper()}] {f.rule_id} {f.title}")
        head.append(f"- 位置：`{f.path}:{f.line}`")
        head.append(f"- 问题：{f.message}")
        if f.snippet:
            head.append(f"- 代码：`{f.snippet}`")
        head.append(f"- 建议方向：{f.fix}")
        head.append("")
    head.append("## 输出格式")
    head.append("请按文件分组输出，每个文件一节，节内按行号升序列出改动，最后给出一段 200 字以内的总结。")
    return "\n".join(head) + "\n"


def worst_severity(findings: Sequence[Finding]) -> Optional[str]:
    if not findings:
        return None
    return min((f.severity for f in findings), key=lambda s: SEVERITY_ORDER.get(s, 9))


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        prog="isg",
        description="一键安装脚本的供应链风险审计器（零依赖）",
    )
    ap.add_argument("paths", nargs="*", default=["."],
                    help="要扫描的脚本或目录，默认当前目录")
    ap.add_argument("--repo", default=os.environ.get("ISG_REPO"),
                    help="当前仓库 owner/name，用于检查硬编码地址是否一致")
    ap.add_argument("--format", choices=["md", "json", "sarif", "codex"], default="md",
                    help="md | json | sarif | codex（codex 输出可直接投喂给 Codex 的提示词）")
    ap.add_argument("--fail-on", choices=["high", "medium", "low", "none"], default="high",
                    help="达到该级别即返回退出码 1，默认 high")
    ap.add_argument("--exclude", action="append", default=[], metavar="PATTERN",
                    help="跳过匹配的路径，支持目录前缀或通配；可重复，例如 --exclude tests/fixtures")
    ap.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    args = ap.parse_args(argv)

    try:
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    except Exception:
        pass

    paths = args.paths or ["."]
    findings = scan_paths(paths, args.repo, args.exclude)
    scanned = sum(1 for p in paths if Path(p).exists() for _ in iter_scripts(Path(p), args.exclude))

    if args.format == "json":
        print(render_json(findings, scanned))
    elif args.format == "sarif":
        print(render_sarif(findings))
    elif args.format == "codex":
        print(render_codex(findings, scanned), end="")
    else:
        print(render_markdown(findings, scanned), end="")

    if args.fail_on == "none":
        return 0
    threshold = SEVERITY_ORDER[args.fail_on]
    worst = worst_severity(findings)
    if worst is not None and SEVERITY_ORDER.get(worst, 9) <= threshold:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
