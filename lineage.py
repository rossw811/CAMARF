"""
lineage.py -- seed/lineage tracking for scripts that depend on each other (Ross's idea, 2026-09-27; design in
Development.md, "Seed/lineage system for dependent scripts").

Each stage declares its code files, params, inputs (upstream stage names or paths) and outputs (paths). Its SEED is a
hash of the upstream stages' seeds, the input paths' fingerprints, its code files' hashes and its params -- so a seed
changes exactly when anything upstream of it changes. After a successful run, `stage.record()` writes
output/lineage/<stage>.json (seed, the parts of the seed, output fingerprints, git commit, time); the previous
manifest is kept in output/lineage/history/.

A stage is UP TO DATE when its recorded seed equals the seed recomputed now AND its outputs still have the recorded
fingerprints (catches an output rewritten by another script). Anything else is stale, and so is everything downstream.
Nothing is skipped automatically: a script decides (`if st.up_to_date and not args.force: ...`).

Fingerprints: sha256 of a file's content; for a directory, sha256 of its sorted (relative path, size, mtime_ns)
listing -- cheap for the 44k-file WRDS cache, and any rewrite changes mtime (a same-size, same-mtime edit would be
missed; stated, not hidden). "_"-prefixed subdirectories (backups/staging by project convention) are excluded.

Usage in a script:
    from lineage import Lineage
    st = Lineage().stage("episodic_scan", code=[__file__, "analysis.py"], params=vars(args),
                         inputs=["output/cache/wrds"], outputs=["output/research/episodic_windows.parquet"])
    ...run...
    st.record()
CLI: python lineage.py status | python lineage.py diff <stage>
"""
import hashlib
import json
import os
import subprocess
import sys
import time
from typing import Dict, List, Optional

_ROOT = os.path.dirname(os.path.abspath(__file__))


def _sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def fingerprint(path: str) -> str:
    """Content hash of a file; listing hash of a directory; 'missing' if absent."""
    if os.path.isfile(path):
        h = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                h.update(chunk)
        return "f:" + h.hexdigest()
    if os.path.isdir(path):
        rows = []
        for dp, dn, fn in os.walk(path):
            # project convention: "_"-prefixed subdirectories are backups/staging (e.g. _backup_d17_20260927),
            # not data -- excluded so making a backup does not mark the whole cache as changed
            dn[:] = [d for d in dn if not d.startswith("_")]
            for n in fn:
                p = os.path.join(dp, n)
                try:
                    st = os.stat(p)
                except OSError:
                    continue
                rows.append(f"{os.path.relpath(p, path)}|{st.st_size}|{st.st_mtime_ns}")
        rows.sort()
        return "d:" + _sha("\n".join(rows).encode())
    return "missing"


def _git_commit(root: str) -> str:
    try:
        return subprocess.run(["git", "-C", root, "rev-parse", "--short", "HEAD"], capture_output=True, text=True,
                              timeout=10).stdout.strip()
    except Exception:
        return ""


