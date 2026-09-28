"""
Synthetic check for lineage.py (Ross's seed system, 2026-09-27). Two-stage chain in a temp dir:
  raw.csv --(stage "clean", code clean.py)--> clean.csv --(stage "model", code model.py)--> model.txt
Checks:
  1. fresh project: both stages stale ("never run"); after recording, both up to date;
  2. seeds chain: model's seed changes when clean's seed changes;
  3. editing raw.csv makes clean AND model stale (propagation), with the reason naming the input;
  4. editing model.py makes only model stale; editing params does too;
  5. an output overwritten by something else (clean.csv edited) makes clean stale ("output changed");
  6. history keeps the previous manifest; directory fingerprint changes when a file in it is rewritten.
Run: python debug/_verify_lineage.py
"""
import os
import shutil
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import lineage

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"[{'PASS' if cond else 'FAIL'}] {name} {detail}")


def w(path, text):
    with open(path, "w") as f:
        f.write(text)


def main():
    root = tempfile.mkdtemp(prefix="verify_lineage_")
    try:
        L = lineage.Lineage(root=root, manifest_dir=os.path.join(root, "lineage"))
        for f, t in (("raw.csv", "a,b\n1,2\n"), ("clean.py", "print(1)\n"), ("model.py", "print(2)\n")):
            w(os.path.join(root, f), t)
        clean = L.stage("clean", code=["clean.py"], inputs=["raw.csv"], outputs=["clean.csv"], params={"k": 1})
        model = L.stage("model", code=["model.py"], inputs=["clean"], outputs=["model.txt"], params={"alpha": 0.5})
        s0 = L.status()
        check("fresh_all_stale", not s0["clean"]["up_to_date"] and not s0["model"]["up_to_date"], f"{s0}")
        w(os.path.join(root, "clean.csv"), "a,b\n1,2\n"); clean.record()
        w(os.path.join(root, "model.txt"), "m\n"); model.record()
        s1 = L.status()
        check("after_record_up_to_date", s1["clean"]["up_to_date"] and s1["model"]["up_to_date"], f"{s1}")
        seed_model_1 = s1["model"]["seed"]

        time.sleep(0.01); w(os.path.join(root, "raw.csv"), "a,b\n1,3\n")
        s2 = L.status()
        check("input_change_propagates", not s2["clean"]["up_to_date"] and not s2["model"]["up_to_date"]
              and "raw.csv" in s2["clean"]["reason"], f"clean={s2['clean']['reason']} model={s2['model']['reason']}")
        check("seed_chains", s2["model"]["seed"] != seed_model_1)
        w(os.path.join(root, "clean.csv"), "a,b\n1,3\n"); clean.record(); model.record()

        w(os.path.join(root, "model.py"), "print(3)\n")
        s3 = L.status()
        check("code_change_only_downstream", s3["clean"]["up_to_date"] and not s3["model"]["up_to_date"]
              and "model.py" in s3["model"]["reason"], s3["model"]["reason"])
        model.record()
        model2 = L.stage("model", code=["model.py"], inputs=["clean"], outputs=["model.txt"], params={"alpha": 0.6})
        s4 = L.status()
        check("params_change", not s4["model"]["up_to_date"] and "params" in s4["model"]["reason"], s4["model"]["reason"])
        model2.record()

        w(os.path.join(root, "clean.csv"), "tampered\n")
        s5 = L.status()
        check("output_overwritten_detected", not s5["clean"]["up_to_date"] and "output" in s5["clean"]["reason"],
              s5["clean"]["reason"])
        hist = os.listdir(os.path.join(root, "lineage", "history"))
        check("history_kept", len([h for h in hist if h.startswith("model")]) >= 3, f"{hist}")

        d = os.path.join(root, "cache"); os.makedirs(d)
        w(os.path.join(d, "x.parquet"), "1")
        f1 = lineage.fingerprint(d)
        time.sleep(0.02); w(os.path.join(d, "x.parquet"), "22")
        check("dir_fingerprint_changes", lineage.fingerprint(d) != f1)
    finally:
        shutil.rmtree(root, ignore_errors=True)
    print(); print(f"{len(PASS)}/{len(PASS) + len(FAIL)} checks passed")
    if FAIL:
        print("FAILED:", FAIL); sys.exit(1)


if __name__ == "__main__":
    main()
