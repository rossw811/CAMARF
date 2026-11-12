#!/bin/bash
# 2026-11-11 Amendment 8 re-run on CachyOS (docs/PREREGISTRATION_STRATEGY_SEARCH_2026-09-27.md, Amendment 8): BUG-D123
# half-lives. Discovery is NOT re-run (no half-life is read there); adapter -> pools -> spreads -> search, primary and
# the `--arm hlbc` comparison arm. Ross 2026-11-05 / 2026-11-11 "yes to all". Every step stops the chain on failure.
cd ~/CAMARF || exit 1
L=logs/latest/latest_run_rerun_a8_cachyos_20261111.log; S=output/research; PY=.venv/bin/python
export PYTHONUTF8=1
git pull -q --ff-only origin main || { echo "$(date '+%F %T') git pull failed -- STOPPED" >> $L; exit 1; }
run() { local name=$1; shift; echo "$(date '+%F %T') START $name: $*" >> $L
  "$@" > $S/_stdout_a8_$name.log 2>&1 || { echo "$(date '+%F %T') FAILED $name -- STOPPED" >> $L; exit 1; }
  echo "$(date '+%F %T') done $name" >> $L; }
seal_gate() { $PY seal.py --audit > $S/_stdout_a8_seal_audit_$1.log 2>&1 \
  || { echo "$(date '+%F %T') GUARD: live caches hold sealed rows ($1) -- STOPPED" >> $L; exit 1; }
  echo "$(date '+%F %T') seal audit ($1): 0 live files with sealed rows" >> $L; }
LIST=$S/a8_cachyos_cache_listing_20261111.tsv
listing() { $PY - "$1" <<'EOF'
import os, sys
root = os.path.join("output", "cache"); cur = {}
for r, _, fs in os.walk(root):
    for f in fs:
        p = os.path.join(r, f); rel = os.path.relpath(p, root).replace("\\", "/"); t = rel.split("/")[0]
        if "/" in rel and t.startswith("_") and t != "_sealed_vault":
            continue                         # backups / derived memos (sync_cache.py rule)
        cur[rel] = os.path.getsize(p)
open(sys.argv[1], "w", encoding="utf-8").write("".join(f"{p}\t{cur[p]}\n" for p in sorted(cur)))
print(len(cur))
EOF
}
parity() { local f=$S/a8_cachyos_cache_listing_$1.tsv; n=$(listing $f)
  if cmp -s $LIST $f; then echo "$(date '+%F %T') parity ($1): $n files, MATCH" >> $L; return 0; fi
  echo "$(date '+%F %T') parity ($1): $n files, DIFFERS from start ($(diff $LIST $f | grep -c '^[<>]') lines)" >> $L; return 1; }

