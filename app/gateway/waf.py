import re
from urllib.parse import unquote

MAX_BODY_SIZE = 1 * 1024 * 1024  # 1 MB

SQL_INJECTION_PATTERNS = [
    r"\bunion\s+select\b",
    r"\bor\s+1\s*=\s*1\b",
    r"\bdrop\s+table\b",
    r"\bselect\b.+\bfrom\b",
]

XSS_PATTERNS = [
    r"<\s*script\b",
    r"javascript\s*:",
    r"onerror\s*=",
    r"onload\s*=",
]


def is_suspicious(value: str) -> bool:
    decoded = unquote(value)

    for pattern in SQL_INJECTION_PATTERNS + XSS_PATTERNS:
        if re.search(pattern, decoded, re.IGNORECASE):
            return True

    return False

def is_bad_path(path: str) -> bool:
    decoded = unquote(path)

    return (
        "\x00" in decoded
        or "\\" in decoded
        or any(part == ".." for part in decoded.split("/"))
    )