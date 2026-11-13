# Mutant harness for debug/_verify_p2_placebo_power.py: each mutant of research/p2_placebo_power.py must FAIL the test.
import os, subprocess, sys, tempfile
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
src = open(os.path.join(ROOT, "research", "p2_placebo_power.py"), encoding="utf-8").read()
test = open(os.path.join(ROOT, "debug", "_verify_p2_placebo_power.py"), encoding="utf-8").read()
MUT = {
    "state without phi": ("zi=[ph * u[s - 1]]", "zi=[u[s - 1]]"),
    "data after year y used": ("    j = j[j.index.year <= year]\n", ""),
    "own null kept in others": ("others = nulls.drop(index=(r.symbol_a, r.symbol_b)).to_numpy()", "others = nulls.to_numpy()"),
}
bad = 0
for name, (old, new) in MUT.items():
    assert src.count(old) == 1, name
    with tempfile.TemporaryDirectory() as d:
        os.makedirs(os.path.join(d, "debug")); os.makedirs(os.path.join(d, "research"))
        open(os.path.join(d, "research", "p2_placebo_power.py"), "w", encoding="utf-8").write(src.replace(old, new))
        # the test inserts ROOT and ROOT/research; put the mutant dir first, the real repo after it for other imports
        t = test.replace('sys.path.insert(0, os.path.join(ROOT, "research"))',
                         f'sys.path.insert(0, os.path.join(ROOT, "research")); sys.path.insert(0, r"{os.path.join(ROOT, "research")}");'
                         f' sys.path.insert(0, r"{ROOT}"); sys.path.insert(0, os.path.join(r"{d}", "research"))')
        p = os.path.join(d, "debug", "t.py"); open(p, "w", encoding="utf-8").write(t)
        r = subprocess.run([sys.executable, p], capture_output=True, text=True, encoding="utf-8")
        fails = [l for l in r.stdout.splitlines() if l.startswith("[FAIL]")]
        print(f"{name}: exit {r.returncode}; {len(fails)} failing: {[f[:60] for f in fails]}")
        bad += r.returncode == 0
print("ALL MUTANTS CAUGHT" if bad == 0 else f"{bad} mutant(s) survived")
