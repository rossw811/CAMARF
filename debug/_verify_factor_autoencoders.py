"""
Synthetic ground truth for research/factor_autoencoders.py. Comparisons are OUT OF SAMPLE (fit bars 0-749, score
750-999) unless stated. Rewritten 2026-11-11 after the independent review (Development.md, review of the model tests).
  1. linear DGP (3 factors, 100 stocks), 3 seeds: AE and VAE within 0.05 of PCA (the optimal linear model). REPORTED
     alongside: a LINEAR-activation AE (PCA's capacity). If it falls short of PCA by as much as the tanh AE, the gap is
     optimization, not a "cost of nonlinearity" (review finding 4: that cause was asserted, not tested).
  2. nonlinear DGP (1 factor f; 50 stocks load on f, 50 on f^2 - 1), k = 1, scored on BOTH groups (review finding 2:
     scoring only the f^2 group let a rank-1 LINEAR fit to that block pass, and PCA k=1 lands on an arbitrary mix of the
     two near-equal blocks). A rank-1 linear model can explain at most about one block (~0.5-0.6 of the total); the
     AE k = 1 must explain >= 0.8 of the TOTAL and >= 0.7 of EACH group. PCA k=1 and PCA k=2 (the linear model that
     needs 2 factors) reported.
  3. same for the VAE
  4. deterministic: same seed -> identical common()
  5. idiosyncratic drift stays in the residual (review finding 1): 20 stocks with a planted drift of 0.003 / bar -- the
     mean residual of those stocks is >= 0.002 for PCA, AE and VAE alike (first version: AE -0.00001)
  6. s-score tracking (factor_residuals DGP, 100 stocks, rolling 252-bar windows): AE corr with the true OU deviation
     >= PCA corr - 0.1 (first version: AE 0.414 vs PCA 0.842)
Run: python debug/_verify_factor_autoencoders.py   (TensorFlow; ~15 min on the Surface)
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "debug"))
import numpy as np

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"[{'PASS' if cond else 'FAIL'}] {name} {detail}", flush=True)


def explained(model, R_te, C_te, cols):
    """Share of the TRUE common component's variance captured over the given stocks."""
    Ch = model.common(R_te)[:, cols]
    return 1 - np.var(C_te[:, cols] - Ch) / np.var(C_te[:, cols])


def main():
    from research.factor_autoencoders import AEModel, VAEModel
    from research.factor_residuals import PCAModel, rolling_sscores
    T, N = 1000, 100
    allc = np.arange(N)

    res = []
    for seed in (20261111, 1, 2):
        rng = np.random.default_rng(seed)
        F = rng.normal(0, 0.01, (T, 3))
        B = np.column_stack([rng.normal(1, 0.3, N), rng.normal(0, 0.6, N), rng.normal(0, 0.6, N)])
        C = F @ B.T
        R = C + rng.normal(0, 0.006, (T, N))
        res.append({n: explained(m.fit(R[:750]), R[750:], C[750:], allc) for n, m in (
            ("pca", PCAModel(k=3)), ("ae", AEModel(k=3, seed=1)), ("vae", VAEModel(k=3, seed=1)),
            ("ae_linear", AEModel(k=3, seed=1, activation="linear")))})
    gap_ae = [r["pca"] - r["ae"] for r in res]
    gap_vae = [r["pca"] - r["vae"] for r in res]
    gap_lin = [r["pca"] - r["ae_linear"] for r in res]
    check("1 linear DGP: AE/VAE within 0.05 of PCA (3 seeds)", max(gap_ae) <= 0.05 and max(gap_vae) <= 0.05,
          f"PCA - model gap: AE {np.round(gap_ae, 3)} VAE {np.round(gap_vae, 3)} | REPORTED linear AE {np.round(gap_lin, 3)}")

    rng = np.random.default_rng(20261111)
    f = rng.normal(0, 1, T)
    C = np.column_stack([np.outer(f, rng.uniform(0.8, 1.2, 50)), np.outer(f * f - 1, rng.uniform(0.5, 0.8, 50))]) * 0.01
    R = C + rng.normal(0, 0.003, (T, N))
    g1, g2 = np.arange(50), np.arange(50, 100)
    models = {"pca1": PCAModel(k=1), "pca2": PCAModel(k=2), "ae": AEModel(k=1, seed=1), "vae": VAEModel(k=1, seed=1)}
    sc = {}
    for n, m in models.items():
        m.fit(R[:750])
        sc[n] = tuple(explained(m, R[750:], C[750:], c) for c in (allc, g1, g2))
    fmt = lambda t: f"total {t[0]:.3f} f {t[1]:.3f} f^2 {t[2]:.3f}"
    rep = f"| PCA k=1 {fmt(sc['pca1'])} | PCA k=2 {fmt(sc['pca2'])}"
    check("2 AE k=1 captures both groups", sc["ae"][0] >= 0.8 and min(sc["ae"][1:]) >= 0.7, f"AE {fmt(sc['ae'])} {rep}")
    check("3 VAE k=1 captures both groups", sc["vae"][0] >= 0.8 and min(sc["vae"][1:]) >= 0.7, f"VAE {fmt(sc['vae'])}")

    a2 = AEModel(k=1, seed=1).fit(R[:750])
    check("4 deterministic", np.array_equal(models["ae"].common(R[750:]), a2.common(R[750:])))

    rng = np.random.default_rng(5)
    F = rng.normal(0, 0.01, (300, 3))
    B = np.column_stack([rng.normal(1, 0.3, N), rng.normal(0, 0.6, N), rng.normal(0, 0.6, N)])
    drift = np.zeros(N)
    drift[:20] = 0.003
    R = F @ B.T + rng.normal(0, 0.006, (300, N)) + drift
    md = {n: float((R - m.fit(R).common(R))[:, :20].mean()) for n, m in (
        ("pca", PCAModel(k=3)), ("ae", AEModel(k=3, seed=1)), ("vae", VAEModel(k=3, seed=1)))}
    check("5 idiosyncratic drift kept in the residual", min(md.values()) >= 0.002,
          f"mean residual of drift stocks (planted 0.003): {({k: round(v, 5) for k, v in md.items()})}")

    import _verify_factor_residuals as FR
    Rd, _, _, X, sig_eq = FR.make(np.random.default_rng(20261111), T=500, N=N, n_ou=20)

    def track(sc_):
        d = sc_[sc_["symbol"].str[1:].astype(int) < 20]
        true = X[Rd.index.get_indexer(d["date"]), d["symbol"].str[1:].astype(int)] / sig_eq
        ok = np.isfinite(d["s"].to_numpy())
        return float(np.corrcoef(d["s"].to_numpy()[ok], true[ok])[0, 1])
    cp = track(rolling_sscores(Rd, lambda: PCAModel(), window=252, step=42))
    ca = track(rolling_sscores(Rd, lambda: AEModel(seed=1), window=252, step=42))
    check("6 AE s-score tracks the true deviation like PCA", ca >= cp - 0.1, f"corr PCA={cp:.3f} AE={ca:.3f}")

    print(f"\n{len(PASS)}/{len(PASS) + len(FAIL)} checks passed")
    if FAIL:
        print("FAILED:", FAIL)
        sys.exit(1)


if __name__ == "__main__":
    main()
