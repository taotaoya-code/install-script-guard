#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""install-script-guard 规则测试。

只用标准库 unittest，保证 clone 下来不装任何依赖就能跑：

    python -m unittest discover -s tests -v
"""
import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import isg  # noqa: E402


def scan(text: str, repo=None):
    return isg.scan_text("<test>", text, repo=repo)


def ids(findings):
    return [f.rule_id for f in findings]


GOOD_SCRIPT = """#!/usr/bin/env bash
set -Eeuo pipefail

REPO="myuser/proj"
TAG="v1.0.0"
TMP_DIR="$(mktemp -d)"
trap 'rm -rf -- "$TMP_DIR"' EXIT

BASE="https://github.com/${REPO}/releases/download/${TAG}"
curl -fL --max-time 60 -o "${TMP_DIR}/pkg.tar.gz" "${BASE}/pkg.tar.gz"
curl -fL --max-time 60 -o "${TMP_DIR}/pkg.sha256" "${BASE}/pkg.sha256"

if [[ ! -s "${TMP_DIR}/pkg.tar.gz" ]]; then
  echo "下载失败：上游未发布该资产（asset not found 404）" >&2
  exit 1
fi

( cd "${TMP_DIR}" && sha256sum -c pkg.sha256 )
tar -xzf "${TMP_DIR}/pkg.tar.gz" -C "${TMP_DIR}"
echo "安装完成"
"""


class TestPipeToShell(unittest.TestCase):
    def test_detects_bash_process_substitution(self):
        f = scan("#!/bin/bash\nbash <(curl -fsSL https://example.com/i.sh)\n")
        self.assertIn("ISG001", ids(f))
        self.assertEqual([x.severity for x in f if x.rule_id == "ISG001"], ["high"])

    def test_detects_pipe_to_bash(self):
        f = scan("curl -fsSL https://x/i.sh | bash\n")
        self.assertIn("ISG001", ids(f))

    def test_detects_pipe_to_sudo_sh(self):
        f = scan("wget -qO- https://x/i.sh | sudo sh\n")
        self.assertIn("ISG001", ids(f))

    def test_clean_download_is_not_flagged(self):
        f = scan('curl -fL --max-time 60 -o /tmp/i.sh https://x/i.sh\n')
        self.assertNotIn("ISG001", ids(f))


class TestChecksum(unittest.TestCase):
    def test_flags_archive_without_verification(self):
        text = 'curl -fL --max-time 60 -o /tmp/p.tar.gz https://x/p.tar.gz\ntar -xzf /tmp/p.tar.gz\n'
        self.assertIn("ISG002", ids(scan(text)))

    def test_no_flag_when_sha256sum_present(self):
        text = ('curl -fL --max-time 60 -o /tmp/p.tar.gz https://x/p.tar.gz\n'
                'sha256sum -c /tmp/p.sha256\n')
        self.assertNotIn("ISG002", ids(scan(text)))

    def test_no_flag_when_no_archive(self):
        self.assertNotIn("ISG002", ids(scan('curl -fL --max-time 60 -o /tmp/i.sh https://x/i.sh\n')))


class TestHardcodedOwner(unittest.TestCase):
    def test_flags_mismatched_owner_as_high(self):
        text = 'REPO_URL="git@github.com:olduser/proj.git"\n'
        f = scan(text, repo="newuser/proj")
        got = [x for x in f if x.rule_id == "ISG003"]
        self.assertTrue(got)
        self.assertEqual(got[0].severity, "high")
        self.assertIn("olduser/proj", got[0].message)

    def test_same_owner_not_flagged(self):
        text = 'REPO_URL="git@github.com:newuser/proj.git"\n'
        f = scan(text, repo="newuser/proj")
        self.assertNotIn("ISG003", ids(f))

    def test_without_repo_context_is_medium(self):
        text = 'URL="https://github.com/someone/proj/releases"\n'
        got = [x for x in scan(text) if x.rule_id == "ISG003"]
        self.assertTrue(got)
        self.assertEqual(got[0].severity, "medium")


class TestLatestTag(unittest.TestCase):
    def test_flags_latest(self):
        f = scan('BASE="https://github.com/a/b/releases/latest/download"\n')
        self.assertIn("ISG004", ids(f))

    def test_downgraded_when_tag_overridable(self):
        text = ('RELEASE_TAG="${TAG:-}"\n'
                'if [[ -n "$RELEASE_TAG" ]]; then\n'
                '  BASE="https://github.com/a/b/releases/download/$RELEASE_TAG"\n'
                'else\n'
                '  BASE="https://github.com/a/b/releases/latest/download"\n'
                'fi\n')
        got = [x for x in scan(text) if x.rule_id == "ISG004"]
        self.assertTrue(got)
        self.assertEqual(got[0].severity, "low")

    def test_pinned_tag_clean(self):
        f = scan('BASE="https://github.com/a/b/releases/download/v1.0.0"\n')
        self.assertNotIn("ISG004", ids(f))


class TestRootExec(unittest.TestCase):
    def test_flags_root_then_exec(self):
        text = ('if [[ ${EUID:-$(id -u)} -ne 0 ]]; then exit 1; fi\n'
                'exec bash "$INSTALL_DIR/install.sh"\n')
        got = [x for x in scan(text) if x.rule_id == "ISG005"]
        self.assertTrue(got)
        self.assertEqual(got[0].severity, "high")

    def test_exec_without_root_check_clean(self):
        f = scan('exec bash "$INSTALL_DIR/install.sh"\n')
        self.assertNotIn("ISG005", ids(f))


class TestStrictMode(unittest.TestCase):
    def test_missing_errexit_is_medium(self):
        got = [x for x in scan('#!/bin/bash\necho hi\n') if x.rule_id == "ISG006"]
        self.assertTrue(got)
        self.assertEqual(got[0].severity, "medium")

    def test_uppercase_flags_recognised(self):
        # -Eeuo pipefail 必须被识别，不能因为大写 E 而误报
        f = scan('set -Eeuo pipefail\necho hi\n')
        self.assertNotIn("ISG006", ids(f))

    def test_missing_pipefail_is_low(self):
        got = [x for x in scan('set -eu\necho hi\n') if x.rule_id == "ISG006"]
        self.assertTrue(got)
        self.assertEqual(got[0].severity, "low")

    def test_set_o_errexit_recognised(self):
        self.assertNotIn("ISG006", ids(scan('set -o errexit\nset -o pipefail\n')))


class TestTrapCleanup(unittest.TestCase):
    def test_flags_mktemp_without_trap(self):
        self.assertIn("ISG007", ids(scan('TMP_DIR="$(mktemp -d)"\necho x\n')))

    def test_trap_present_clean(self):
        self.assertNotIn("ISG007", ids(
            scan('TMP_DIR="$(mktemp -d)"\ntrap \'rm -rf -- "$TMP_DIR"\' EXIT\n')))


class TestCurlFlags(unittest.TestCase):
    def test_flags_missing_fail_and_timeout(self):
        got = [x for x in scan('curl -sL -o /tmp/a https://x\n') if x.rule_id == "ISG008"]
        self.assertTrue(got)
        self.assertIn("-f", got[0].message)
        self.assertIn("--max-time", got[0].message)

    def test_full_flags_clean(self):
        self.assertNotIn("ISG008", ids(scan('curl -fL --max-time 60 -o /tmp/a https://x\n')))


class TestRmRf(unittest.TestCase):
    def test_flags_unquoted_variable(self):
        self.assertIn("ISG009", ids(scan("rm -rf $TARGET\n")))

    def test_quoted_clean(self):
        self.assertNotIn("ISG009", ids(scan('rm -rf -- "$TARGET"\n')))

    def test_literal_path_clean(self):
        self.assertNotIn("ISG009", ids(scan("rm -rf /opt/known-dir\n")))


class TestAssetHint(unittest.TestCase):
    def test_flags_silent_failure(self):
        self.assertIn("ISG010", ids(
            scan('U="https://github.com/a/b/releases/latest/download/x.tar.gz"\n')))

    def test_hint_present_clean(self):
        text = ('U="https://github.com/a/b/releases/download/v1/x.tar.gz"\n'
                'echo "未找到该资产" >&2\n')
        self.assertNotIn("ISG010", ids(scan(text)))


class TestGoodScript(unittest.TestCase):
    def test_good_script_has_no_high_or_medium(self):
        f = scan(GOOD_SCRIPT, repo="myuser/proj")
        bad = [x for x in f if x.severity in ("high", "medium")]
        self.assertEqual(bad, [], msg=f"意外告警: {[(x.rule_id, x.message) for x in bad]}")

    def test_good_script_is_clean_overall(self):
        f = scan(GOOD_SCRIPT, repo="myuser/proj")
        self.assertEqual(f, [], msg=f"预期零告警，实际: {[(x.rule_id, x.severity) for x in f]}")


class TestRealSample(unittest.TestCase):
    """用真实的一键安装脚本验证：规则要能抓到真问题，而不是只在玩具样本上有效。"""

    FIXTURE = ROOT / "tests" / "fixtures" / "real-vps-benchmark-quick-install.sh"

    def setUp(self):
        if not self.FIXTURE.exists():
            self.skipTest("真实样本缺失")
        self.text = self.FIXTURE.read_text(encoding="utf-8", errors="replace")

    def test_finds_root_execution(self):
        f = isg.scan_text(self.FIXTURE.name, self.text,
                          repo="taotaoya-code/vps-benchmark-public")
        self.assertIn("ISG005", ids(f))

    def test_finds_missing_timeouts(self):
        f = isg.scan_text(self.FIXTURE.name, self.text)
        self.assertIn("ISG008", ids(f))

    def test_has_at_least_one_high(self):
        f = isg.scan_text(self.FIXTURE.name, self.text)
        self.assertTrue([x for x in f if x.severity == "high"])


class TestExitCode(unittest.TestCase):
    def test_fail_on_high_returns_1_when_high_present(self):
        tmp = ROOT / "tests" / "_tmp_bad.sh"
        tmp.write_text("curl -fsSL https://x/i.sh | bash\n", encoding="utf-8")
        try:
            self.assertEqual(isg.main([str(tmp), "--fail-on", "high"]), 1)
        finally:
            tmp.unlink(missing_ok=True)

    def test_fail_on_none_returns_0(self):
        tmp = ROOT / "tests" / "_tmp_bad2.sh"
        tmp.write_text("curl -fsSL https://x/i.sh | bash\n", encoding="utf-8")
        try:
            self.assertEqual(isg.main([str(tmp), "--fail-on", "none"]), 0)
        finally:
            tmp.unlink(missing_ok=True)


class TestRenderers(unittest.TestCase):
    def test_markdown_contains_table(self):
        f = scan("curl -fsSL https://x/i.sh | bash\n")
        md = isg.render_markdown(f, 1)
        self.assertIn("install-script-guard 报告", md)
        self.assertIn("ISG001", md)

    def test_json_shape(self):
        import json
        f = scan("curl -fsSL https://x/i.sh | bash\n")
        data = json.loads(isg.render_json(f, 1))
        self.assertEqual(data["tool"], "install-script-guard")
        self.assertIn("summary", data)
        self.assertTrue(data["findings"])

    def test_sarif_shape(self):
        import json
        f = scan("curl -fsSL https://x/i.sh | bash\n")
        data = json.loads(isg.render_sarif(f))
        self.assertEqual(data["version"], "2.1.0")
        self.assertEqual(data["runs"][0]["tool"]["driver"]["name"], "install-script-guard")
        self.assertTrue(data["runs"][0]["results"])

    def test_codex_prompt_contains_constraints_and_findings(self):
        f = scan("curl -fsSL https://x/i.sh | bash\n")
        out = isg.render_codex(f, 1)
        self.assertIn("ISG001", out)
        self.assertIn("不要引入新的第三方依赖", out)
        self.assertIn("high 1", out)

    def test_codex_prompt_handles_empty(self):
        self.assertIn("无告警", isg.render_codex([], 0))


class TestEdgeCases(unittest.TestCase):
    def test_empty_file(self):
        self.assertEqual(scan(""), [])

    def test_binary_garbage_does_not_crash(self):
        self.assertIsInstance(scan("\x00\x01\x02 not a script \xff"), list)

    def test_multiline_continuation_is_joined(self):
        text = "curl -fsSL \\\n  https://x/i.sh | \\\n  bash\n"
        self.assertIn("ISG001", ids(scan(text)))


if __name__ == "__main__":
    unittest.main(verbosity=2)
