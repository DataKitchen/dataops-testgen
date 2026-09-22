import hashlib
import re

TERM_ID_MAX_LENGTH = 100
_DIGEST_LENGTH = 8

_INVALID = re.compile(r"[^A-Za-z0-9_-]+")
_REPEATS = re.compile(r"_{2,}")


def slugify_term_id(*parts: str | None) -> str:
    """Build a term identity from natural-key parts, matching ``^[A-Za-z0-9_-]+$``.

    Each part is reduced to the allowed character set and the surviving parts are joined with
    ``-``, bounded to ``TERM_ID_MAX_LENGTH``. Raises ``ValueError`` when no part survives.

    A join too long for the bound keeps a digest of the whole join in place of what the cut
    removes: the identity sits in a unique index, and two keys differing only past the cut
    would otherwise collapse onto one string. The result stays a pure function of the parts.
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

    joined = "-".join(slugged)
    if len(joined) > TERM_ID_MAX_LENGTH:
        digest = hashlib.sha256(joined.encode()).hexdigest()[:_DIGEST_LENGTH]
        kept = joined[: TERM_ID_MAX_LENGTH - _DIGEST_LENGTH - 1].rstrip("-_")
        return f"{kept}-{digest}"
    return joined.rstrip("-_")
