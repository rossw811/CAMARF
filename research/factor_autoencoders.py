"""
research/factor_autoencoders.py -- nonlinear (autoencoder) and probabilistic (VAE) factor models with the same
fit(R_window) / common(R) interface as research.factor_residuals.PCAModel (Ross 2026-11-11: "auto encoders, vaes").

PCA is the optimal LINEAR autoencoder, so the comparison PCA vs AE vs VAE, with the residual s-score trading rule held
fixed, isolates what nonlinearity (AE) and a probabilistic latent (VAE) add.
Mean handling is IDENTICAL to PCAModel, so only the fluctuation model differs: the network is trained on in-window
DE-MEANED returns (scaled by in-window s.d.), and common() = network(de-meaned) + the factor part of each stock's mean,
i.e. the in-window mean projected on the same k PCA directions PCAModel uses (for PCA itself this split is exact:
P(R) = P(R - mu) + P(mu)). Each stock's idiosyncratic drift therefore stays in its residual.
2026-11-11 (independent review, finding 1): the first version fed uncentered returns to layers with biases, so the output
biases learned every stock's own mean and de-meaned the residuals -- the PCAModel first-draft bug again (s-score corr
with the true deviation 0.414 vs PCA 0.842). debug/_verify_factor_autoencoders.py check 6.
Bottleneck size k defaults to the Marchenko-Pastur count (as PCAModel), so all three use the same number of factors.
Architecture (small on purpose; windows are 252 bars): N -> hidden (tanh) -> k -> hidden (tanh) -> N, Adam, MSE,
early stopping on the last 20% of the window (time-ordered, no shuffling across that split). VAE: encoder gives mean
and log-variance of k latents, loss = N * MSE + beta * KL, common() decodes the posterior MEAN (no sampling noise).
The summed squared error implies an observation variance of 0.5 per standardized return, not the data's noise share,
so beta = 1 is not a calibrated ELBO weight (disclosed; the VAE is used for its reconstruction, not its likelihood).
Deterministic given `seed` (tf op determinism). Training belongs on CachyOS for the full universe.
Verify: debug/_verify_factor_autoencoders.py
"""
import os

import numpy as np

os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "2")


def _tf(seed, use_gpu: bool = False):
    """use_gpu=False (default) hides the GPU from TF. Measured 2026-11-12 on CachyOS (RTX 4080 vs i7-10700K),
    debug/_verify_factor_autoencoders.py: GPU 6m35s, CPU 3m43s -- these small networks (N ~400 inputs, batch 32) are
    launch-overhead bound -- and the CPU run reproduces the Surface's numbers exactly (s-score corr 0.655; GPU 0.672).
    GPU-first rule (CLAUDE.md): GPU only where measured faster."""
    import tensorflow as tf
    if not use_gpu:
        try:
            tf.config.set_visible_devices([], "GPU")
        except (RuntimeError, ValueError):
            pass                        # TF already initialised its devices in this process; leave as is
    tf.keras.utils.set_random_seed(seed)
    try:
        tf.config.experimental.enable_op_determinism()
    except Exception:
        pass
    return tf


class _Base:
    # lr 3e-3 / patience 60 / 500 epochs: with lr 1e-3 / patience 20 the AE stopped after ~90 epochs while still
    # learning a nonlinear factor (f^2 group explained 0.62-0.78 across seeds; 0.89 with these settings) -- verify check 2
    # activation="linear": a linear autoencoder (PCA's capacity) -- the verify test's control separating the cost of
    # nonlinearity from optimization shortfall
    def __init__(self, k=None, hidden=None, epochs=500, seed=0, patience=60, lr=3e-3, activation="tanh"):
        self.k, self.hidden, self.epochs, self.seed, self.patience, self.lr = k, hidden, epochs, seed, patience, lr
        self.activation = activation

    def _prep(self, R):
        from research.factor_residuals import PCAModel, mp_factor_count
        self.mu, self.sd = R.mean(0), R.std(0, ddof=1)
        self.k_used = self.k if self.k is not None else max(mp_factor_count(R), 1)
        self.h = self.hidden or max(4 * self.k_used, 16)
        V = PCAModel(k=self.k_used).fit(R).V
        self.mean_common = ((self.mu / self.sd) @ V @ V.T) * self.sd          # factor part of the mean (as PCAModel)
        Z = ((R - self.mu) / self.sd).astype("float32")
        n_val = max(int(0.2 * len(Z)), 1)
        return Z[:-n_val], Z[-n_val:]

    def common(self, R):
        return self._reconstruct(((R - self.mu) / self.sd).astype("float32")) * self.sd + self.mean_common


