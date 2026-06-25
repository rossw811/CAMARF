"""
CAMARF graph_clustering.py — comparison method, NOT part of the production
pipeline.

Idea #2 from Development.md's Session 10 architecture/academic backlog:
cluster the correlation matrix directly (community detection) instead of
testing pre-filtered pairs independently. The existing pipeline
(analysis.py) tests EVERY pair above MIN_PEARSON_CORR independently via
Engle-Granger + BH-FDR — a pairwise, hypothesis-test-driven discovery
process. This script asks the comparison question Ross requested: does
community detection on the SAME correlation matrix surface the same
structure, and does it surface anything the pairwise screen doesn't
(e.g. other members of a confirmed pair's correlation cluster that were
never tested, or failed FDR, but sit in the same dense community)?

Read-only. Loads cache via UniverseBuilder.build(connect=False,
fetch=False) — never fetches, per CLAUDE.md Rule 1. Reuses
UniverseFilter.run(..., return_matrices=True) so the correlation matrix
is bit-identical to what analysis.py's real pipeline computed, not a
separately-reimplemented version that could silently drift.

Usage:
    python research/graph_clustering.py --tf 1m
    python research/graph_clustering.py --tf 3m --min-corr 0.5
"""
import argparse
import json
import os
import sys

import networkx as nx
import numpy as np
import pandas as pd
from networkx.algorithms.community import louvain_communities, modularity

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from analysis import Config, DataAligner, DataStore, UniverseFilter
from data import UniverseBuilder

# Deliberately NOT output/results/{tf}/ — that tree is glob-scanned by
# other scripts (e.g. ml.py's confirmed-pair discovery) and reserved for
# the production pipeline's actual per-TF output. This is exploratory
# comparison output and stays clearly separate.
_RESEARCH_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "output", "research", "graph_clustering"
)

_SHALLOW_CAP = {"1m": 5_000, "2m": 5_000, "3m": 5_000}


def _build_aligned(universe, tf_label):
    """Mirrors AnalysisPipeline._run_one_tf's Steps 1-2 exactly (data.py/
    analysis.py are never modified by this script — this just replicates
    the same read-only steps to reach the same aligned data)."""
    exclusions = getattr(universe, "exclusion_set", set()) or set()
    tf_data_raw = {}
    for sym, _cls in universe.assets:
        if sym in exclusions:
            continue
        key = f"{sym}_{tf_label}"
        if key not in universe.data or universe.data[key] is None:
            continue
        df = universe.data[key]
        if not DataStore.validate_frequency(sym, tf_label, df):
            continue
        cap = _SHALLOW_CAP.get(tf_label)
        if cap and len(df) > cap:
            df = df.iloc[-cap:]
        tf_data_raw[sym] = df
    if len(tf_data_raw) < 10:
        return None
    return DataAligner.align_universe(
        {f"{sym}_{tf_label}": df for sym, df in tf_data_raw.items()}, tf_label
    )


def _load_confirmed_pairs(tf_label):
    safe = DataStore._TF_SAFE.get(tf_label, tf_label)
    path = os.path.join(Config.DATA.OUTPUT_DIR, "results", safe, "pairs.parquet")
    if not os.path.exists(path):
        return []
    df = pd.read_parquet(path)
    return list(zip(df["symbol_a"], df["symbol_b"]))


