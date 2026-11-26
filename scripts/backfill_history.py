"""
One-off backfill: rebuild docs/data/history.json from the organizer repo's git
history, because the live feeds only expose *current* holdings, not past ones.

Usage:
    git clone https://github.com/exofri/ensim-trade-center.git /some/tmp/dir
    python scripts/backfill_history.py /some/tmp/dir

After this, scripts/algorithm.py appends one snapshot per new market tick on
every scheduled run, so the backfill never needs to be run again.
"""
import json, subprocess, sys

from algorithm import TRADER_ID, BASELINE_IDS, HISTORY_PATH

def git(repo, *args, data=None):
    return subprocess.run(["git", "-C", repo, *args], input=data,
                          capture_output=True, check=True).stdout

def main(repo):
    trader_ids = [TRADER_ID] + BASELINE_IDS
    commits = git(repo, "log", "--reverse", "--format=%H %cI",
                  "--", "market/state.json").decode().split()
    commits = list(zip(commits[0::2], commits[1::2]))

    # Read every file in one `git cat-file --batch` call -- hundreds of commits.
    paths = ["market/state.json"] + [f"traders/{t}/holdings.json" for t in trader_ids]
    query = "".join(f"{sha}:{p}\n" for sha, _ in commits for p in paths)
    out = git(repo, "cat-file", "--batch", data=query.encode())

    blobs, i = [], 0
    while i < len(out):
        nl = out.index(b"\n", i)
        header = out[i:nl].decode()
        if header.endswith("missing"):
            blobs.append(None)
            i = nl + 1
            continue
        size = int(header.split()[2])
        blobs.append(json.loads(out[nl + 1: nl + 1 + size]))
        i = nl + 1 + size + 1

    snapshots, seen_t = [], set()
    for k, (sha, ts) in enumerate(commits):
        state, *holdings = blobs[k * len(paths):(k + 1) * len(paths)]
        if state is None or state["t"] in seen_t:
            continue
        seen_t.add(state["t"])
        snapshots.append({
            "t": state["t"],
            "timestamp": ts,
            "prices": {p: round(v, 4) for p, v in state["prices"].items()},
            "holdings": {tid: h for tid, h in zip(trader_ids, holdings) if h is not None},
        })

    with open(HISTORY_PATH, "w") as f:
        json.dump({"trader": TRADER_ID, "baselines": BASELINE_IDS,
                   "snapshots": snapshots}, f, separators=(",", ":"))
    mine = sum(1 for s in snapshots if TRADER_ID in s["holdings"])
    print(f"Wrote {len(snapshots)} snapshots ({mine} include {TRADER_ID}) to {HISTORY_PATH}")

if __name__ == "__main__":
    main(sys.argv[1])
