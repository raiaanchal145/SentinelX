"""Detection engine (P23, docs/API_CONTRACT.md "Detection rules").

Rules are data (validated JSON definitions, app/detection/definitions);
evaluators are pure functions (app/detection/evaluators); sliding
window state lives in Redis with an in-memory fallback
(app/detection/state). The worker evaluates every newly stored event
batch at the end of process_events and writes RuleHit rows.
"""
