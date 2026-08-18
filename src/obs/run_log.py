"""
run_log.py — per-stage timing, cost and outcome for every pipeline run.

WHY
The pipeline prints timings to the terminal and then throws them away. A single
6-minute video costs ~175 minutes of CPU across three stages, and one Chatterbox
chunk once took 2260s against a ~110s median — a p99 outlier that scrolled past
and vanished. You cannot tune, budget or regression-test what you don't record.

WHAT IT ISN'T
Not Langfuse/LangSmith. Those trace token-billed API calls; this pipeline has no
paid APIs left — every model runs locally, so the meaningful cost is WALL CLOCK
and the meaningful anomaly is a stall, not a bill. A JSONL file and percentiles
answer the real questions: where does the time go, what's the p95 chunk, did this
change make it slower.

USE
    from src.obs.run_log import stage
    with stage("voice", series="jojo", provider="chatterbox") as s:
        ...
        s.count(chunks=25)

    python -m src.obs.run_log report          # table across all runs
"""
from __future__ import annotations

import json
import platform
import statistics
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

LOG_PATH = Path("data/runs.jsonl")

# Local models are free; the honest cost of this pipeline is time and hardware.
# Kept explicit so the README's "$0.00 per video" is a recorded fact, not a claim.
COST_PER_RUN_USD = 0.0


@dataclass
class StageRecord:
    stage: str
    series: str
    provider: str | None = None
    counts: dict = field(default_factory=dict)
    extra: dict = field(default_factory=dict)
    seconds: float = 0.0
    ok: bool = True
    error: str | None = None
    samples: list[float] = field(default_factory=list)

    def count(self, **kw) -> None:
        """Record item counts, e.g. s.count(chunks=25, words=915)."""
        self.counts.update(kw)

    def sample(self, seconds: float) -> None:
        """Record one unit of work (a chunk, an image) for percentile stats."""
        self.samples.append(seconds)

    def note(self, **kw) -> None:
        self.extra.update(kw)


@contextmanager
def stage(name: str, series: str, provider: str | None = None,
          log_path: Path = LOG_PATH):
    """Time a pipeline stage and append one JSONL record. Records on failure too
    — a stage that crashed after 40 minutes is exactly what you want in the log."""
    rec = StageRecord(stage=name, series=series, provider=provider)
    t0 = time.time()
    try:
        yield rec
    except Exception as e:
        rec.ok = False
        rec.error = f"{type(e).__name__}: {e}"[:300]
        raise
    finally:
        rec.seconds = time.time() - t0
        row = {
            "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "stage": rec.stage,
            "series": rec.series,
            "provider": rec.provider,
            "seconds": round(rec.seconds, 1),
            "ok": rec.ok,
            "error": rec.error,
            "cost_usd": COST_PER_RUN_USD,
            "host": f"{platform.system()}-{platform.machine()}",
            **rec.counts,
            **rec.extra,
        }
        if rec.samples:
            s = sorted(rec.samples)
            row["unit_p50"] = round(statistics.median(s), 1)
            row["unit_p95"] = round(s[max(int(len(s) * 0.95) - 1, 0)], 1)
            row["unit_max"] = round(s[-1], 1)
            row["units"] = len(s)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row) + "\n")


def load(log_path: Path = LOG_PATH) -> list[dict]:
    if not log_path.exists():
        return []
    return [json.loads(l) for l in log_path.read_text(encoding="utf-8").splitlines() if l.strip()]


def report(log_path: Path = LOG_PATH) -> str:
    rows = load(log_path)
    if not rows:
        return "no runs logged yet — run a stage first"

    out = ["", "PER-STAGE", "-" * 78,
           f"{'stage':<10}{'provider':<12}{'runs':>5}{'median':>9}"
           f"{'p95':>9}{'unit p50':>10}{'unit p95':>10}{'unit max':>10}"]
    stages: dict[tuple, list[dict]] = {}
    for r in rows:
        stages.setdefault((r["stage"], r.get("provider") or "-"), []).append(r)
    for (st, pv), rs in sorted(stages.items()):
        secs = sorted(r["seconds"] for r in rs)
        p95 = secs[max(int(len(secs) * 0.95) - 1, 0)]
        up50 = [r["unit_p50"] for r in rs if "unit_p50" in r]
        up95 = [r["unit_p95"] for r in rs if "unit_p95" in r]
        umax = [r["unit_max"] for r in rs if "unit_max" in r]
        out.append(
            f"{st:<10}{pv:<12}{len(rs):>5}"
            f"{statistics.median(secs)/60:>8.1f}m{p95/60:>8.1f}m"
            f"{(f'{statistics.median(up50):.0f}s' if up50 else '-'):>10}"
            f"{(f'{max(up95):.0f}s' if up95 else '-'):>10}"
            f"{(f'{max(umax):.0f}s' if umax else '-'):>10}")

    out += ["", "PER-VIDEO", "-" * 78,
            f"{'series':<20}{'total':>9}{'stages':>8}{'cost':>9}  breakdown"]
    per: dict[str, list[dict]] = {}
    for r in rows:
        per.setdefault(r["series"], []).append(r)
    for series, rs in sorted(per.items()):
        total = sum(r["seconds"] for r in rs)
        cost = sum(r.get("cost_usd", 0.0) for r in rs)
        bd = " + ".join(f"{r['stage']} {r['seconds']/60:.0f}m"
                        for r in sorted(rs, key=lambda x: x["ts"]))
        out.append(f"{series:<20}{total/60:>8.1f}m{len(rs):>8}"
                   f"{'$' + format(cost, '.2f'):>9}  {bd}")

    fails = [r for r in rows if not r["ok"]]
    if fails:
        out += ["", f"FAILURES ({len(fails)})", "-" * 78]
        out += [f"  {r['ts']}  {r['stage']}/{r['series']}: {r['error']}" for r in fails]
    out.append("")
    return "\n".join(out)


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "report":
        print(report())
    else:
        print("Usage: python -m src.obs.run_log report")
