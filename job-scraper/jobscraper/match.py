"""Free resume check: which important words from a job ad appear in your resume.

No AI involved. It picks the words and two-word phrases the ad uses most
(the title counts extra), ignores filler words, and looks for each in the
resume text. It's a rough guide to what an applicant-tracking system or a
recruiter skimming for keywords would notice.
"""

from __future__ import annotations

import re
from collections import Counter

STOPWORDS = set("""
a about above after again against all also am an and any are as at be because been before being below between both
but by can could did do does doing down during each etc few for from further had has have having he her here hers
him his how i if in into is it its itself just me more most my no nor not now of off on once only or other our ours
out over own same she should so some such than that the their theirs them then there these they this those through
to too under until up very was we were what when where which while who whom why will with would you your yours
able across ad ads apply applicant applicants applications based benefits candidate candidates company day days
description duties employer employment equal etc every experience full get great help hiring hour hours include
including join job jobs looking make may must need needed new opportunity part pay per plus position preferred
provide required requirements responsibilities role salary seeking shift skills strong team time us using well
within work working year years yr yrs week weekly active lbs permanent contract jobs ability excellent require requires
""".split())
# Same thing, written differently. Each group counts as found if any of its forms is in the resume.
ALIASES = [
    {"registered nurse", "rn"}, {"licensed practical nurse", "lpn"}, {"certified nursing assistant", "cna"},
    {"electronic health record", "ehr", "emr"}, {"medical surgical", "med surg"}, {"commercial driver", "cdl"},
    {"customer service", "customer support"}, {"microsoft excel", "excel"}, {"point of sale", "pos"},
    {"javascript", "js"}, {"kubernetes", "k8s"},
]
WORD_RE = re.compile(r"[a-z][a-z0-9+#.\-/]*[a-z0-9+#]|[a-z]")


def _words(text: str) -> list[str]:
    return [w for w in WORD_RE.findall((text or "").lower()) if len(w) > 1]


def _stem(word: str) -> str:
    for suffix in ("ing", "ed", "es", "s"):
        if len(word) > len(suffix) + 3 and word.endswith(suffix):
            return word[: -len(suffix)]
    return word


def _chunks(text: str) -> list[list[str]]:
    """Word runs between punctuation, so phrases never span "Associate - Night" or "picking, packing"."""
    return [_words(part) for part in re.split(r"[,.;:!?()\[\]|&•–—]|\s-\s|\n", (text or "").lower())]


def _useful(w: str) -> bool:
    return w not in STOPWORDS and len(w) > 2 and not w.isdigit() and not w.startswith("$")


def keywords(title: str, description: str, tags=(), limit: int = 15) -> list[str]:
    singles: Counter[str] = Counter()
    pairs: Counter[str] = Counter()
    for weight, text in ((3, title), (1, description), (2, " | ".join(tags or []))):
        for chunk in _chunks(text):
            for w in chunk:
                if _useful(w):
                    singles[w] += weight
            for a, b in zip(chunk, chunk[1:]):
                if _useful(a) and _useful(b):
                    pairs[f"{a} {b}"] += weight
    # A two-word phrase counts when it's in the title or repeated; then it stands in for its words.
    scored = {p: n * 1.5 for p, n in pairs.items() if n >= 2}
    for w, n in singles.items():
        if not any(w in p.split() for p in scored):
            scored[w] = n
    return [t for t, _ in sorted(scored.items(), key=lambda kv: (-kv[1], kv[0]))][:limit]


def _parts(text: str) -> list[str]:
    """Words with "med/surg" and "med-surg" both split into "med", "surg"."""
    return [p for w in _words(text) for p in re.split(r"[-/]", w) if p]


def in_text(term: str, resume_text: str) -> bool:
    stems = {_stem(w) for w in _parts(resume_text)}
    norm = " ".join(_parts(term))
    forms = next((g for g in ALIASES if norm in g), {norm})
    return any(all(_stem(w) in stems for w in form.split()) for form in forms)


def match(resume_text: str, title: str, description: str, tags=()) -> dict:
    # Category names like "Healthcare & Nursing Jobs" and "Full Time" aren't things a resume should say.
    tags = [t for t in tags or [] if not t.lower().endswith(" jobs") and t.lower().replace("-", " ") not in
            {"full time", "part time", "permanent", "contract", "temporary", "internship"}]
    terms = keywords(title, description, tags)
    found = [t for t in terms if in_text(t, resume_text)]
    missing = [t for t in terms if t not in found]
    score = round(100 * len(found) / len(terms)) if terms else 0
    return {"score": score, "found": found, "missing": missing, "checked": len(terms)}
