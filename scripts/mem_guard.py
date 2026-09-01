#!/usr/bin/env python3
"""
mem_guard.py -- reusable memory-watch wrapper for heavy CAMARF jobs on CachyOS.

WHY: multiple sessions (2026-08-16/17 k-BAHC work, see docs/HANDOFF.md) built an "active
memory-watch monitor" ad hoc, inline, per job -- never as a standing, reusable tool. The
2026-08-23 GPU benchmark crash (N=17,324 correlation-core benchmark, CachyOS went fully
unreachable -- no ping, no port 22) is the direct motivation for making this permanent rather
than re-improvising a monitor every time a new heavy job comes up.

WHAT THIS DOES: launches the given command as a child process, polls system free memory (and,
if the command's argv suggests GPU work, free VRAM) at a short interval via /proc/meminfo and
nvidia-smi, and kills the process tree the moment free memory drops below a configurable floor
-- BEFORE the kernel OOM killer (or a full system lockup, which is what actually happened here)
has to intervene. A clean SIGTERM-then-SIGKILL of one runaway process is always safer than
losing the whole machine.

This is a backstop under systemd-oomd/earlyoom (OS-level, protects against anything not run
through this wrapper), not a replacement for it -- see docs/HARDWARE_OPTIMIZATION_PLAN.md.

Usage:
    python3 scripts/mem_guard.py --min-free-gb 4 --min-vram-free-gb 2 -- <command> [args...]

Exits with the wrapped command's own exit code on clean completion, or 137 (SIGKILL convention)
if the guard had to kill it for a memory-floor breach.
"""
import argparse
import os
import signal
import subprocess
import sys
import time


def _free_mem_gb() -> float:
    """Linux MemAvailable (not MemFree) -- accounts for reclaimable page cache correctly,
    the same distinction CLAUDE.md's own environment notes already rely on."""
    with open("/proc/meminfo") as f:
        for line in f:
            if line.startswith("MemAvailable:"):
                kb = int(line.split()[1])
                return kb / (1024 * 1024)
    raise RuntimeError("MemAvailable not found in /proc/meminfo")


def _free_vram_gb() -> float | None:
    """Returns None (skip check) if nvidia-smi isn't available -- never fail the guard itself
    over a missing/irrelevant GPU check."""
    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.free", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=5,
        )
        if out.returncode != 0:
            return None
        return int(out.stdout.strip().splitlines()[0]) / 1024
    except Exception:
        return None


def _kill_tree(proc: subprocess.Popen):
    """Found live 2026-08-24: killpg(getpgid(proc.pid)) only reaches processes still in the
    SAME process group as `proc`. When the wrapped command spawns ITS OWN children with
    start_new_session=True (run_overnight_research.py does exactly this for its own per-stage
    timeout/tree-kill mechanism -- os.name-branched _popen_kwargs()), those grandchildren land
    in a NEW group and survive this killpg entirely -- confirmed live: mem_guard correctly
    killed run_overnight_research.py on a memory-floor breach, but its orphaned
    episodic_window_size_sweep.py subprocess kept running unsupervised and grew to 14GB+ before
    being caught manually. Two independently-correct tree-kill designs that don't compose when
    nested. Fixed: walk the REAL descendant tree via psutil (works regardless of process-group
    membership) as the primary mechanism, with the killpg call kept as a fast-path/fallback for
    when psutil isn't available."""
    try:
        import psutil
        try:
            parent = psutil.Process(proc.pid)
            descendants = parent.children(recursive=True)
            for child in descendants:
                try:
                    child.terminate()
                except psutil.NoSuchProcess:
                    pass
            _gone, alive = psutil.wait_procs(descendants, timeout=2)
            for child in alive:
                try:
                    child.kill()
                except psutil.NoSuchProcess:
                    pass
        except psutil.NoSuchProcess:
            pass
    except ImportError:
        pass  # fall through to the process-group kill below regardless
    try:
        os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
        time.sleep(2)
        os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
    except ProcessLookupError:
        pass


def _service_is_active(name: str) -> bool:
    out = subprocess.run(["systemctl", "is-active", name], capture_output=True, text=True)
    return out.stdout.strip() == "active"


def _stop_service(name: str) -> bool:
    """Best-effort: returns True if the service was active and this call stopped it (so the
    caller knows to restart it afterward), False if it was already inactive or sudo isn't
    scoped for this -- never raises, since a GPU-sharing service not stopping is exactly the
    condition the VRAM-headroom check in gpu_backend.py exists to catch anyway (belt+suspenders,
    not a hard dependency)."""
    if not _service_is_active(name):
        return False
    print(f"[mem_guard] stopping {name} (currently active, would contend for GPU/RAM)", flush=True)
    r = subprocess.run(["sudo", "-n", "systemctl", "stop", name], capture_output=True, text=True)
    if r.returncode != 0:
        print(f"[mem_guard] WARNING: could not stop {name} ({r.stderr.strip() or 'no sudo scope'}) "
              "-- proceeding anyway, gpu_backend.py's headroom check is the real backstop", flush=True)
        return False
    return True


