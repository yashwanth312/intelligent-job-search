"""ATS-safe normalization of generated resume content.

Applicant tracking systems read the PDF *text layer*, not the rendered page.
Two classes of defect were measured across 619 generated resumes in output/:

1. Characters the text layer carries badly. `<1s answer latency` appeared in
   145/619 resumes; several parsers treat `<...>` as markup and drop the run.
   Arrows, middle dots, em/en dashes and curly quotes appeared throughout.

2. Skill strings Workday cannot match against its skill taxonomy. Workday
   splits a skills line on commas and matches each token individually, so
   `AWS (EC2, S3, Cognito)` becomes the tokens `AWS (EC2`, `S3`, `Cognito)` --
   none of which match anything, so the Skills field comes back empty.
   600/619 resumes had a comma inside parentheses in the skills block.

Both are fixed here, at render time. profile.yaml is the source of most of
these strings and is deliberately left untouched.
"""
from __future__ import annotations

import logging
import re
import unicodedata

logger = logging.getLogger(__name__)

# Structural bullet glyph prefixed to each bullet line by the renderer. It is
# exempt from the ASCII purge: every major parser recognises U+2022 as a list
# marker, and an attached marker segments bullets far better than none at all.
# Swap to "-" here if a pure-ASCII text layer is ever required.
BULLET_CHAR = "•"

# Cap expansion so `AWS (EC2, S3, Lambda, EKS, CloudFormation, VPC, GuardDuty,
# WAF, Cognito)` does not turn one skill into ten and blow out the line.
MAX_CHILDREN_PER_ITEM = 5
MAX_ITEMS_PER_CATEGORY = 12


# ─────────────────────────────────────────────────────────────────────────────
# Character sanitization
# ─────────────────────────────────────────────────────────────────────────────

_UNICODE_MAP = {
    "—": "-",   # em dash   -- 9,476 occurrences across the survey
    "–": "-",   # en dash   -- date ranges: "June 2024 - Present"
    "‒": "-", "‐": "-", "‑": "-", "−": "-",
    "→": " to ",    # →
    "↔": " to ",    # ↔
    "←": " from ",  # ←
    "·": ", ",  # ·  used as a skill delimiter Workday won't split on
    "•": ", ",  # •  only reachable if the model emits one mid-content
    "‘": "'", "’": "'", "‚": "'", "′": "'",
    "“": '"', "”": '"', "„": '"', "″": '"',
    "…": "...",
    " ": " ", " ": " ", " ": " ", " ": " ", "​": "",
    "✓": "", "✔": "", "✗": "", "✘": "",
    "×": "x",
    "™": "", "®": "", "©": "",
    "≠": " not equal to ",
}
_TRANSLATION = str.maketrans(_UNICODE_MAP)

_GE = re.compile(r"≥\s*")
_LE = re.compile(r"≤\s*")
# Only rewrite angle brackets that read as comparisons ("<1s", ">50%"); any
# survivor is stripped rather than left to look like a markup tag.
_LT_NUM = re.compile(r"<\s*(?=[\d$.])")
_GT_NUM = re.compile(r">\s*(?=[\d$.])")
_STRAY_ANGLE = re.compile(r"[<>]")
# Only a free-standing ampersand becomes "and" -- this must not touch
# "MITRE ATT&CK" or "R&D", which are single tokens in the profile.
_SPACED_AMP = re.compile(r"\s+&\s+")
_MULTISPACE = re.compile(r"[ \t]{2,}")
# Delimiter substitutions leave a gap before the comma ("Redis · SQLite" ->
# "Redis , SQLite"); close it so tokens split cleanly on ", ".
_SPACE_BEFORE_PUNCT = re.compile(r"\s+([,;])")


def sanitize_text(text: str, *, preserve_ampersand: bool = False) -> str:
    """Return `text` reduced to characters an ATS text layer handles cleanly.

    `preserve_ampersand` keeps a spaced `&` intact. It is set for the locked
    identity strings -- job titles and canonical project names -- because those
    must match LinkedIn character-for-character; rewriting
    "AI & Cloud Infrastructure Engineer" would create exactly the recruiter
    cross-check mismatch the locked constants exist to prevent.
    """
    if not text:
        return ""
    s = str(text).translate(_TRANSLATION)
    s = _GE.sub("at least ", s)
    s = _LE.sub("at most ", s)
    s = _LT_NUM.sub("under ", s)
    s = _GT_NUM.sub("over ", s)
    s = _STRAY_ANGLE.sub(" ", s)
    if not preserve_ampersand:
        s = _SPACED_AMP.sub(" and ", s)
    s = unicodedata.normalize("NFKC", s)

    if any(ord(c) > 127 for c in s):
        residue = sorted({c for c in s if ord(c) > 127})
        logger.debug("Dropping unmapped non-ASCII from resume text: %r", residue)
        s = "".join(c if ord(c) < 128 else " " for c in s)

    s = _SPACE_BEFORE_PUNCT.sub(r"\1", s)
    return _MULTISPACE.sub(" ", s).strip()


