#!/usr/bin/env python3
"""Rate-limit-friendly batch indexer: runs pi_ingest.py over a file list with
pacing, cooldown, and one automatic retry round for failures.

Usage:
  python3 batch_ingest.py FILE [FILE ...]
  python3 batch_ingest.py --list-from files.txt      # one path per line

Env:
  PI_STORE / PI_BASE / PI_KEY / ... (inherited by pi_ingest.py)
  PI_BATCH_INTERVAL  seconds between docs   (default 75; lower for paid APIs)
  PI_BATCH_COOLDOWN  seconds before retry round (default 300)
  PI_BATCH_LOG       log file              (default $PI_STORE/batch.log)

sha1 dedupe inside pi_ingest.py makes retry rounds safe (no double billing).
"""
try: import _site  # local site defaults (no-op in published pkg)
except ImportError: pass

import os, subprocess, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
PY = sys.executable
INTERVAL = int(os.environ.get("PI_BATCH_INTERVAL", "75"))
COOLDOWN = int(os.environ.get("PI_BATCH_COOLDOWN", "300"))


def main(files):
    log_path = os.environ.get(
        "PI_BATCH_LOG",
        os.path.join(os.environ.get("PI_STORE",
                     os.path.expanduser("~/.pageindex-rag/store")), "batch.log"))
    os.makedirs(os.path.dirname(log_path), exist_ok=True)

    def run(f):
        try:
            r = subprocess.run([PY, os.path.join(HERE, "pi_ingest.py"), f],
                               capture_output=True, text=True, timeout=1800)
            return r.returncode, (r.stdout[-500:] + r.stderr[-250:])
        except Exception as e:
            return -1, f"EXC {e}"

    with open(log_path, "a", encoding="utf-8") as log:
        pending = list(files)
        for rnd in (1, 2):
            if not pending:
                break
            log.write(f"==== round {rnd} {time.strftime('%T')} pending={len(pending)} ====\n")
            log.flush()
            failed = []
            for f in pending:
                code, out = run(f)
                log.write(f"---- {time.strftime('%T')} {os.path.basename(f)} rc={code}\n{out}\n")
                log.flush()
                if code != 0:
                    failed.append(f)
                time.sleep(INTERVAL)
            pending = failed
            if pending and rnd == 1:
                log.write(f"==== cooldown {COOLDOWN}s before retry ====\n")
                log.flush()
                time.sleep(COOLDOWN)
        log.write(f"BATCH DONE {time.strftime('%T')} failed={len(pending)}\n")
        print(f"done, failed={len(pending)}, log={log_path}")


if __name__ == "__main__":
    argv = sys.argv[1:]
    if argv and argv[0] == "--list-from":
        files = [l.strip() for l in open(argv[1], encoding="utf-8") if l.strip()]
    else:
        files = argv
    if not files:
        print(__doc__)
        sys.exit(0)
    main(files)
