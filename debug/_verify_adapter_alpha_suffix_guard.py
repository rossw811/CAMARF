"""
Code review R1.14 (confirmed 2026-10-10): research/episodic_pairs_adapter.py --alpha other than the production 0.05
without --out-suffix reused the production resume checkpoint (its resume filter keys on the pair only, so rows built
at a different alpha would be mixed in) and overwrote the production output file. Written failing-first. Checks:
  1. _check_alpha_args(0.01, "") refuses (SystemExit); (0.01, "_alpha01") and (0.05, "") are allowed
  2. main() calls _check_alpha_args before building anything
Run: python debug/_verify_adapter_alpha_suffix_guard.py
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "research"))
PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"[{'PASS' if cond else 'FAIL'}] {name} {detail}")


def main():
    import episodic_pairs_adapter as m
    g = getattr(m, "_check_alpha_args", None)
    check("guard_exists", g is not None)
    if g is not None:
        try:
            g(0.01, ""); check("refuses_alpha_without_suffix", False)
        except SystemExit:
            check("refuses_alpha_without_suffix", True)
        try:
            g(0.01, "_alpha01"); g(0.05, ""); check("allows_valid_combinations", True)
        except SystemExit as e:
            check("allows_valid_combinations", False, str(e))
    src = open(m.__file__, encoding="utf-8").read()
    body = src[src.index("def main():"):]
    check("main_calls_guard", "_check_alpha_args(args.alpha, args.out_suffix)" in body
          and body.index("_check_alpha_args(") < body.index("build_adapter_rows("))
    print(); print(f"{len(PASS)}/{len(PASS) + len(FAIL)} checks passed")
    if FAIL:
        print("FAILED:", FAIL); sys.exit(1)


if __name__ == "__main__":
    main()
