"""AI package: provider client, prompts, triage service, fallback.

Everything other agents plug into lives here. The worker's triage job
(app/worker/ai_jobs.py) is the first consumer; the orchestrator/context/
threat/incident/report agents of the AI SOC Analyst doc §11 mount the
same client + service patterns later.
"""
