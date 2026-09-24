"""
The simulator CLI: `python -m tools.simulator` (from the repo root,
using the repo's venv -- no new dependencies, stdlib only).

    python -m tools.simulator --list
    python -m tools.simulator --scenario ssh_or_windows_bruteforce --dry-run
    python -m tools.simulator --scenario mixed --api-key sx_...

Arguments: --api-url (default http://localhost:8000), --api-key (an
event-source ingestion key, `sx_<prefix>_<secret>`, from the Event
Sources page), --scenario (a key from scenarios.SCENARIOS), --rate
(events per second, default 2), --duration (seconds to keep sending,
default 0 = send the whole scenario once), --seed (default 42),
--list, --dry-run.

Generation is deterministic per seed; --rate and --duration only pace
or truncate what is SENT. Events go out in batches of at most 250
(half the API's 500 limit) via urllib against POST /api/v1/events;
every batch's 202 accept/reject counts are printed. No dependencies
outside the standard library.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from urllib.parse import urlencode

from tools.simulator.scenarios import SCENARIOS, SCENARIO_DESCRIPTIONS, generate

SEND_BATCH_SIZE = 250


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m tools.simulator",
        description="Send labelled demo events to a SentinelX event source (P07 ingestion API).",
    )
    parser.add_argument("--api-url", default="http://localhost:8000", help="SentinelX backend base URL (default: %(default)s)")
    parser.add_argument("--api-key", default=None, help="Event-source ingestion key (sx_<prefix>_<secret>); required unless --list/--dry-run")
    parser.add_argument("--scenario", default=None, choices=sorted(SCENARIOS), help="Which scenario to run (required unless --list)")
    parser.add_argument("--rate", type=float, default=2.0, help="Events per second to send (default: %(default)s)")
    parser.add_argument("--duration", type=float, default=0.0, help="Seconds to keep sending; 0 sends the whole scenario once (default: %(default)s)")
    parser.add_argument("--seed", type=int, default=42, help="RNG seed -- the same seed reproduces the same events (default: %(default)s)")
    parser.add_argument("--list", action="store_true", help="Print the available scenarios and exit")
    parser.add_argument("--dry-run", action="store_true", help="Print the events instead of sending them")
    return parser


def print_scenarios() -> None:
    print("Available scenarios (python -m tools.simulator --scenario <name>):\n")
    for name in sorted(SCENARIOS):
        print(f"  {name:28s} {SCENARIO_DESCRIPTIONS[name]}")
    print("\nEvery event is tagged {\"sim\": {\"scenario\": <name>}} inside raw. "
          "IPs are documentation/private ranges only; users and hosts are synthetic.")


def _slice_for_duration(events: list[dict], rate: float, duration: float) -> list[dict]:
    """Which events the run sends: the whole scenario, or the first
    ceil(duration * rate) of a repeated sequence when --duration is set."""
    if duration <= 0:
        return events
    wanted = max(1, int(duration * rate + 0.999999))
    if wanted <= len(events):
        return events[:wanted]
    repeats = [events[(i % len(events))] for i in range(wanted)]
    # Re-timestamp repeats so they stay sequential from where the first
    # pass ended -- a replayed identical batch would just deduplicate.
    base = datetime.fromisoformat(events[-1]["timestamp"])
    step = 1.0 / max(rate, 0.001)
    out = []
    for i, event in enumerate(repeats):
        shifted = dict(event)
        shifted["timestamp"] = (base + timedelta(seconds=step * (i - len(events) + 1))).isoformat()
        out.append(shifted)
    return out


def send_batches(api_url: str, api_key: str, events: list[dict], rate: float) -> tuple[int, int]:
    """POST the events in batches, pacing by rate. Returns (accepted, rejected)."""
    endpoint = api_url.rstrip("/") + "/api/v1/events"
    accepted = rejected = 0
    inter_batch_delay = len(range(0, len(events), SEND_BATCH_SIZE)) > 1 and (SEND_BATCH_SIZE / max(rate, 0.001)) or 0.0

    for start in range(0, len(events), SEND_BATCH_SIZE):
        batch = events[start : start + SEND_BATCH_SIZE]
        body = json.dumps({"events": batch}).encode("utf-8")
        request = urllib.request.Request(
            endpoint,
            data=body,
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                payload = json.loads(response.read().decode("utf-8"))
                accepted += payload.get("accepted", 0)
                rejected += payload.get("rejected", 0)
                print(f"  batch {start // SEND_BATCH_SIZE + 1}: sent {len(batch)}, accepted {payload.get('accepted', 0)}, rejected {payload.get('rejected', 0)}")
                warnings = response.headers.get("X-Ingestion-Warning")
                if warnings:
                    print(f"  WARNING from API: {warnings}")
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")[:300]
            print(f"  batch {start // SEND_BATCH_SIZE + 1}: HTTP {exc.code} -- {detail}", file=sys.stderr)
            raise SystemExit(1) from exc
        except urllib.error.URLError as exc:
            print(f"  Could not reach {endpoint}: {exc.reason}", file=sys.stderr)
            raise SystemExit(1) from exc

        if inter_batch_delay and start + SEND_BATCH_SIZE < len(events):
            time.sleep(inter_batch_delay)

    return accepted, rejected


def print_dry_run(events: list[dict]) -> None:
    for i, event in enumerate(events):
        printable = {k: v for k, v in event.items() if not k.startswith("_")}
        print(f"[{i:3d}] {event['timestamp']}  {event['source_type']:12s} {event['event_type']:18s} {event['message'][:80]}")
        if event.get("_leftover_fields"):
            print(f"      unexpected fields dropped: {sorted(event['_leftover_fields'])}")
    print(f"\n{len(events)} events total (dry run -- nothing sent).")
    print(json.dumps(printable, indent=2)[:1200])


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.list:
        print_scenarios()
        return 0

    if not args.scenario:
        parser.error("--scenario is required (or use --list to see the options)")

    events = generate(args.scenario, args.seed, datetime.now(timezone.utc))

    if args.dry_run:
        print_dry_run(events)
        return 0

    if not args.api_key:
        parser.error("--api-key is required to send (get one from the Event Sources page) -- or use --dry-run")

    to_send = _slice_for_duration(events, args.rate, args.duration)
    print(f"Scenario '{args.scenario}' (seed {args.seed}): sending {len(to_send)} of {len(events)} generated events "
          f"to {args.api_url} at {args.rate}/s ...")

    started = time.perf_counter()
    accepted, rejected = send_batches(args.api_url, args.api_key, to_send, args.rate)
    elapsed = time.perf_counter() - started

    print(f"\nDone in {elapsed:.1f}s: accepted {accepted}, rejected {rejected}.")
    print("Watch them appear on the SOC Events page (live refresh) within a few seconds.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
