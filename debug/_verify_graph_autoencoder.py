"""
Synthetic ground truth for research/graph_autoencoder.py. 200 nodes with latent 2-D positions in 4 clusters; edge
probability falls with latent distance; node features = noisy positions + 6 junk dimensions.
  1. split_edges removes every held-out edge from the training graph (no leakage) and balances the test set
  2. GAE recovers held-out edges: AUC > 0.85 and within 0.03 of the best simple baseline (common neighbours, feature
     distance). Independent review 2026-11-11 (finding 3): common neighbours alone reach 0.943 here, so this checks that
     the GAE works -- it does not show the GCN adds anything; the real-data stage must report against the baselines.
  3. VGAE: same
  4. null: a uniformly random graph with the same edge count and pure-noise features gives AUC ~0.5
     (|AUC - 0.5| < 0.1) -- the model does not manufacture links
  5. deterministic: same seed -> identical scores
Run: python debug/_verify_graph_autoencoder.py
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import numpy as np
from sklearn.metrics import roc_auc_score

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"[{'PASS' if cond else 'FAIL'}] {name} {detail}")


def make(rng, N=200):
    centers = np.array([[0, 0], [4, 0], [0, 4], [4, 4]], float)
    pos = centers[rng.integers(0, 4, N)] + rng.normal(0, 0.8, (N, 2))
    D2 = ((pos[:, None] - pos[None]) ** 2).sum(-1)
    P = 1 / (1 + np.exp(-(1.5 - 1.2 * D2)))
    U = np.triu(rng.uniform(size=(N, N)) < P, 1).astype(float)
    A = U + U.T
    X = np.column_stack([pos + rng.normal(0, 0.5, (N, 2)), rng.normal(0, 1, (N, 6))])
    return A, X


def main():
    from research.graph_autoencoder import GraphAutoencoder, split_edges
    rng = np.random.default_rng(20261111)
    A, X = make(rng)
    A_tr, pairs, y = split_edges(A, 0.15, rng)
    leaked = int(A_tr[pairs[y == 1, 0], pairs[y == 1, 1]].sum())
    check("1 split: no leakage, balanced", leaked == 0 and y.sum() == (1 - y).sum() and np.allclose(A_tr, A_tr.T),
          f"held-out edges={int(y.sum())} still in train graph={leaked} (edges total={int(A.sum() / 2)})")

    from research.graph_autoencoder import common_neighbours_score, feature_distance_score
    cn = roc_auc_score(y, common_neighbours_score(A_tr, pairs))
    fd = roc_auc_score(y, feature_distance_score(X, pairs))
    best = max(cn, fd)
    g = GraphAutoencoder(seed=1).fit(A_tr, X)
    auc = roc_auc_score(y, g.score(pairs))
    check("2 GAE held-out AUC matches the best baseline", auc > 0.85 and auc >= best - 0.03,
          f"AUC={auc:.3f}; baselines: common neighbours {cn:.3f}, feature distance {fd:.3f} "
          f"(the synthetic graph does NOT show the GCN adds value over them)")
    v = GraphAutoencoder(variational=True, seed=1).fit(A_tr, X)
    aucv = roc_auc_score(y, v.score(pairs))
    check("3 VGAE held-out AUC matches the best baseline", aucv > 0.85 and aucv >= best - 0.03, f"AUC={aucv:.3f}")

    # null: same edge count, wired uniformly at random (no clusters), features pure noise
    iu = np.triu_indices(len(A), 1)
    R = np.zeros_like(A)
    pick = rng.permutation(len(iu[0]))[: int(A.sum() / 2)]
    R[iu[0][pick], iu[1][pick]] = 1
    R = R + R.T
    A0, pairs0, y0 = split_edges(R, 0.15, rng)
    n0 = GraphAutoencoder(seed=1).fit(A0, rng.normal(0, 1, X.shape))
    auc0 = roc_auc_score(y0, n0.score(pairs0))
    check("4 null graph AUC ~ 0.5", abs(auc0 - 0.5) < 0.1, f"AUC={auc0:.3f}")

    g2 = GraphAutoencoder(seed=1).fit(A_tr, X)
    check("5 deterministic", np.array_equal(g.score(pairs), g2.score(pairs)))

    print(f"\n{len(PASS)}/{len(PASS) + len(FAIL)} checks passed")
    if FAIL:
        print("FAILED:", FAIL)
        sys.exit(1)


if __name__ == "__main__":
    main()
