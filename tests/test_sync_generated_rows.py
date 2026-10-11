#!/usr/bin/env python3
"""Tests for the generated-preset-rows precondition in `scripts/sync.py`.

WHY THIS TEST EXISTS. `scripts/make-preset-rows.mjs` documents its own `--check` as
living "in CI rather than a one-off" and NOTHING ran it: `.github/workflows/` is empty,
there is no root `package.json`, and the only caller was a test a human has to remember
to run. So the committed generated profile artefacts sat one generation behind their
source, and a corrected row came back through a later sync with it
(`docs/mesh/166-web-profile-office-references.md` §3, §7). `sync.py` is where this
estate actually runs its checks — the 15-minute tick that publishes committed HEAD onto
`~/.dsh` — so the check went there, next to the version precondition that already had the
same shape and the same blast radius rule (skip the one step, never the sync).

WHAT IS ASSERTED, and it is the decision rather than the subprocess:
  * `--check` exit 0  -> (0, ...) and the profile step RUNS;
  * `--check` exit 1  -> (1, ...) and the profile step is SKIPPED, with the DRIFT line in
    the reason (the verdict line for the standalone artefact goes to stderr and the
    managed-block verdict to stdout, so a naive "first --check: line" reported a cheerful
    "UP TO DATE" as the reason for a skip — that regression is pinned here);
  * a check that CANNOT run (no generator, no node) -> (2, ...) and the profile step is
    SKIPPED: a generated file whose generation cannot be reproduced is not installed on
    every machine;
  * neither skip message contains the word WOULD, because `autosync.ps1` reads that word
    as "did not converge" and would stall the whole job every tick.

No network, no real generator run from the tests: `sync.GENERATOR` is pointed at a script
written into tmp_path, so the tests measure `sync.py`'s handling of each outcome.

Run:  python -m pytest tests/test_sync_generated_rows.py -q
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


def _load_sync():
    spec = importlib.util.spec_from_file_location("harness_sync", REPO / "scripts" / "sync.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules["harness_sync"] = module
    spec.loader.exec_module(module)
    return module


sync = _load_sync()


def _fake_generator(tmp_path: Path, exit_code: int, stdout: str = "", stderr: str = "") -> Path:
    """A stand-in for `make-preset-rows.mjs` that produces one exact outcome."""
    script = tmp_path / f"generator-{exit_code}.mjs"
    script.write_text(
        f"process.stdout.write({stdout!r});\n"
        f"process.stderr.write({stderr!r});\n"
        f"process.exit({exit_code});\n",
        encoding="utf-8",
    )
    return script


def test_an_up_to_date_generator_lets_the_profile_step_run(tmp_path, monkeypatch):
    monkeypatch.setattr(sync, "GENERATOR", _fake_generator(
        tmp_path, 0, stdout="--check: UP TO DATE - profiles/web/presets.generated.patch.yml\n"))
    status, note = sync.check_generated_preset_rows()
    assert status == 0
    assert "UP TO DATE" in note
    assert sync.report_generated_step(status, note) is True


def test_drift_skips_the_profile_step_and_names_the_drifting_artefact(tmp_path, monkeypatch, capsys):
    # The real shape: the DRIFT verdict for the standalone artefact arrives on STDERR and
    # the managed-block verdict on STDOUT. A check that read only the first `--check:` line
    # of the concatenation reported the UP TO DATE line as the reason for the skip.
    monkeypatch.setattr(sync, "GENERATOR", _fake_generator(
        tmp_path, 1,
        stdout="--check: managed block UP TO DATE - profiles/web/cordis.patch.yml\n",
        stderr="--check: DRIFT - profiles/web/presets.generated.patch.yml does not match what the converter would write\n",
    ))
    status, note = sync.check_generated_preset_rows()
    assert status == 1
    assert "DRIFT" in note
    assert "presets.generated.patch.yml" in note
    assert sync.report_generated_step(status, note) is False
    printed = capsys.readouterr().out
    assert "SKIPPED" in printed
    assert "make-preset-rows.mjs --install" in printed, "the remedy is in the message"
    assert "WOULD" not in printed, "autosync.ps1 reads WOULD as 'did not converge' and would stall the tick"


def test_a_check_that_cannot_run_skips_the_step_instead_of_publishing_the_artefact(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(sync, "GENERATOR", tmp_path / "not-here.mjs")
    status, note = sync.check_generated_preset_rows()
    assert status == 2
    assert "absent" in note
    assert sync.report_generated_step(status, note) is False
    printed = capsys.readouterr().out
    assert "did NOT run" in printed
    assert "WOULD" not in printed


def test_with_no_node_on_path_the_check_refuses_rather_than_guessing(tmp_path, monkeypatch):
    monkeypatch.setattr(sync, "GENERATOR", _fake_generator(tmp_path, 0))
    monkeypatch.setattr(sync.shutil, "which", lambda name: None)
    status, note = sync.check_generated_preset_rows()
    assert status == 2
    assert "node" in note


def test_the_real_repo_is_up_to_date_and_the_profiles_step_would_run():
    """The committed repo, with the REAL generator — the assertion a stale commit fails."""
    status, note = sync.check_generated_preset_rows()
    assert status == 0, f"the committed generated preset rows are stale: {note}"
    assert sync.report_generated_step(status, note) is True
