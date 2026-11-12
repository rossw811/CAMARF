"""
research/factor_autoencoders.py -- nonlinear (autoencoder) and probabilistic (VAE) factor models with the same
fit(R_window) / common(R) interface as research.factor_residuals.PCAModel (Ross 2026-11-11: "auto encoders, vaes").

PCA is the optimal LINEAR autoencoder, so the comparison PCA vs AE vs VAE, with the residual s-score trading rule held
fixed, isolates what nonlinearity (AE) and a probabilistic latent (VAE) add. Inputs are returns scaled by their
in-window standard deviation, uncentered (same as PCAModel: only the factor part of each mean is removed).
Bottleneck size k defaults to the Marchenko-Pastur count (as PCAModel), so all three use the same number of factors.
Architecture (small on purpose; windows are 252 bars): N -> hidden (tanh) -> k -> hidden (tanh) -> N, Adam, MSE,
early stopping on the last 20% of the window (time-ordered, no shuffling across that split). VAE: encoder gives mean
and log-variance of k latents, loss = N * MSE + beta * KL, common() decodes the posterior MEAN (no sampling noise).
Deterministic given `seed` (tf op determinism). Training belongs on CachyOS for the full universe.
Verify: debug/_verify_factor_autoencoders.py
"""
import os

import numpy as np

os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "2")


def _tf(seed):
    import tensorflow as tf
    tf.keras.utils.set_random_seed(seed)
    try:
        tf.config.experimental.enable_op_determinism()
    except Exception:
        pass
    return tf


class _Base:
    # lr 3e-3 / patience 60 / 500 epochs: with lr 1e-3 / patience 20 the AE stopped after ~90 epochs while still
    # learning a nonlinear factor (f^2 group explained 0.62-0.78 across seeds; 0.89 with these settings) -- verify check 2
    def __init__(self, k=None, hidden=None, epochs=500, seed=0, patience=60, lr=3e-3):
        self.k, self.hidden, self.epochs, self.seed, self.patience, self.lr = k, hidden, epochs, seed, patience, lr

    def _prep(self, R):
        from research.factor_residuals import mp_factor_count
        self.sd = R.std(0, ddof=1)
        self.k_used = self.k if self.k is not None else max(mp_factor_count(R), 1)
        self.h = self.hidden or max(4 * self.k_used, 16)
        Z = (R / self.sd).astype("float32")
        n_val = max(int(0.2 * len(Z)), 1)
        return Z[:-n_val], Z[-n_val:]

    def common(self, R):
        return self._reconstruct((R / self.sd).astype("float32")) * self.sd


class AEModel(_Base):
    def fit(self, R):
        tf = _tf(self.seed)
        L = tf.keras.layers
        Ztr, Zva = self._prep(R)
        N = R.shape[1]
        inp = tf.keras.Input((N,))
        code = L.Dense(self.k_used)(L.Dense(self.h, activation="tanh")(inp))
        out = L.Dense(N)(L.Dense(self.h, activation="tanh")(code))
        self.model = tf.keras.Model(inp, out)
        self.model.compile(tf.keras.optimizers.Adam(self.lr), "mse")
        self.model.fit(Ztr, Ztr, validation_data=(Zva, Zva), epochs=self.epochs, batch_size=32, shuffle=True, verbose=0,
                       callbacks=[tf.keras.callbacks.EarlyStopping(patience=self.patience, restore_best_weights=True)])
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
        x = tf.keras.Input((N,))
        hh = L.Dense(self.h, activation="tanh")(x)
        self.enc = tf.keras.Model(x, [L.Dense(k)(hh), L.Dense(k)(hh)])
        z = tf.keras.Input((k,))
        self.dec = tf.keras.Model(z, L.Dense(N)(L.Dense(self.h, activation="tanh")(z)))
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
        best, best_w, wait = np.inf, None, 0
        for _ in range(self.epochs):
            idx = order.permutation(len(Ztr))
            for i in range(0, len(idx), 32):
                step(tf.constant(Ztr[idx[i:i + 32]]))
            rec, kl = losses(tf.constant(Zva), False)
            v = float(rec + self.beta * kl)
            if v < best - 1e-6:
                best, best_w, wait = v, [p.numpy() for p in params], 0
            else:
                wait += 1
                if wait >= self.patience:
                    break
        for p, w in zip(params, best_w):
            p.assign(w)
        self.kl_val = float(losses(tf.constant(Zva), False)[1])
        return self

    def _reconstruct(self, Z):
        mu, _ = self.enc(Z, training=False)
        return self.dec(mu, training=False).numpy()
