"""
research/graph_autoencoder.py -- graph autoencoder (GAE) and variational GAE (VGAE) for link prediction
(Kipf & Welling 2016; Ross 2026-11-11: "vaes/gaes").

CAMARF use (comparison arm, not built into discovery): nodes = stocks, edges = pairs related at decision date t
(e.g. pairs admitted by the point-in-time pool), node features = descriptors known at t. The encoder embeds each stock
from its features and its neighbours (2-layer GCN); the decoder scores a pair by sigmoid(z_i . z_j). The question it
answers: can next year's pairs be predicted from this year's graph? Point-in-time is the CALLER's job: the adjacency and
features passed in must use data up to t only, and labels must come from after t.

  A_hat = D^{-1/2} (A + I) D^{-1/2};  H = relu(A_hat X W0);  Z = A_hat H W1  (VGAE: mean and log-std heads)
  loss = weighted BCE over all node pairs (positive weight = #non-edges / #edges, as Kipf & Welling)
         + VGAE: KL(q(Z) || N(0, I)) / N
Dense full-batch: fine to a few thousand nodes (N^2 memory). Deterministic given `seed`.
Baselines (common_neighbours_score, feature_distance_score) must be reported next to every GAE result: on the synthetic
clustered graph common neighbours alone reach AUC 0.943 vs GAE 0.947 (independent review 2026-11-11, finding 3), so the
synthetic test shows the GAE works, NOT that the GCN adds anything over them. Weighting note: pos_w and norm count the
N self-loops among positives (Kipf & Welling's reference code does not); immaterial at these sizes.
Verify: debug/_verify_graph_autoencoder.py
"""
import os

import numpy as np

os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "2")


def normalize_adj(A: np.ndarray) -> np.ndarray:
    A = A + np.eye(len(A))
    d = 1.0 / np.sqrt(A.sum(1))
    return (A * d[:, None]) * d[None, :]


class GraphAutoencoder:
    def __init__(self, hidden=32, dim=16, variational=False, epochs=300, lr=0.01, seed=0):
        self.hidden, self.dim, self.variational, self.epochs, self.lr, self.seed = hidden, dim, variational, epochs, lr, seed

    def fit(self, A: np.ndarray, X: np.ndarray):
        from research.factor_autoencoders import _tf
        tf = _tf(self.seed)
        A = np.asarray(A, float)
        assert np.allclose(A, A.T) and np.all(np.diag(A) == 0), "A must be symmetric with an empty diagonal"
        N = len(A)
        Ah = tf.constant(normalize_adj(A), tf.float32)
        Xt = tf.constant(X, tf.float32)
        target = tf.constant(A + np.eye(N), tf.float32)        # Kipf & Welling reconstruct A + I
        n_pos = float(target.numpy().sum())
        pos_w = (N * N - n_pos) / n_pos
        norm = N * N / (2.0 * (N * N - n_pos))
        init = tf.keras.initializers.GlorotUniform(seed=self.seed)
        self.W0 = tf.Variable(init((X.shape[1], self.hidden)))
        self.Wm = tf.Variable(init((self.hidden, self.dim)))
        self.Ws = tf.Variable(init((self.hidden, self.dim))) if self.variational else None
        params = [v for v in (self.W0, self.Wm, self.Ws) if v is not None]
        opt = tf.keras.optimizers.Adam(self.lr)
        rng = tf.random.Generator.from_seed(self.seed)

        @tf.function
        def step():
            with tf.GradientTape() as tape:
                H = tf.nn.relu(Ah @ Xt @ self.W0)
                mu = Ah @ H @ self.Wm
                if self.variational:
                    logs = Ah @ H @ self.Ws
                    Z = mu + rng.normal(tf.shape(mu)) * tf.exp(logs)
                else:
                    Z = mu
                logits = Z @ tf.transpose(Z)
                loss = norm * tf.reduce_mean(tf.nn.weighted_cross_entropy_with_logits(target, logits, pos_w))
                if self.variational:
                    kl = -0.5 / N * tf.reduce_mean(tf.reduce_sum(1 + 2 * logs - tf.square(mu) - tf.exp(2 * logs), 1))
                    loss = loss + kl
            opt.apply_gradients(zip(tape.gradient(loss, params), params))
            return loss

        for _ in range(self.epochs):
            self.final_loss = float(step())
        H = tf.nn.relu(Ah @ Xt @ self.W0)
        self.Z = (Ah @ H @ self.Wm).numpy()                    # embedding = posterior mean for VGAE
        return self

    def score(self, pairs) -> np.ndarray:
        """Link probability for each (i, j) row of `pairs`."""
        p = np.asarray(pairs)
        return 1.0 / (1.0 + np.exp(-np.einsum("ij,ij->i", self.Z[p[:, 0]], self.Z[p[:, 1]])))


def common_neighbours_score(A: np.ndarray, pairs) -> np.ndarray:
    """Baseline: number of shared neighbours of (i, j) in the training graph."""
    p = np.asarray(pairs)
    return np.einsum("ij,ij->i", A[p[:, 0]], A[p[:, 1]]).astype(float)


def feature_distance_score(X: np.ndarray, pairs) -> np.ndarray:
    """Baseline: negative Euclidean distance between the two nodes' standardized features."""
    Z = (X - X.mean(0)) / X.std(0)
    p = np.asarray(pairs)
    return -np.linalg.norm(Z[p[:, 0]] - Z[p[:, 1]], axis=1)


def split_edges(A: np.ndarray, test_frac: float, rng):
    """Hold out `test_frac` of edges and an equal number of non-edges; returns the training adjacency (held-out edges
    REMOVED, so the model never sees them) and the test pairs/labels."""
    iu = np.triu_indices(len(A), 1)
    pos = np.column_stack(iu)[A[iu] > 0]
    neg = np.column_stack(iu)[A[iu] == 0]
    pt = pos[rng.permutation(len(pos))[: int(test_frac * len(pos))]]
    nt = neg[rng.permutation(len(neg))[: len(pt)]]
    A_tr = A.copy()
    A_tr[pt[:, 0], pt[:, 1]] = A_tr[pt[:, 1], pt[:, 0]] = 0
    return A_tr, np.vstack([pt, nt]), np.r_[np.ones(len(pt)), np.zeros(len(nt))]
