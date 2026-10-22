"""
SentinelX QA Test Case Decorator and Metadata Engine.

The test code is the single source of truth.
Excel is purely generated output synchronized from code.
"""

from __future__ import annotations

import functools
import re
from dataclasses import dataclass, asdict
from typing import Any, Callable, Literal

# Regex for TestCaseID: 2 to 6 uppercase letters, hyphen, 2 to 4 digits (e.g., AUTH-01, ORG-002)
TC_ID_REGEX = re.compile(r"^[A-Z]{2,6}-\d{2,4}$")
VALID_TC_TYPES = {"automated", "manual", "mocked"}


@dataclass(frozen=True)
class TestCaseMeta:
    """Metadata container for a single SentinelX test case."""
    id: str
    module: str
    description: str
    preconditions: str
    steps: str
    expected: str
    type: Literal["automated", "manual", "mocked"]
    owner: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def parse_natural_key(test_id: str) -> tuple[str, int]:
    """
    Splits a test ID into prefix and integer for natural ordering.
    E.g. 'AUTH-02' -> ('AUTH', 2), 'AUTH-10' -> ('AUTH', 10).
    """
    match = re.match(r"^([A-Z]+)-(\d+)$", test_id.strip())
    if match:
        prefix, num = match.groups()
        return (prefix, int(num))
    return (test_id, 0)


def tc(
    *,
    id: str,
    module: str,
    description: str,
    preconditions: str,
    steps: str,
    expected: str,
    type: Literal["automated", "manual", "mocked"] = "automated",
    owner: str = "Ansh",
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """
    Decorator attaching test case metadata directly to a pytest test function.
    Validates required fields and test case ID formatting at decoration time.
    """
    # 1. Validate ID format
    clean_id = (id or "").strip()
    if not clean_id or not TC_ID_REGEX.match(clean_id):
        raise ValueError(
            f"Invalid TestCaseID '{id}'. Must match pattern 'MODULE-NUMBER' "
            f"(e.g. 'AUTH-01', 'ORG-02', 'ALR-03')."
        )

    # 2. Validate Type
    clean_type = (type or "").strip().lower()
    if clean_type not in VALID_TC_TYPES:
        raise ValueError(
            f"Invalid test type '{type}' for test '{clean_id}'. "
            f"Allowed types: {sorted(VALID_TC_TYPES)}"
        )

    # 3. Validate mandatory fields
    fields = {
        "module": module,
        "description": description,
        "preconditions": preconditions,
        "steps": steps,
        "expected": expected,
        "owner": owner,
    }
    for field_name, val in fields.items():
        if not val or not str(val).strip():
            raise ValueError(
                f"Missing required metadata field '{field_name}' in test case '{clean_id}'."
            )

    meta = TestCaseMeta(
        id=clean_id,
        module=str(module).strip(),
        description=str(description).strip(),
        preconditions=str(preconditions).strip(),
        steps=str(steps).strip(),
        expected=str(expected).strip(),
        type=clean_type,  # type: ignore
        owner=str(owner).strip(),
    )

    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        # Attach directly to function
        setattr(func, "__test_case_meta__", meta)

        # Also add pytest mark so pytest markers can filter if needed
        import pytest
        marked_func = pytest.mark.test_case(meta=meta)(func)

        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            return marked_func(*args, **kwargs)

        # Preserve the metadata on the wrapper as well
        setattr(wrapper, "__test_case_meta__", meta)
        return wrapper

    return decorator
