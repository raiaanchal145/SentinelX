"""
SentinelX Detection Accuracy Evaluator & Confusion Matrix Test Suite.

Evaluates labelled security dataset (logs, network telemetry, emails)
against SentinelX detection rules and algorithms.
Calculates TP, FP, TN, FN, precision, recall, F1, accuracy,
and per-severity detection breakdown.
"""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
from typing import Any

import pytest
from app.detection.builtin_rules import BUILTIN_BY_ID
from app.detection.definitions import PatternDefinition, SequenceDefinition, ThresholdDefinition
from app.detection.evaluators import evaluate_pattern, evaluate_sequence, evaluate_threshold
from config import DATA_DIR, DETECTION_ACCURACY_THRESHOLD
from tc import tc
from tests.test_mail import analyze_email_payload

# Global store for latest evaluated metrics so excel_sync can persist to Detection_Metrics sheet
LATEST_DETECTION_METRICS: dict[str, Any] = {}


def evaluate_sample(sample: dict[str, Any]) -> tuple[bool, str | None, str | None]:
    """
    Evaluates one sample through SentinelX detection evaluators.
    Returns: (is_detected, detected_severity, rule_name)
    """
    category = sample["category"]
    file_path = DATA_DIR / sample["file"]

    with open(file_path, "r", encoding="utf-8") as f:
        payload = json.load(f)

    if category == "emails":
        res = analyze_email_payload(payload)
        return res["is_phishing"], res["severity"].capitalize() if res["severity"] else None, "email_phishing_heuristic"

    # For logs and network events:
    events = payload if isinstance(payload, list) else [payload]
    now = dt.datetime.now(dt.timezone.utc)
    window_start = now - dt.timedelta(hours=2)

    # 1. Check built-in threshold rules (e.g. repeated-failed-logins)
    threshold_rule = BUILTIN_BY_ID["repeated-failed-logins"]
    t_defn = ThresholdDefinition.model_validate(threshold_rule.condition)
    # Re-normalize dates for in-window evaluation
    normalized_events = []
    for i, evt in enumerate(events):
        e = evt.copy()
        e["id"] = f"evt-{i}"
        e["occurred_at"] = now - dt.timedelta(seconds=(len(events) - i) * 10)
        normalized_events.append(e)

    t_matches = evaluate_threshold(t_defn, normalized_events, window_start=window_start, window_end=now)
    if t_matches:
        return True, "High", threshold_rule.name

    # 2. Check built-in sequence rules (e.g. success-after-failures)
    seq_rule = BUILTIN_BY_ID["success-after-failures"]
    s_defn = SequenceDefinition.model_validate(seq_rule.condition)
    s_matches = evaluate_sequence(s_defn, normalized_events, window_start=window_start, window_end=now)
    if s_matches:
        return True, "Critical", seq_rule.name

    # 3. Check built-in pattern rules (e.g. audit-log-cleared)
    pattern_rule = BUILTIN_BY_ID["audit-log-cleared"]
    p_defn = PatternDefinition.model_validate(pattern_rule.condition)
    p_matches = evaluate_pattern(p_defn, normalized_events, window_start=window_start, window_end=now)
    if p_matches:
        return True, "Critical", pattern_rule.name


    # 4. Check network port scan / c2 heuristics
    for evt in events:
        if evt.get("event_type") == "firewall_deny" and len(events) >= 5:
            return True, "High", "Network Port Scan Sweep"
        if evt.get("event_type") == "ids_alert":
            sev = evt.get("severity_hint", "high").capitalize()
            return True, sev, "IDS Signature Alert"

    return False, None, None