echo "$(date '+%F %T') start: $(git log --oneline -1 | cut -c1-90) on $(hostname)" >> $L
n=$(listing $LIST); echo "$(date '+%F %T') cache listing saved: $n files, sha256 $(sha256sum $LIST | cut -c1-16)" >> $L
seal_gate start
# Amendment 7 outputs are reported as superseded, never overwritten: search outputs, pools, and the pool pairs' spreads.
K=$S/_superseded_a7_20261111; mkdir -p $K/spreads
for f in $S/strategy_search/*.parquet $S/strategy_search/*.json $S/purity_pairs_pit_k1_clean.parquet \
         $S/purity_pairs_pit_k2_clean.parquet $S/purity_pairs.parquet $S/purity_pairs_pit_k1.parquet $S/purity_pairs_pit_k2.parquet; do
  [ -e "$f" ] && { cp -n "$f" $K/ || exit 1; }; done
$PY - $K <<'EOF' >> $L 2>&1 || { echo "$(date '+%F %T') could not keep the A7 spreads -- STOPPED" >> $L; exit 1; }
import os, shutil, sys, pandas as pd
sys.path.insert(0, ".")
import backtest as bt
P = pd.read_parquet("output/research/purity_pairs_pit_k1_clean.parquet"); n = 0
for tf_dir, tf in bt._TF_DIRS:
    for a, b in zip(*(P.loc[P.tf_label == tf, c] for c in ("symbol_a", "symbol_b"))):
        sp = bt._spread_path(tf_dir, a, b)
        if os.path.exists(sp):
            d = os.path.join(sys.argv[1], "spreads", tf_dir); os.makedirs(d, exist_ok=True); shutil.copy2(sp, d); n += 1
print(f"A7 pool spreads kept: {n} files")
EOF
[ -s $K/summary.parquet ] || { echo "GUARD: no Amendment 7 summary to keep -- STOPPED" >> $L; exit 1; }
echo "$(date '+%F %T') Amendment 7 outputs kept in $K: $(ls $K | wc -l) files + spreads/" >> $L

$PY debug/_run_all_verify.py --workers 4 --timeout 900 > docs/bug_recheck/suite_20261111_a8_cachyos.log 2>&1
FAILS=$(grep -E "\] (FAIL|TIMEOUT|ERROR) " docs/bug_recheck/suite_20261111_a8_cachyos.log \
  | grep -v "_verify_paper_claims.py\|_verify_paper_magnitude_claims.py" | wc -l)
echo "$(date '+%F %T') suite: $(grep -cE '\] (PASS|FAIL|TIMEOUT|ERROR) ' docs/bug_recheck/suite_20261111_a8_cachyos.log) tests, unexplained failures: $FAILS" >> $L
[ "$FAILS" -eq 0 ] || { echo "unexplained suite failures -- STOPPED" >> $L; exit 1; }
parity after_suite || { echo "GUARD: a test changed the real cache -- STOPPED" >> $L; exit 1; }

run adapter $PY -u research/episodic_pairs_adapter.py --fresh
run comparison_arms $PY -u research/build_comparison_arm_pairs.py
run pit_eligibility $PY -u research/purity_pit_eligibility.py
run clean_pools $PY -u research/clean_pool_identity_pairs.py
$PY - $K <<'EOF' >> $L 2>&1
import sys, pandas as pd
for k in (1, 2):
    c = ["symbol_a", "symbol_b", "tf_label", "eligible_from"]
    a = pd.read_parquet(f"{sys.argv[1]}/purity_pairs_pit_k{k}_clean.parquet")[c].sort_values(c[:3]).reset_index(drop=True)
    b = pd.read_parquet(f"output/research/purity_pairs_pit_k{k}_clean.parquet")[c].sort_values(c[:3]).reset_index(drop=True)
    print(f"pool k{k}: A7 {len(a)} pairs, A8 {len(b)} pairs, identical (pairs + eligible_from): {a.equals(b)}")
EOF
run pool_spreads $PY -u research/regenerate_pool_spread_series.py --pairs $S/purity_pairs_pit_k1_clean.parquet
run squeeze $PY -u research/squeeze_momentum_features.py --pairs-file $S/purity_pairs_pit_k1_clean.parquet
run audit_degenerate $PY -u research/degenerate_column_audit.py --dir output/results/1day --pattern "spread_series_*.parquet" --out $S/degenerate_column_audit_a8.parquet
run audit_contracts $PY -u research/pipeline_contracts.py
seal_gate before_search
for ARM in a5 hlbc; do
  SUF=$([ $ARM = hlbc ] && echo _hlbc); NT=$([ $ARM = hlbc ] && echo 2160 || echo 1728)
  T0=$(date +%s)
  run search_run_$ARM $PY -u research/strategy_search.py run --fresh --arm $ARM
  DT=$(( $(date +%s) - T0 ))
  for p in pit_k1$SUF pit_k2$SUF; do n=$(find $S/strategy_search/$p -maxdepth 1 -name "*.parquet" -newermt "@$T0" | wc -l)
    echo "$(date '+%F %T') $p: $n fresh trade files; run took ${DT}s" >> $L
    [ "$n" -eq 216 ] || { echo "GUARD: expected 216 fresh files in $p -- STOPPED" >> $L; exit 1; }; done
  [ "$DT" -ge 120 ] || { echo "GUARD: 432 backtests in ${DT}s is implausible -- STOPPED" >> $L; exit 1; }
  run search_eval_$ARM $PY -u research/strategy_search.py eval --arm $ARM --n-trials-combined $NT
done
parity end || echo "$(date '+%F %T') note: the cache changed during the chain (reported, not a stop)" >> $L
echo "$(date '+%F %T') A8 chain complete" >> $L
