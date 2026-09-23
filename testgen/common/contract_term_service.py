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

    The identity sits in a unique index, so a key the reduction does not render exactly carries
    a digest of the raw parts and stays distinct from every key that reduces the same way. The
    reduction loses information wherever it collapses a run of disallowed characters, cuts at
    the bound, keeps a ``-`` that then reads as the one joining parts, or drops an absent part
    and shifts the ones after it. The result stays a pure function of the parts.
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
    present = [part for part in parts if part]
    renders_exactly = (
        present == slugged
        and present == list(parts[: len(present)])
        and not any("-" in part for part in slugged)
        and len(joined) <= TERM_ID_MAX_LENGTH
    )
    if renders_exactly:
        return joined

    # Joined on a character no identifier carries, so the digest tells apart the keys the
    # reduction cannot -- including ones differing only in how many parts they have.
    raw_key = "\x00".join(part or "" for part in parts)
    digest = hashlib.sha256(raw_key.encode()).hexdigest()[:_DIGEST_LENGTH]
    kept = joined[: TERM_ID_MAX_LENGTH - _DIGEST_LENGTH - 1].rstrip("-_")
    return f"{kept}-{digest}"