class AEModel(_Base):
    def fit(self, R):
        tf = _tf(self.seed)
        L = tf.keras.layers
        Ztr, Zva = self._prep(R)
        N = R.shape[1]

        def build():
            inp = tf.keras.Input((N,))
            code = L.Dense(self.k_used)(L.Dense(self.h, activation=self.activation)(inp))
            m = tf.keras.Model(inp, L.Dense(N)(L.Dense(self.h, activation=self.activation)(code)))
            m.compile(tf.keras.optimizers.Adam(self.lr), "mse")
            return m

        # the split only CHOOSES the epoch count; the model is then refit on the whole window (as PCA uses it), so the
        # window-end bars that set the s-score are not out-of-sample for the AE alone (review follow-up 2026-11-11)
        h = build().fit(Ztr, Ztr, validation_data=(Zva, Zva), epochs=self.epochs, batch_size=32, shuffle=True,
                        verbose=0, callbacks=[tf.keras.callbacks.EarlyStopping(patience=self.patience)])
        self.best_epochs = int(np.argmin(h.history["val_loss"])) + 1
        tf.keras.utils.set_random_seed(self.seed)
        self.model = build()
        Z = np.vstack([Ztr, Zva])
        self.model.fit(Z, Z, epochs=self.best_epochs, batch_size=32, shuffle=True, verbose=0)
        return self

    def _reconstruct(self, Z):
        return self.model(Z, training=False).numpy()


class VAEModel(_Base):
    def __init__(self, beta=1.0, **kw):
        super().__init__(**kw)
        self.beta = beta

    def fit(self, R):
        tf = _tf(self.seed)
        L = tf.keras.layers
        Ztr, Zva = self._prep(R)
        N, k = R.shape[1], self.k_used

        def train(Xtr, Xva, max_epochs):
            """Fresh model trained on Xtr; with Xva, early-stops on it and returns the best epoch count."""
            tf.keras.utils.set_random_seed(self.seed)
            x = tf.keras.Input((N,))
            hh = L.Dense(self.h, activation=self.activation)(x)
            self.enc = tf.keras.Model(x, [L.Dense(k)(hh), L.Dense(k)(hh)])
            z = tf.keras.Input((k,))
            self.dec = tf.keras.Model(z, L.Dense(N)(L.Dense(self.h, activation=self.activation)(z)))
            opt = tf.keras.optimizers.Adam(self.lr)
            params = self.enc.trainable_variables + self.dec.trainable_variables
            rng = tf.random.Generator.from_seed(self.seed)

            def losses(X, sample):
                mu, logv = self.enc(X)
                zz = mu + tf.exp(0.5 * logv) * rng.normal(tf.shape(mu)) if sample else mu
                rec = tf.reduce_mean(tf.reduce_sum(tf.square(X - self.dec(zz)), 1))
                kl = tf.reduce_mean(-0.5 * tf.reduce_sum(1 + logv - tf.square(mu) - tf.exp(logv), 1))
                return rec, kl

            @tf.function
            def step(X):
                with tf.GradientTape() as tape:
                    rec, kl = losses(X, True)
                    loss = rec + self.beta * kl
                opt.apply_gradients(zip(tape.gradient(loss, params), params))

            order = np.random.default_rng(self.seed)
            best, best_ep, wait = np.inf, max_epochs, 0
            for ep in range(1, max_epochs + 1):
                idx = order.permutation(len(Xtr))
                for i in range(0, len(idx), 32):
                    step(tf.constant(Xtr[idx[i:i + 32]]))
                if Xva is None:
                    continue
                rec, kl = losses(tf.constant(Xva), False)
                v = float(rec + self.beta * kl)
                if v < best - 1e-6:
                    best, best_ep, wait = v, ep, 0
                else:
                    wait += 1
                    if wait >= self.patience:
                        break
            self.kl_val = float(losses(tf.constant(Xva if Xva is not None else Xtr), False)[1])
            return best_ep

        # the split only CHOOSES the epoch count; the model is refit on the whole window (as AEModel; see there)
        self.best_epochs = train(Ztr, Zva, self.epochs)
        train(np.vstack([Ztr, Zva]), None, self.best_epochs)
        return self

    def _reconstruct(self, Z):
        mu, _ = self.enc(Z, training=False)
        return self.dec(mu, training=False).numpy()
