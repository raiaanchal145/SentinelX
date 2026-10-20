"""AI evaluation harness (tools/ai_eval).

Labelled triage cases are derived from the demo simulator's scenarios
(tools/simulator/scenarios.py -- deterministic by seed): attack
scenarios carry an expected severity band, `benign_noise` is the benign
class. The runner feeds each case through the SAME prompt construction
the production service uses, calls the provider (fake by default --
CI never touches the network), parses the structured output and prints:

  precision, recall, false-positive rate, average estimated cost.

Usage:
    python -m tools.ai_eval                 # fake provider, no network
    python -m tools.ai_eval --provider real # OPENAI_API_KEY required
    python -m tools.ai_eval --demo          # full DB pipeline, fixture alert
"""

from tools.ai_eval.cases import Case, build_cases
from tools.ai_eval.runner import run_eval, run_demo

__all__ = ["Case", "build_cases", "run_eval", "run_demo"]