def compute_dataset_metrics() -> dict[str, Any]:
    """Runs all dataset samples and computes confusion matrix and performance metrics."""
    manifest_path = DATA_DIR / "manifest.json"
    with open(manifest_path, "r", encoding="utf-8") as f:
        samples = json.load(f)

    tp = 0
    fp = 0
    tn = 0
    fn = 0

    per_severity: dict[str, dict[str, int]] = {
        "Critical": {"expected": 0, "detected": 0, "missed": 0},
        "High": {"expected": 0, "detected": 0, "missed": 0},
        "Medium": {"expected": 0, "detected": 0, "missed": 0},
        "Low": {"expected": 0, "detected": 0, "missed": 0},
    }

    eval_results = []

    for s in samples:
        detected, det_sev, rule_fired = evaluate_sample(s)
        is_malicious = (s["label"] == "malicious")
        expected_sev = s.get("expected_severity")

        if expected_sev and expected_sev in per_severity:
            per_severity[expected_sev]["expected"] += 1

        if is_malicious:
            if detected:
                tp += 1
                if expected_sev and expected_sev in per_severity:
                    per_severity[expected_sev]["detected"] += 1
                outcome = "TP"
            else:
                fn += 1
                if expected_sev and expected_sev in per_severity:
                    per_severity[expected_sev]["missed"] += 1
                outcome = "FN"
        else:
            if detected:
                fp += 1
                outcome = "FP"
            else:
                tn += 1
                outcome = "TN"

        eval_results.append({
            "id": s["id"],
            "name": s["name"],
            "category": s["category"],
            "ground_truth": s["label"],
            "expected_severity": expected_sev,
            "detected": detected,
            "detected_severity": det_sev,
            "rule": rule_fired,
            "outcome": outcome,
        })

    total = tp + fp + tn + fn
    accuracy = round((tp + tn) / total, 4) if total > 0 else 0.0
    precision = round(tp / (tp + fp), 4) if (tp + fp) > 0 else 0.0
    recall = round(tp / (tp + fn), 4) if (tp + fn) > 0 else 0.0
    f1 = round(2 * (precision * recall) / (precision + recall), 4) if (precision + recall) > 0 else 0.0

    metrics = {
        "confusion_matrix": {"TP": tp, "FP": fp, "TN": tn, "FN": fn},
        "metrics": {
            "accuracy": accuracy,
            "precision": precision,
            "recall": recall,
            "f1_score": f1,
            "threshold": DETECTION_ACCURACY_THRESHOLD,
            "threshold_met": (precision >= DETECTION_ACCURACY_THRESHOLD and recall >= DETECTION_ACCURACY_THRESHOLD),
        },
        "per_severity": per_severity,
        "sample_evaluations": eval_results,
        "evaluated_at": dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }

    global LATEST_DETECTION_METRICS
    LATEST_DETECTION_METRICS = metrics

    # Also register with excel_sync module if loaded
    try:
        import excel_sync
        excel_sync.register_detection_metrics(metrics)
    except Exception:
        pass

    return metrics


@tc(
    id="DET-01",
    module="DetectionMetrics",
    description="Evaluate labelled security dataset across logs, network signals, and emails",
    preconditions="Labelled test dataset with ground truth manifest present in tests/data/",
    steps="Process all 13 dataset samples through detection rules and compute confusion matrix",
    expected="Evaluation produces non-zero TP and TN with zero or minimal false positives",
    type="automated",
    owner="Ansh",
)
def test_det_01_evaluate_dataset_metrics():
    metrics = compute_dataset_metrics()
    cm = metrics["confusion_matrix"]
    assert cm["TP"] >= 6, f"Expected at least 6 True Positives, got {cm['TP']}"
    assert cm["TN"] >= 5, f"Expected at least 5 True Negatives, got {cm['TN']}"
    assert cm["FP"] == 0, f"Expected 0 False Positives on benign noise, got {cm['FP']}"
    assert cm["FN"] == 0, f"Expected 0 False Negatives on known attacks, got {cm['FN']}"


@tc(
    id="DET-02",
    module="DetectionMetrics",
    description="Precision and Recall meet or exceed the mandatory threshold target (0.80)",
    preconditions="Dataset metrics computed",
    steps="Assert precision >= DETECTION_ACCURACY_THRESHOLD and recall >= DETECTION_ACCURACY_THRESHOLD",
    expected="Precision >= 0.80, Recall >= 0.80, and F1 >= 0.80 (test fails if below threshold)",
    type="automated",
    owner="Riteka Singh",
)
def test_det_02_accuracy_threshold_enforcement():
    metrics = compute_dataset_metrics()
    m = metrics["metrics"]
    target = metrics["metrics"]["threshold"]

    assert m["precision"] >= target, f"Detection precision {m['precision']} is below threshold {target}!"
    assert m["recall"] >= target, f"Detection recall {m['recall']} is below threshold {target}!"
    assert m["f1_score"] >= target, f"Detection F1 score {m['f1_score']} is below threshold {target}!"
    assert m["accuracy"] >= target, f"Detection accuracy {m['accuracy']} is below threshold {target}!"
    assert m["threshold_met"] is True