class Stage:
    def __init__(self, lin: "Lineage", name: str, code: List[str], inputs: List[str], outputs: List[str],
                 params: Optional[dict]):
        self.lin, self.name, self.code, self.inputs, self.outputs = lin, name, list(code), list(inputs), list(outputs)
        self.params = json.loads(json.dumps(params or {}, sort_keys=True, default=str))
        lin._stages[name] = self

    def _abs(self, p: str) -> str:
        return p if os.path.isabs(p) else os.path.join(self.lin.root, p)

    def parts(self) -> dict:
        """Everything the seed is made of, computed now."""
        ups, paths = {}, {}
        for i in self.inputs:
            if i in self.lin._stages:
                ups[i] = self.lin._stages[i].seed()
            else:
                paths[i] = self.lin._fp(self._abs(i))
        code = {c: self.lin._fp(self._abs(c)) for c in self.code}
        return {"upstream": ups, "inputs": paths, "code": code, "params": self.params}

    def seed(self) -> str:
        if self.name not in self.lin._seed_cache:
            self.lin._seed_cache[self.name] = _sha(json.dumps(self.parts(), sort_keys=True).encode())
        return self.lin._seed_cache[self.name]

    def manifest(self) -> Optional[dict]:
        p = os.path.join(self.lin.manifest_dir, f"{self.name}.json")
        if not os.path.exists(p):
            return None
        with open(p, encoding="utf-8") as f:
            return json.load(f)

    def status(self) -> dict:
        self.lin._clear_if_top()
        m, now = self.manifest(), self.parts()
        seed = _sha(json.dumps(now, sort_keys=True).encode())
        if m is None:
            return {"up_to_date": False, "seed": seed, "reason": "never run"}
        reasons = []
        old = m.get("parts", {})
        for k in ("upstream", "inputs", "code"):
            for name, v in now[k].items():
                if old.get(k, {}).get(name) != v:
                    reasons.append(f"{k} changed: {name}")
            for name in set(old.get(k, {})) - set(now[k]):
                reasons.append(f"{k} removed: {name}")
        if old.get("params") != now["params"]:
            reasons.append("params changed")
        for o, fp in m.get("outputs", {}).items():
            if self.lin._fp(self._abs(o)) != fp:
                reasons.append(f"output changed since recorded: {o}")
        for u in self.inputs:
            if u in self.lin._stages:
                self.lin._depth += 1
                try:
                    stale = not self.lin._stages[u].status()["up_to_date"]
                finally:
                    self.lin._depth -= 1
                if stale:
                    reasons.append(f"upstream stale: {u}")
        return {"up_to_date": not reasons, "seed": seed, "recorded_seed": m.get("seed"), "reason": "; ".join(reasons)}

    @property
    def up_to_date(self) -> bool:
        return self.status()["up_to_date"]

    def record(self) -> dict:
        """Call after a successful run: writes the manifest (previous one moved to history/)."""
        self.lin._fp_cache.clear(); self.lin._seed_cache.clear()  # outputs were just written -- fingerprint afresh
        os.makedirs(os.path.join(self.lin.manifest_dir, "history"), exist_ok=True)
        p = os.path.join(self.lin.manifest_dir, f"{self.name}.json")
        if os.path.exists(p):
            old = self.manifest() or {}
            stamp = str(old.get("recorded_at_ns", time.time_ns()))
            os.replace(p, os.path.join(self.lin.manifest_dir, "history", f"{self.name}.{stamp}.json"))
        parts = self.parts()
        m = {"stage": self.name, "seed": _sha(json.dumps(parts, sort_keys=True).encode()), "parts": parts,
             "outputs": {o: fingerprint(self._abs(o)) for o in self.outputs}, "git_commit": _git_commit(self.lin.root),
             "recorded_at": time.strftime("%Y-%m-%d %H:%M:%S"), "recorded_at_ns": time.time_ns()}
        with open(p + ".tmp", "w", encoding="utf-8") as f:
            json.dump(m, f, indent=1, sort_keys=True)
        os.replace(p + ".tmp", p)
        return m


class Lineage:
    def __init__(self, root: str = _ROOT, manifest_dir: Optional[str] = None):
        self.root = root
        self.manifest_dir = manifest_dir or os.path.join(root, "output", "lineage")
        self._stages: Dict[str, Stage] = {}
        # memo for ONE status/record call (a DAG shares inputs; recomputing each directory fingerprint per downstream
        # stage took minutes); cleared at the start of every top-level call so results are never stale
        self._fp_cache: Dict[str, str] = {}
        self._seed_cache: Dict[str, str] = {}
        self._depth = 0

    def _fp(self, path: str) -> str:
        if path not in self._fp_cache:
            self._fp_cache[path] = fingerprint(path)
        return self._fp_cache[path]

    def _clear_if_top(self) -> None:
        if self._depth == 0:
            self._fp_cache.clear(); self._seed_cache.clear()

    def stage(self, name: str, code: List[str], inputs: List[str] = (), outputs: List[str] = (),
              params: Optional[dict] = None) -> Stage:
        return Stage(self, name, code, list(inputs), list(outputs), params)

    def status(self) -> Dict[str, dict]:
        self._fp_cache.clear(); self._seed_cache.clear()
        self._depth += 1  # keep one memo across the whole DAG pass
        try:
            return {n: s.status() for n, s in self._stages.items()}
        finally:
            self._depth -= 1


def _load_recorded(lin: Lineage) -> None:
    """Rebuild stages from recorded manifests (for the CLI, which has no script context)."""
    if not os.path.isdir(lin.manifest_dir):
        return
    for f in sorted(os.listdir(lin.manifest_dir)):
        if f.endswith(".json"):
            with open(os.path.join(lin.manifest_dir, f), encoding="utf-8") as fh:
                m = json.load(fh)
            p = m["parts"]
            lin.stage(m["stage"], code=list(p["code"]), inputs=list(p["upstream"]) + list(p["inputs"]),
                      outputs=list(m["outputs"]), params=p["params"])


def main(argv: List[str]) -> None:
    lin = Lineage()
    _load_recorded(lin)
    if not argv or argv[0] == "status":
        for n, s in lin.status().items():
            print(f"{'OK   ' if s['up_to_date'] else 'STALE'}  {n:40s} {s['reason']}")
    elif argv[0] == "diff" and len(argv) > 1:
        st = lin._stages.get(argv[1])
        if st is None:
            print(f"no recorded stage {argv[1]!r}"); return
        m, now = st.manifest(), st.parts()
        print(json.dumps({"recorded": m["parts"], "now": now}, indent=1, sort_keys=True))
    else:
        print(__doc__)


if __name__ == "__main__":
    main(sys.argv[1:])
