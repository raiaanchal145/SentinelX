import re

# Allow-list validation: instead of trying to block every dangerous
# character one at a time, each field only accepts a fixed, known-safe set
# of characters. Anything outside that set (HTML tags, quotes, semicolons,
# emoji, etc.) is rejected outright.

# Names: letters, spaces, apostrophes and hyphens only (covers names like
# "Anne-Marie" or "O'Brien") -- no digits or symbols.
_NAME_PATTERN = re.compile(r"^[A-Za-z\s'-]+$")

# Emails: the standard practical set of characters allowed in an email
# address (letters, digits, dot, underscore, percent, plus, hyphen before
# the @; letters, digits, dot, hyphen in the domain).
_EMAIL_PATTERN = re.compile(r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$")


def is_valid_name_format(value: str) -> bool:
    return bool(_NAME_PATTERN.match(value))


def is_valid_email_format(value: str) -> bool:
    return bool(_EMAIL_PATTERN.match(value))