# ─────────────────────────────────────────────────────────────────────────────
# Skill normalization
# ─────────────────────────────────────────────────────────────────────────────

# Tokens whose slash is part of the name, not a separator.
_NEVER_SPLIT_SLASH = {
    "tcp/ip", "ci/cd", "ui/ux", "i/o", "a/b", "s/mime", "r/w", "os/2", "24/7",
}
# Parents whose children read naturally as "<parent> <child>" in a skills list
# and match Workday's taxonomy that way ("AWS EC2"). Everything else emits the
# child standalone, because "Java Spring Boot" is not a skill but "Spring Boot" is.
_PLATFORM_PREFIX = {"aws", "azure", "gcp", "google cloud", "amazon web services"}
# A parenthetical containing one of these is a proficiency note, not a product.
_QUALIFIER_WORDS = {
    "certified", "certification", "cert", "experience", "proficient", "basic",
    "advanced", "familiar", "familiarity", "exposure", "coursework", "learning",
}

_PAREN = re.compile(r"^(?P<head>[^(]+?)\s*\((?P<inner>[^()]*)\)\s*(?P<tail>.*)$")
_STRIP_PARENS = re.compile(r"\s*\([^()]*\)")


def _looks_like_product(token: str) -> bool:
    """True when a parenthetical fragment is a proper product/technology name.

    Distinguishes `AWS (EC2, S3)` -- real sub-skills worth promoting -- from
    `Cloudflare Workers (edge serverless)` or `Ansible (RH294 certified)`,
    where the parenthetical is prose that would only pollute the skills line.
    """
    words = token.split()
    if not words or len(words) > 3:
        return False
    if any(w.lower().strip(".,()") in _QUALIFIER_WORDS for w in words):
        return False
    for w in words:
        core = w.strip("().,-")
        if not core:
            continue
        if not (core[0].isupper() or core[0].isdigit()):
            return False
    return True


def _expand_parens(item: str) -> list[str]:
    """`AWS (EC2, S3)` -> `[AWS, AWS EC2, AWS S3]`; `Ansible (RH294 certified)` -> `[Ansible]`."""
    m = _PAREN.match(item)
    if not m:
        return [item]
    head, inner, tail = m.group("head").strip(), m.group("inner"), m.group("tail").strip()
    if tail:  # unusual shape like "Foo (bar) baz" -- just drop the parenthetical
        return [_STRIP_PARENS.sub("", item).strip() or item]

    out = [head]
    children = [c.strip() for c in re.split(r"[,;]", inner) if c.strip()]
    prefix = head if head.lower() in _PLATFORM_PREFIX else ""
    for child in [c for c in children if _looks_like_product(c)][:MAX_CHILDREN_PER_ITEM]:
        out.append(f"{prefix} {child}" if prefix else child)
    return out


def _split_slashes(item: str) -> list[str]:
    """`JavaScript/TypeScript` -> two skills; `TCP/IP` stays one."""
    if "/" not in item or item.lower() in _NEVER_SPLIT_SLASH:
        return [item]
    parts = [p.strip() for p in item.split("/")]
    if len(parts) > 3 or any(len(p) < 2 for p in parts):
        return [item]
    return parts


def normalize_skill_items(items) -> list[str]:
    """Flatten one skill category into clean, comma-separable, taxonomy-matchable tokens.

    Every returned token is safe to sit between two commas on the skills line,
    which is the unit Workday actually matches. Bold markers survive on the
    first token derived from a bolded input.
    """
    out: list[str] = []
    seen: set[str] = set()
    for raw in items or []:
        text = str(raw)
        bold = "**" in text
        text = sanitize_text(text.replace("**", ""))
        if not text:
            continue
        first_from_this_item = True
        for expanded in _expand_parens(text):
            for part in re.split(r"\s*[,;]\s*", expanded):
                for token in _split_slashes(part.strip()):
                    token = token.strip(" ,;.")
                    key = token.lower()
                    if not token or key in seen:
                        continue
                    seen.add(key)
                    out.append(f"**{token}**" if bold and first_from_this_item else token)
                    first_from_this_item = False
    return out[:MAX_ITEMS_PER_CATEGORY]
