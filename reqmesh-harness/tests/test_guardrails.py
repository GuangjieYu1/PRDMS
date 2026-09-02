"""#18 审批门与白名单：fail-closed 裁决、DRAFT 通配 vs MUTATE 必匹配、dry_run_only、ADMIN 双卡、
每次调用重读、approvals CLI（list/add/remove，TTY 与 --yes 同文件）、注册表 ADMIN 分区。"""

from __future__ import annotations

import stat
from pathlib import Path

import pytest

from reqmesh_harness.config import Settings
from reqmesh_harness.errors import ApprovalConfigError
from reqmesh_harness.guardrails.gate import ApprovalGate, GateToken
from reqmesh_harness.guardrails.whitelist import WhitelistEntry, WhitelistStore
from reqmesh_harness.tools import build_registry
from reqmesh_harness.tools.registry import annotations_for

BASE = "http://reqmesh.test"


def _gate(tmp_path, entries=None, **overrides) -> ApprovalGate:
    approvals = tmp_path / "approvals.toml"
    if entries is not None:
        WhitelistStore(approvals).replace(entries)
    kw = dict(base_url=BASE, username="dev", password="dev-pass", approvals_file=approvals)
    kw.update(overrides)
    return ApprovalGate(Settings(**kw))


def _write(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")


# ------------------------------------------------------------------ fail-closed 与层级规则
def test_empty_whitelist_denies_with_fix_hint(tmp_path) -> None:
    decision = _gate(tmp_path).decide("create_requirement", "cessna-172", dry_run=False, level="DRAFT")
    assert decision.status == "denied"
    assert not decision.approved
    assert decision.token is None
    assert "白名单无该工具的条目" in decision.deny_reason
    # 错误含精确修复建议：CLI 命令 + TOML 片段
    assert "reqmesh-harness approvals add create_requirement" in decision.fix_hint
    assert '[["approvals"]]' not in decision.fix_hint
    assert "tool = \"create_requirement\"" in decision.fix_hint


def test_draft_project_optional_wildcards(tmp_path) -> None:
    gate = _gate(tmp_path, [WhitelistEntry(tool="create_requirement")])
    assert gate.decide("create_requirement", "cessna-172", dry_run=False, level="DRAFT").approved
    assert gate.decide("create_requirement", "other-project", dry_run=False, level="DRAFT").approved


def test_draft_project_specific_pins_one_project(tmp_path) -> None:
    gate = _gate(tmp_path, [WhitelistEntry(tool="create_requirement", project="cessna-172")])
    assert gate.decide("create_requirement", "cessna-172", dry_run=False, level="DRAFT").approved
    assert gate.decide("create_requirement", "other", dry_run=False, level="DRAFT").status == "denied"


def test_mutate_requires_exact_project_no_wildcard(tmp_path) -> None:
    gate = _gate(tmp_path, [WhitelistEntry(tool="update_requirement")])  # 通配条目对 MUTATE 无效
    decision = gate.decide("update_requirement", "cessna-172", dry_run=False, level="MUTATE")
    assert decision.status == "denied"
    assert "具体 project" in decision.deny_reason
    assert "--project cessna-172" in decision.fix_hint
    gate2 = _gate(tmp_path, [WhitelistEntry(tool="update_requirement", project="cessna-172")])
    assert gate2.decide("update_requirement", "cessna-172", dry_run=False, level="MUTATE").approved
    assert gate2.decide("update_requirement", "other", dry_run=False, level="MUTATE").status == "denied"


def test_dry_run_only_entry_limits_to_dry_run(tmp_path) -> None:
    gate = _gate(tmp_path, [WhitelistEntry(tool="create_requirement", dry_run_only=True)])
    assert gate.decide("create_requirement", "cessna-172", dry_run=True, level="DRAFT").approved
    real = gate.decide("create_requirement", "cessna-172", dry_run=False, level="DRAFT")
    assert real.status == "denied"
    assert "dry_run_only" in real.deny_reason


def test_admin_disabled_without_env(tmp_path) -> None:
    decision = _gate(tmp_path, [WhitelistEntry(tool="freeze_baseline", project="cessna-172")]).decide(
        "freeze_baseline", "cessna-172", dry_run=False, level="ADMIN"
    )
    assert decision.status == "admin_disabled"
    assert "REQMESH_ENABLE_ADMIN" in decision.deny_reason


def test_admin_double_gate_when_enabled(tmp_path) -> None:
    # 开启后仍需白名单：两道卡缺一不可
    gate = _gate(tmp_path, [], enable_admin=True)
    assert gate.decide("freeze_baseline", "cessna-172", dry_run=False, level="ADMIN").status == "denied"
    gate2 = _gate(tmp_path, [WhitelistEntry(tool="freeze_baseline", project="cessna-172")], enable_admin=True)
    assert gate2.decide("freeze_baseline", "cessna-172", dry_run=False, level="ADMIN").approved
    # 通配条目（无 project）对 ADMIN 无效
    gate3 = _gate(tmp_path, [WhitelistEntry(tool="freeze_baseline")], enable_admin=True)
    assert gate3.decide("freeze_baseline", "cessna-172", dry_run=False, level="ADMIN").status == "denied"


def test_whitelist_reread_per_call(tmp_path) -> None:
    """白名单每次调用重读、不缓存：文件修改后立刻生效。"""
    path = tmp_path / "approvals.toml"
    gate = ApprovalGate(Settings(base_url=BASE, username="dev", password="dev-pass", approvals_file=path))
    assert gate.decide("create_requirement", "cessna-172", dry_run=False, level="DRAFT").status == "denied"
    _write(path, '[[approvals]]\ntool = "create_requirement"\nproject = "cessna-172"\n')
    assert gate.decide("create_requirement", "cessna-172", dry_run=False, level="DRAFT").approved


def test_corrupt_whitelist_is_config_error(tmp_path) -> None:
    path = tmp_path / "approvals.toml"
    _write(path, "[[approvals]\ntool = ")  # 非法 TOML
    gate = ApprovalGate(Settings(base_url=BASE, username="dev", password="dev-pass", approvals_file=path))
    with pytest.raises(ApprovalConfigError):
        gate.decide("create_requirement", "cessna-172", dry_run=False, level="DRAFT")


def test_gate_issued_token_is_opaque_and_tied_to_entry(tmp_path) -> None:
    gate = _gate(tmp_path, [WhitelistEntry(tool="create_requirement", project="cessna-172")])
    decision = gate.decide("create_requirement", "cessna-172", dry_run=False, level="DRAFT")
    assert decision.entry == "create_requirement+cessna-172"
    assert repr(decision.token) == "GateToken(tool='create_requirement', project='cessna-172')"
    assert decision.token.entry.dry_run_only is False


# ------------------------------------------------------------------ 注册表/注解
def test_registry_admin_partition_absent_by_default(monkeypatch) -> None:
    monkeypatch.delenv("REQMESH_ENABLE_ADMIN", raising=False)
    registry = build_registry()
    assert registry.enable_admin is False
    assert len(registry) == 39
    assert all(s.level != "ADMIN" for s in registry.all())  # tools/list 不含 ADMIN（协议层不存在）
    assert registry._admin_specs == {}


def test_registry_admin_partition_enabled_via_env(monkeypatch) -> None:
    monkeypatch.setenv("REQMESH_ENABLE_ADMIN", "1")
    registry = build_registry()
    assert registry.enable_admin is True
    assert all(s.level != "ADMIN" for s in registry.all())  # P2 未注册任何 ADMIN 工具（分区空的）


def test_annotations_four_levels() -> None:
    assert annotations_for("READ").readOnlyHint is True
    for level in ("DRAFT", "MUTATE"):
        ann = annotations_for(level)
        assert ann.readOnlyHint is False  # spec L173 字面语义
        assert ann.destructiveHint is False
    assert annotations_for("ADMIN").destructiveHint is True
    assert annotations_for("ADMIN").readOnlyHint is False


def test_add_admin_rejects_non_admin_level() -> None:
    from reqmesh_harness.tools import ToolSpec
    from reqmesh_harness.tools.registry import ToolRegistry

    registry = ToolRegistry()
    with pytest.raises(ValueError):
        registry.add_admin(ToolSpec(name="x", title="x", domain="x", level="DRAFT", fn=lambda: None))


# ------------------------------------------------------------------ approvals CLI
def _cli_env(monkeypatch, tmp_path):
    monkeypatch.setenv("REQMESH_APPROVALS_FILE", str(tmp_path / "approvals.toml"))
    monkeypatch.setenv("REQMESH_BASE_URL", BASE)
    monkeypatch.setenv("REQMESH_USERNAME", "")
    monkeypatch.setenv("REQMESH_PASSWORD", "")


def test_cli_add_list_remove_scripts(monkeypatch, tmp_path, capsys) -> None:
    from reqmesh_harness.guardrails.approvals_cli import approvals_main

    _cli_env(monkeypatch, tmp_path)
    approvals = tmp_path / "approvals.toml"

    assert approvals_main(["add", "create_requirement", "--yes"]) == 0
    assert approvals_main(["add", "update_requirement", "--project", "cessna-172", "--yes"]) == 0
    out = approvals_main(["list"])
    assert out == 0
    text = capsys.readouterr().out
    assert "create_requirement  project=<通配>" in text
    assert "update_requirement  project=cessna-172" in text

    # 与手改 TOML 同源：门直接读同一文件
    gate = ApprovalGate(Settings(base_url=BASE, approvals_file=approvals))
    assert gate.decide("create_requirement", "any", dry_run=False, level="DRAFT").approved
    assert gate.decide("update_requirement", "cessna-172", dry_run=False, level="MUTATE").approved
    assert gate.decide("update_requirement", "other", dry_run=False, level="MUTATE").status == "denied"

    assert approvals_main(["remove", "create_requirement", "--yes"]) == 0
    assert gate.decide("create_requirement", "any", dry_run=False, level="DRAFT").status == "denied"
    assert approvals_main(["list"]) == 0


def test_cli_mutate_requires_project(monkeypatch, tmp_path, capsys) -> None:
    from reqmesh_harness.guardrails.approvals_cli import approvals_main

    _cli_env(monkeypatch, tmp_path)
    assert approvals_main(["add", "update_requirement", "--yes"]) == 2
    assert "必须指定具体 --project" in capsys.readouterr().err


def test_cli_rejects_read_tool_and_unknown_tool(monkeypatch, tmp_path, capsys) -> None:
    from reqmesh_harness.guardrails.approvals_cli import approvals_main

    _cli_env(monkeypatch, tmp_path)
    assert approvals_main(["add", "list_requirements", "--yes"]) == 2
    assert "READ 层工具" in capsys.readouterr().err
    assert approvals_main(["add", "no_such_tool", "--yes"]) == 2
    assert "不在注册表" in capsys.readouterr().err


class _FakeStdin:
    def __init__(self, answer: str = "y\n", tty: bool = True) -> None:
        self._answer = answer
        self._tty = tty

    def isatty(self) -> bool:
        return self._tty

    def readline(self, *a) -> str:
        return self._answer


def test_cli_interactive_tty_confirm(monkeypatch, tmp_path, capsys) -> None:
    from reqmesh_harness.guardrails.approvals_cli import approvals_main

    _cli_env(monkeypatch, tmp_path)
    monkeypatch.setattr("sys.stdin", _FakeStdin("y\n"))
    assert approvals_main(["add", "create_requirement"]) == 0
    raw = (tmp_path / "approvals.toml").read_text(encoding="utf-8")
    assert 'tool = "create_requirement"' in raw

    monkeypatch.setattr("sys.stdin", _FakeStdin("n\n"))
    assert approvals_main(["add", "create_risk"]) == 1
    assert "create_risk" not in (tmp_path / "approvals.toml").read_text(encoding="utf-8")


def test_cli_non_tty_without_yes_aborts(monkeypatch, tmp_path, capsys) -> None:
    from reqmesh_harness.guardrails.approvals_cli import approvals_main

    _cli_env(monkeypatch, tmp_path)
    monkeypatch.setattr("sys.stdin", _FakeStdin(tty=False))
    assert approvals_main(["add", "create_requirement"]) == 1
    assert "请加 --yes" in capsys.readouterr().err


def test_whitelist_file_0600_and_parseable(monkeypatch, tmp_path) -> None:
    from reqmesh_harness.guardrails.approvals_cli import approvals_main

    _cli_env(monkeypatch, tmp_path)
    approvals_main(["add", "create_requirement", "--yes"])
    approvals_main(["add", "update_requirement", "--project", "cessna-172", "--dry-run-only", "--yes"])
    path = tmp_path / "approvals.toml"
    raw = path.read_text(encoding="utf-8")
    assert "dry_run_only = true" in raw
    mode = stat.S_IMODE(path.stat().st_mode)
    assert mode == 0o600
    # 再写回 round-trip：门可解析
    gate = ApprovalGate(Settings(base_url=BASE, approvals_file=path))
    assert gate.decide("update_requirement", "cessna-172", dry_run=False, level="MUTATE").status == "denied"
    assert gate.decide("update_requirement", "cessna-172", dry_run=True, level="MUTATE").approved


def test_console_script_dispatches_approvals(tmp_path, monkeypatch, capsys) -> None:
    """`reqmesh-harness approvals list` 经 console script 可用（cli.py 分发）。"""
    from reqmesh_harness.cli import main

    _cli_env(monkeypatch, tmp_path)
    assert main(["approvals", "list"]) == 0
    assert "（空）" in capsys.readouterr().out
