"""
Synthetic verification for research/capital_size_sweep.py -- no live data, no
network, no real backtest.py invocation (subprocess.run is mocked).

Run: python debug/_verify_capital_size_sweep.py
"""
import os
import shutil
import sys
import tempfile
from pathlib import Path
from unittest import mock

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from research.capital_size_sweep import build_cmd, run_one, _STORM_FLAG_ARGS

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"[{'PASS' if cond else 'FAIL'}] {name} {detail}")


def test_build_cmd_no_gate():
    cmd = build_cmd("pairs.parquet", 100_000)
    check("build_cmd.no_gate.has_capital_sim", "--capital-sim" in cmd)
    check("build_cmd.no_gate.has_account_size", "100000" in cmd)
    check("build_cmd.no_gate.no_storm_flag", not any("storm" in c for c in cmd))
    check("build_cmd.no_gate.no_holdout", "--holdout" not in cmd)


def test_build_cmd_with_gate_and_holdout():
    cmd = build_cmd("pairs.parquet", 500_000, storm_flag="storm_momentum_gate", holdout=True)
    check("build_cmd.gate.has_momentum_flag", "--storm-momentum-gate" in cmd)
    check("build_cmd.gate.has_holdout", "--holdout" in cmd)
    check("build_cmd.gate.has_account_size", "500000" in cmd)


def test_build_cmd_unknown_storm_flag_raises():
    raised = False
    try:
        build_cmd("pairs.parquet", 100_000, storm_flag="not_a_real_flag")
    except ValueError:
        raised = True
    check("build_cmd.unknown_flag_raises", raised)


def test_all_three_gate_flags_map_correctly():
    for flag_name, expected_arg in _STORM_FLAG_ARGS.items():
        cmd = build_cmd("pairs.parquet", 100_000, storm_flag=flag_name)
        check(f"build_cmd.flag_map.{flag_name}", expected_arg in cmd)


def test_run_one_archives_with_correct_name_and_reads_row():
    tmpdir = tempfile.mkdtemp()
    try:
        backtest_out = os.path.join(tmpdir, "output", "backtest")
        archive_dir = os.path.join(tmpdir, "output", "research", "capital_size_sweep")
        os.makedirs(backtest_out, exist_ok=True)
        os.makedirs(archive_dir, exist_ok=True)

        portfolio_path = os.path.join(backtest_out, "portfolio_layer1_storm_capsim_fixed_100000.parquet")
        pd.DataFrame([{"sharpe_portfolio": 0.42, "n_taken": 50, "final_equity": 105000.0}]) \
            .to_parquet(portfolio_path)
        trades_path = portfolio_path.replace("portfolio_", "trades_")
        pd.DataFrame([{"pnl_net": 100.0}]).to_parquet(trades_path)

        with mock.patch("research.capital_size_sweep._BACKTEST_OUT_DIR", backtest_out), \
             mock.patch("research.capital_size_sweep._ARCHIVE_DIR", archive_dir), \
             mock.patch("research.capital_size_sweep.subprocess.run") as mock_run:
            mock_run.return_value = mock.Mock(returncode=0, stdout="", stderr="")
            row, err = run_one("pairs.parquet", 100_000, "storm_momentum_gate", holdout=False)

        check("run_one.no_error", err is None, err)
        check("run_one.row_has_sharpe", row is not None and row.get("sharpe_portfolio") == 0.42)
        check("run_one.row_tagged_with_account_size", row is not None and row.get("account_size") == 100_000)
        check("run_one.row_tagged_is_split", row is not None and row.get("split") == "is")

        expected_archive = os.path.join(archive_dir, "storm_momentum_gate_100000_is.parquet")
        check("run_one.archived_portfolio_file_exists", os.path.exists(expected_archive))
        expected_trades_archive = os.path.join(
            archive_dir, "storm_momentum_gate_100000_is_trades.parquet")
        check("run_one.archived_trades_file_exists", os.path.exists(expected_trades_archive))
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_run_one_reports_subprocess_failure():
    with mock.patch("research.capital_size_sweep.subprocess.run") as mock_run:
        mock_run.return_value = mock.Mock(returncode=1, stdout="stdout text", stderr="stderr text")
        row, err = run_one("pairs.parquet", 100_000, None, holdout=False)
    check("run_one.subprocess_failure_returns_none_row", row is None)
    check("run_one.subprocess_failure_returns_error", err is not None and "stderr text" in err)


if __name__ == "__main__":
    test_build_cmd_no_gate()
    test_build_cmd_with_gate_and_holdout()
    test_build_cmd_unknown_storm_flag_raises()
    test_all_three_gate_flags_map_correctly()
    test_run_one_archives_with_correct_name_and_reads_row()
    test_run_one_reports_subprocess_failure()

    print()
    print(f"{len(PASS)}/{len(PASS) + len(FAIL)} checks passed")
    if FAIL:
        print("FAILED:", FAIL)
        sys.exit(1)
    sys.exit(0)
