# 贡献指南 / Contributing

## 报告问题

提交 issue 时请附上：

1. `python3 isg.py <你的文件> --format json` 的输出
2. 触发告警的那几行脚本（脱敏后）
3. Python 版本与操作系统

如果是**误报**，请在标题里写明 `false positive`，并说明为什么这段代码实际是安全的——误报比漏报更值得优先修。

## 加一条新规则

1. 在 `isg.py` 里新增 `check_xxx(ctx) -> List[Finding]`，保持纯函数、无副作用。
2. 在 `RULES` 列表里注册：`(规则号, 级别, 标题, 函数, 分类)`。
3. 在 `tests/test_rules.py` 里**同时**写两个用例：一个必须命中，一个必须不命中。
4. 在 README 的规则表里补一行。

规则号从 `ISG011` 往后顺延，不要复用已废弃的号。

## 规则的设计约束

- **确定性优先**：不调用 LLM 做判定。判定必须可复现。
- **零依赖**：不引入第三方包。
- **宁可漏报，不可误报泛滥**：误报会让使用者关掉整个工具。
- 每条 `Finding` 必须带 `fix`，只报问题不给方向没有价值。

## 提交 PR

- 一个 PR 只做一件事（一条规则 / 一个 bug）。
- CI 必须全绿：单测、self-audit、shellcheck。
- 改动了规则行为时，同步更新 README 的规则表。

## 开发命令

```bash
python3 -m unittest discover -s tests -v
python3 isg.py . --repo owner/name
```