def main() -> int:
    p = argparse.ArgumentParser(description="Memory-watch guard for heavy CAMARF jobs")
    p.add_argument("--min-free-gb", type=float, default=10.0,
                   help="Kill the job if system free memory (MemAvailable) drops below this. "
                        "Raised from 4.0 to 10.0 (2026-08-23) after 3 unexplained CachyOS "
                        "hangs this session with no hardware fault logged anywhere (non-ECC "
                        "RAM -- EDAC can't monitor it) -- a materially wider safety margin "
                        "since the actual failure mechanism is unconfirmed, not just a tuned "
                        "floor for a known-understood risk.")
    p.add_argument("--min-vram-free-gb", type=float, default=3.0,
                   help="Kill the job if free VRAM drops below this (skipped if no GPU). "
                        "Raised from 1.0 to 3.0, same reasoning as --min-free-gb above.")
    p.add_argument("--poll-seconds", type=float, default=2.0,
                   help="Raised polling frequency from 5.0 -> 2.0 (2026-08-23) for faster "
                        "detection given the unexplained hangs -- a real, present cost "
                        "(more frequent nvidia-smi/meminfo reads) accepted deliberately over "
                        "slower detection.")
    p.add_argument("--stop-gpu-sharers", action="store_true",
                   help="Stop ollama (and any other services in --gpu-sharer-service, repeatable) "
                        "before launching, restart them after -- added 2026-08-23 after ollama's "
                        "own VRAM usage caused a real crash. Off by default: only genuinely CAMARF-"
                        "dedicated runs should touch Ross's other services.")
    p.add_argument("--gpu-sharer-service", action="append", default=["ollama"],
                   help="Service name(s) to stop/restart under --stop-gpu-sharers (default: ollama).")
    p.add_argument("cmd", nargs=argparse.REMAINDER,
                   help="Command to run, preceded by --")
    args = p.parse_args()

    cmd = args.cmd
    if cmd and cmd[0] == "--":
        cmd = cmd[1:]
    if not cmd:
        p.error("no command given (usage: mem_guard.py [opts] -- <command> [args...])")

    stopped_services = []
    if args.stop_gpu_sharers:
        for svc in args.gpu_sharer_service:
            if _stop_service(svc):
                stopped_services.append(svc)

    try:
        return _run_loop(cmd, args)
    finally:
        # Restart anything we stopped, regardless of how the job ended (clean exit, floor
        # breach, Ctrl-C) -- Ross's other work (ollama-backed podcast drafting etc.) should
        # never stay down just because a CAMARF job also ran.
        for svc in stopped_services:
            print(f"[mem_guard] restarting {svc}", flush=True)
            subprocess.run(["sudo", "-n", "systemctl", "start", svc], capture_output=True)


def _run_loop(cmd, args) -> int:
    print(f"[mem_guard] launching: {' '.join(cmd)}", flush=True)
    print(f"[mem_guard] floors: system>={args.min_free_gb}GB free, "
          f"vram>={args.min_vram_free_gb}GB free, poll={args.poll_seconds}s", flush=True)

    proc = subprocess.Popen(cmd, start_new_session=True)

    while True:
        ret = proc.poll()
        if ret is not None:
            print(f"[mem_guard] job exited on its own (code {ret})", flush=True)
            return ret

        free_gb = _free_mem_gb()
        vram_gb = _free_vram_gb()
        vram_str = f", vram_free={vram_gb:.2f}GB" if vram_gb is not None else ""
        print(f"[mem_guard] mem_free={free_gb:.2f}GB{vram_str}", flush=True)

        if free_gb < args.min_free_gb:
            print(f"[mem_guard] FLOOR BREACHED: {free_gb:.2f}GB < {args.min_free_gb}GB -- "
                  "killing job before it takes the machine down", flush=True)
            _kill_tree(proc)
            return 137

        if vram_gb is not None and vram_gb < args.min_vram_free_gb:
            print(f"[mem_guard] VRAM FLOOR BREACHED: {vram_gb:.2f}GB < "
                  f"{args.min_vram_free_gb}GB -- killing job", flush=True)
            _kill_tree(proc)
            return 137

        time.sleep(args.poll_seconds)


if __name__ == "__main__":
    sys.exit(main())