def main():
    p = argparse.ArgumentParser(description="Graph-clustering comparison (idea #2)")
    p.add_argument("--tf", default="1m", help="Timeframe label, e.g. 1m, 3m, 15m")
    p.add_argument(
        "--min-corr",
        type=float,
        default=None,
        help="Edge threshold |corr| (default: Config.UNIVERSE.MIN_PEARSON_CORR, "
        "same threshold the existing pairwise screen uses)",
    )
    args = p.parse_args()
    tf_label = args.tf
    min_corr = args.min_corr or Config.UNIVERSE.MIN_PEARSON_CORR

    print(f"Loading universe from cache (connect=False, fetch=False)...")
    builder = UniverseBuilder()
    universe = builder.build(connect=False, fetch=False)
    asset_class_map = {sym: cls for sym, cls in universe.assets}

    print(f"Aligning {tf_label} data...")
    aligned = _build_aligned(universe, tf_label)
    if not aligned:
        print(f"[{tf_label}] insufficient aligned data — abort")
        return

    print(f"Computing correlation matrix (UniverseFilter.run, return_matrices=True)...")
    _, _, _, corr, sym_order = UniverseFilter.run(
        aligned,
        asset_class_map,
        threshold=Config.UNIVERSE.MIN_PEARSON_CORR,
        tf_label=tf_label,
        return_matrices=True,
    )
    n = len(sym_order)
    print(f"[{tf_label}] {n} assets in correlation matrix")

    # Build weighted graph: edge weight = |corr|, same threshold the
    # pairwise screen uses, so this is an apples-to-apples comparison —
    # "given the same correlation bar the existing pipeline applies, what
    # does community structure look like?"
    G = nx.Graph()
    G.add_nodes_from(sym_order)
    abs_corr = np.abs(corr)
    iu = np.triu_indices(n, k=1)
    for i, j, w in zip(iu[0], iu[1], abs_corr[iu]):
        if np.isfinite(w) and w >= min_corr:
            G.add_edge(sym_order[i], sym_order[j], weight=float(w))
    print(f"[{tf_label}] graph: {G.number_of_nodes()} nodes, "
          f"{G.number_of_edges()} edges (|corr| >= {min_corr:.2f})")

    isolated = list(nx.isolates(G))
    G.remove_nodes_from(isolated)
    if G.number_of_nodes() == 0:
        print(f"[{tf_label}] no edges survive the threshold — abort")
        return

    communities = louvain_communities(G, weight="weight", seed=42)
    communities = sorted(communities, key=len, reverse=True)
    mod = modularity(G, communities, weight="weight")
    print(f"[{tf_label}] Louvain: {len(communities)} communities, "
          f"modularity={mod:.3f}, {len(isolated)} isolated nodes excluded")

    sym_to_comm = {}
    for idx, comm in enumerate(communities):
        for sym in comm:
            sym_to_comm[sym] = idx

    confirmed = _load_confirmed_pairs(tf_label)
    print(f"\n[{tf_label}] {len(confirmed)} confirmed pair(s) in pairs.parquet:")
    confirmed_syms = set()
    for a, b in confirmed:
        confirmed_syms.update([a, b])
        ca, cb = sym_to_comm.get(a), sym_to_comm.get(b)
        same = "SAME community" if ca == cb and ca is not None else "DIFFERENT communities (or one excluded)"
        print(f"  {a:<8} {b:<8} -> community {ca} / {cb}  [{same}]")

    print(f"\n[{tf_label}] community membership for confirmed-pair symbols "
          f"(other members = candidates the pairwise+FDR screen never "
          f"confirmed, but graph clustering groups with a known pair):")
    reported_comms = sorted({sym_to_comm[s] for s in confirmed_syms if s in sym_to_comm})
    for c_idx in reported_comms:
        members = sorted(communities[c_idx])
        novel = [m for m in members if m not in confirmed_syms]
        print(f"  community {c_idx} (size {len(members)}): "
              f"confirmed-pair members={sorted(set(members) & confirmed_syms)}")
        print(f"    other members (candidates, untested-or-rejected by pairwise screen): "
              f"{novel[:30]}{'...' if len(novel) > 30 else ''}")

    out = {
        "tf_label": tf_label,
        "n_assets": n,
        "min_corr": min_corr,
        "n_communities": len(communities),
        "modularity": mod,
        "community_sizes": [len(c) for c in communities],
        "confirmed_pairs_same_community": sum(
            1 for a, b in confirmed
            if sym_to_comm.get(a) == sym_to_comm.get(b) and sym_to_comm.get(a) is not None
        ),
        "confirmed_pairs_total": len(confirmed),
    }
    os.makedirs(_RESEARCH_DIR, exist_ok=True)
    out_path = os.path.join(_RESEARCH_DIR, f"{tf_label}_summary.json")
    with open(out_path, "w") as f:
        json.dump(out, f, indent=2)
    print(f"\nSummary written to {out_path}")


if __name__ == "__main__":
    main()
