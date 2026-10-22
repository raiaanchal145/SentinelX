"""
SentinelX New Test Generator CLI.

Usage:
    python new_test.py --module Login --name "Verify remember me"
    python new_test.py --module Alerts --name "Verify alert dedup window" --owner "Riteka Singh"
"""

import argparse
import re
from pathlib import Path

from config import DEFAULT_OWNER, TEAM_MEMBERS, TESTS_DIR
from sync_excel import extract_test_cases_from_code

MODULE_MAP = {
    "auth": ("Auth", "AUTH", "test_auth.py"),
    "login": ("Auth", "AUTH", "test_auth.py"),
    "org": ("Organization", "ORG", "test_org.py"),
    "organization": ("Organization", "ORG", "test_org.py"),
    "rbac": ("RBAC", "RBAC", "test_rbac.py"),
    "log": ("LogIngest", "LOG", "test_log_ingest.py"),
    "logingest": ("LogIngest", "LOG", "test_log_ingest.py"),
    "net": ("Network", "NET", "test_network.py"),
    "network": ("Network", "NET", "test_network.py"),
    "mail": ("EmailAnalysis", "MAIL", "test_mail.py"),
    "email": ("EmailAnalysis", "MAIL", "test_mail.py"),
    "alr": ("Alerts", "ALR", "test_alerts.py"),
    "alert": ("Alerts", "ALR", "test_alerts.py"),
    "alerts": ("Alerts", "ALR", "test_alerts.py"),
    "rem": ("Remedy", "REM", "test_remedy.py"),
    "remedy": ("Remedy", "REM", "test_remedy.py"),
    "tkt": ("Tickets", "TKT", "test_tickets.py"),
    "ticket": ("Tickets", "TKT", "test_tickets.py"),
    "tickets": ("Tickets", "TKT", "test_tickets.py"),
    "dash": ("Dashboard", "DASH", "test_dashboard.py"),
    "dashboard": ("Dashboard", "DASH", "test_dashboard.py"),
    "sec": ("Security", "SEC", "test_security.py"),
    "security": ("Security", "SEC", "test_security.py"),
    "db": ("Database", "DB", "test_db.py"),
    "database": ("Database", "DB", "test_db.py"),
    "det": ("DetectionMetrics", "DET", "test_detection_accuracy.py"),
    "detection": ("DetectionMetrics", "DET", "test_detection_accuracy.py"),
    "sync": ("SyncLogic", "SYNC", "test_excel_sync.py"),
}


def get_next_test_id(prefix: str) -> str:
    """Finds highest number used for this prefix in tests/ and returns prefix + (max+1)."""
    collected = extract_test_cases_from_code(TESTS_DIR)
    numbers = []

    pattern = re.compile(rf"^{prefix}-(\d+)$")
    for tc_id in collected:
        match = pattern.match(tc_id)
        if match:
            numbers.append(int(match.group(1)))

    next_num = max(numbers, default=0) + 1
    return f"{prefix}-{next_num:02d}"


def sanitize_func_name(name: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9_]+", "_", name.lower().strip())
    cleaned = re.sub(r"_+", "_", cleaned).strip("_")
    return cleaned or "new_test"


def generate_test_case(module_arg: str, name_arg: str, owner_arg: str) -> tuple[str, Path]:
    mod_key = module_arg.strip().lower()
    if mod_key in MODULE_MAP:
        module_name, prefix, filename = MODULE_MAP[mod_key]
    else:
        # Default fallback
        module_name = module_arg.capitalize()
        prefix = re.sub(r"[^A-Z]", "", module_name.upper())[:4] or "TEST"
        filename = f"test_{mod_key}.py"

    next_id = get_next_test_id(prefix)
    target_file = TESTS_DIR / filename
    func_name = f"test_{sanitize_func_name(next_id)}_{sanitize_func_name(name_arg)}"

    template = f'''

@tc(
    id="{next_id}",
    module="{module_name}",
    description="{name_arg}",
    preconditions="Prerequisites defined",
    steps="1. Execute action\\n2. Verify outcome",
    expected="Expected outcome achieved",
    type="automated",
    owner="{owner_arg}",
)
def {func_name}():
    # TODO: Implement test assertions
    pass
'''

    if not target_file.exists():
        with open(target_file, "w", encoding="utf-8") as f:
            f.write(f'"""SentinelX QA Test Suite: {module_name}."""\n\nimport pytest\nfrom tc import tc\n')

    with open(target_file, "a", encoding="utf-8") as f:
        f.write(template)

    return next_id, target_file


def main():
    parser = argparse.ArgumentParser(description="Create a new SentinelX test case with auto-assigned ID")
    parser.add_argument("--module", required=True, help="Module name (e.g. Login, Org, Alerts, Tickets)")
    parser.add_argument("--name", required=True, help="Description/name of the test case")
    parser.add_argument("--owner", default=DEFAULT_OWNER, choices=TEAM_MEMBERS, help=f"Test owner (one of {TEAM_MEMBERS})")
    args = parser.parse_args()

    next_id, filepath = generate_test_case(args.module, args.name, args.owner)
    print("\n" + "=" * 60)
    print(f"SUCCESS: Created new test case [{next_id}]")
    print(f"  Description: {args.name}")
    print(f"  Module:      {args.module}")
    print(f"  Owner:       {args.owner}")
    print(f"  Target File: {filepath.relative_to(Path.cwd())}")
    print("=" * 60 + "\n")


if __name__ == "__main__":
    main()
