"""Labelled cases derived from the simulator scenarios.

Each case is one generated scenario snapshot turned into the same
(alert text, events text, asset text) triple the triage service builds
from the database, plus the label a correct triage should produce:

- attack cases: `expect_attack=True` and an expected severity BAND
  (the model may sit one notch inside the band; the metric counts a
  true positive when severity >= band floor and FP likelihood < 0.5);
- `benign_noise`: `expect_attack=False` -- flagging it is a false
  positive, whatever the severity.

Severity bands follow AI SOC Analyst doc §15 (info < low < medium <
high < critical) and the scenario docstrings' own severity hints.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field

from tools.simulator.scenarios import SCENARIOS, generate

SEVERITY_ORDER = {"info": 0, "low": 1, "medium": 2, "high": 3, "critical": 4}

# (scenario, expected band) for attack cases; benign_noise is separate.
ATTACK_CASES: list[tuple[str, str]] = [
    ("ssh_or_windows_bruteforce", "high"),
    ("privilege_escalation", "critical"),
    ("audit_log_cleared", "high"),  # tampering: doc hint says critical; band floor high
    ("suspicious_download", "medium"),
    ("new_user_created", "medium"),  # suspicious account creation + first login
    ("service_installed", "medium"),  # persistence
    ("mixed", "high"),
]

BENIGN_CASES: list[str] = ["benign_noise"]


@dataclass
class Case:
    name: str
    expect_attack: bool
    expected_band: str | None
    alert_text: str
    events_text: str
    asset_text: str
    raw_events: list[dict] = field(default_factory=list)

    @property
    def user_text(self) -> str:
        """What the runner feeds the provider: the same delimited shape
        build_triage_messages produces, minus the system prompt."""
        from app.ai.prompts import build_data_block

        return build_data_block(
            [("Alert", self.alert_text), ("Events", self.events_text), ("Asset", self.asset_text)]
        )


def _synthetic_event_ids(scenario: str, seed: int, count: int) -> list[str]:
    """Deterministic UUIDs for eval events -- the simulator's records
    have no ids (the ingestion API mints them); synthesizing stable ones
    lets the fake provider CITE evidence and the eval exercise the
    grounding check exactly like production."""
    return [
        str(uuid.uuid5(uuid.NAMESPACE_URL, f"sentinelx-eval/{scenario}/{seed}/{i}"))
        for i in range(count)
    ]


def _case_from_scenario(scenario: str, seed: int, expect_attack: bool, band: str | None) -> Case:
    events = generate(scenario, seed)
    ids = _synthetic_event_ids(scenario, seed, len(events))
    event_types = sorted({e["event_type"] for e in events})
    hosts = sorted({(e.get("host") or "n/a") for e in events})
    users = sorted({(e.get("user") or "n/a") for e in events})

    alert_text = "\n".join(
        [
            f"rule: {scenario}",
            "rule severity: high" if expect_attack else "rule severity: low",
            f"event_count: {len(events)}",
            f"event_types: {', '.join(event_types)}",
            f"hosts: {', '.join(hosts)}",
            f"users: {', '.join(users)}",
        ]
    )
    events_text = "\n\n".join(
        "\n".join(
            [
                f"event_id: {ids[i]}",
                f"  timestamp: {e.get('timestamp')}",
                f"  event_type: {e.get('event_type')}",
                f"  host: {e.get('host') or 'n/a'}  user: {e.get('user') or 'n/a'}  ip: {e.get('ip') or 'n/a'}",
                f"  message: {e.get('message', '')}",
            ]
        )
        for i, e in enumerate(events)
    )
    asset_text = f"hostname: {hosts[0] if hosts else 'n/a'}\ntype: server\ncriticality: medium"
    return Case(
        name=f"{scenario}@seed{seed}",
        expect_attack=expect_attack,
        expected_band=band,
        alert_text=alert_text,
        events_text=events_text,
        asset_text=asset_text,
        raw_events=events,
    )


def build_cases(seed: int = 7) -> list[Case]:
    """One case per (scenario, label); `mixed` reuses the composed
    scenario. Deterministic: same seed -> byte-identical cases."""
    cases = [_case_from_scenario(s, seed, True, band) for s, band in ATTACK_CASES]
    cases += [_case_from_scenario(s, seed, False, None) for s in BENIGN_CASES]
    assert set(SCENARIOS) >= {s for s, _ in ATTACK_CASES} | set(BENIGN_CASES)
    return cases
