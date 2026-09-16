import re

TERM_ID_MAX_LENGTH = 100

_INVALID = re.compile(r"[^A-Za-z0-9_-]+")
_REPEATS = re.compile(r"_{2,}")


def slugify_term_id(*parts: str | None) -> str:
    """Build a term identity from natural-key parts, matching ``^[A-Za-z0-9_-]+$``.

    Each part is reduced to the allowed character set and the surviving parts are joined with
    ``-``, bounded to ``TERM_ID_MAX_LENGTH``. Raises ``ValueError`` when no part survives.
    """
    slugged = []
    for part in parts:
        if not part:
            continue
        cleaned = _REPEATS.sub("_", _INVALID.sub("_", part.strip())).strip("_-")
        if cleaned:
            slugged.append(cleaned)

    if not slugged:
        raise ValueError("no part of the natural key survives slugification")

    return "-".join(slugged)[:TERM_ID_MAX_LENGTH].rstrip("-_")
