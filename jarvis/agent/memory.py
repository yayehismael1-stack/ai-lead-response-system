"""
Writes to memory/ and nowhere else.

Every path this module produces is built from data.memory_dir(). There is no
code path here that writes outside it, and nothing else in JARVIS writes at all.
"""
import os
import re
from datetime import datetime

import data

SAFE_SLUG = re.compile(r"[^a-z0-9]+")


def _dir():
    d = data.memory_dir()
    os.makedirs(d, exist_ok=True)
    return d


def _slug(text, limit=48):
    s = SAFE_SLUG.sub("-", text.lower()).strip("-")
    return (s[:limit].rstrip("-")) or "fact"


def remember(fact, source="spoken"):
    """One fact, one dated file. Returns the record so the caller can say it aloud."""
    fact = (fact or "").strip()
    if not fact:
        return None
    now = datetime.now()
    stamp = now.strftime("%Y-%m-%d")
    base = f"{stamp}-{_slug(fact)}"
    d = _dir()
    path = os.path.join(d, base + ".md")
    n = 2
    while os.path.exists(path):
        path = os.path.join(d, f"{base}-{n}.md")
        n += 1

    # Guarantee we never escape memory/ even if a slug somehow contains a separator.
    if os.path.dirname(os.path.abspath(path)) != os.path.abspath(d):
        raise ValueError("refusing to write outside memory/")

    body = (
        f"---\ndate: {now.isoformat(timespec='seconds')}\nsource: {source}\n---\n\n"
        f"{fact}\n"
    )
    with open(path, "w") as f:
        f.write(body)
    return {"file": os.path.basename(path), "fact": fact, "date": stamp}


def list_facts(limit=200):
    d = _dir()
    out = []
    for fn in sorted(os.listdir(d), reverse=True):
        if not fn.endswith(".md"):
            continue
        full = os.path.join(d, fn)
        try:
            with open(full) as f:
                raw = f.read()
        except OSError:
            continue
        body = raw.split("---", 2)[-1].strip() if raw.startswith("---") else raw.strip()
        out.append({"file": fn, "fact": body, "date": fn[:10]})
        if len(out) >= limit:
            break
    return out


def search(query, limit=5):
    q = (query or "").lower().split()
    if not q:
        return []
    scored = []
    for rec in list_facts():
        text = rec["fact"].lower()
        hits = sum(1 for t in q if t in text)
        if hits:
            scored.append((hits, rec))
    scored.sort(key=lambda p: -p[0])
    return [r for _, r in scored[:limit]]
