"""
The tools, plus the turn handler that decides between talking and reaching
for one.

Every tool returns {"say": <one or two spoken sentences>, "card": {...}}.
The spoken line and the card never carry the same text.
"""
import json
import os
import re
import urllib.error
import urllib.request
from datetime import datetime, timedelta

import data
import memory
from vault import VAULT

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
MODEL = "claude-sonnet-5"
MAX_TURNS = 10

# Instructions embedded in indexed files are data, not commands.
INJECTION_RE = re.compile(
    r"(ignore (all |your |previous )*instructions|disregard (the |your )*(above|prior|previous)"
    r"|system prompt|you are now|new instructions:)",
    re.IGNORECASE,
)


def _key():
    return (os.environ.get("ANTHROPIC_API_KEY") or "").strip()


def model_status():
    if not _key():
        return {
            "available": False,
            "reason": "ANTHROPIC_API_KEY not set — answers come from keyword scoring against your files, not from a model.",
        }
    return {"available": True, "reason": "", "model": MODEL}


def _system_prompt():
    parts = []
    for path in (os.path.join(HERE, "prompt.md"), os.path.join(ROOT, "CLAUDE.md")):
        if os.path.isfile(path):
            with open(path) as f:
                parts.append(f.read())
    facts = memory.list_facts(limit=40)
    if facts:
        lines = "\n".join(f"- ({f['date']}) {f['fact']}" for f in facts)
        parts.append(f"# Remembered facts\n\nWritten by you, at his request:\n{lines}")
    return "\n\n---\n\n".join(parts)


# ---------------------------------------------------------------- tools


def search_brain(query, **_):
    hits = VAULT.search(query, limit=5)
    if not hits:
        return {
            "say": "Nothing in your files on that.",
            "card": {"kind": "search", "query": query, "results": []},
        }
    flags = []
    for h in hits:
        if INJECTION_RE.search(h["excerpt"] or ""):
            flags.append(h["rel"])
    top = hits[0]
    if len(hits) == 1:
        say = f"One file — {top['title']}."
    else:
        names = ", ".join(h["title"] for h in hits[:3])
        say = f"{len(hits)} files, mostly {top['title']}. Also {names.split(', ', 1)[-1]}."
    if flags:
        say += f" One of them contains instruction-like text — flagged, not followed."
    return {
        "say": say,
        "card": {"kind": "search", "query": query, "results": hits, "flagged": flags},
    }


def research_web(query, **_):
    """No paid API is called without asking. This drafts the lookup instead."""
    local = VAULT.search(query, limit=3)
    return {
        "say": "No web access wired up — that would need a paid search key, so I'm not spending it. Here's what your own files say instead.",
        "card": {
            "kind": "research",
            "query": query,
            "status": "not_run",
            "why": "research_web needs a paid search API. Never spend without asking.",
            "local_context": local,
        },
    }


def _load_json(path):
    if not path or not os.path.isfile(path):
        return None
    try:
        with open(path) as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def read_inbox(**_):
    msgs = _load_json(data.inbox_source())
    if msgs is None:
        return {
            "say": "No inbox connected. Point JARVIS_INBOX_PATH at an export and I'll read it.",
            "card": {"kind": "inbox", "status": "unavailable", "messages": []},
        }
    enriched = []
    known = 0
    for m in msgs:
        sender = m.get("from", "")
        domain = sender.split("@")[-1].split(".")[0] if "@" in sender else sender
        matches = VAULT.search(domain, limit=2) if domain else []
        in_files = [x["title"] for x in matches if x["score"] >= 6]
        if in_files:
            known += 1
        flagged = bool(INJECTION_RE.search(m.get("preview", "")))
        enriched.append({**m, "known_from": in_files, "flagged": flagged})
    unread = sum(1 for m in msgs if m.get("unread"))
    new_names = [m["from"] for m in enriched if not m["known_from"]]
    say = f"{unread} unread. {known} from names already in your files"
    say += f", {len(new_names)} not." if new_names else "."
    if any(e["flagged"] for e in enriched):
        say += " One message contains instruction-like text — reporting it, not acting on it."
    return {"say": say, "card": {"kind": "inbox", "status": "ok", "messages": enriched}}


def brief_me(**_):
    events = _load_json(data.calendar_source()) or []
    msgs = _load_json(data.inbox_source()) or []
    today = datetime.now().date()
    soon = [e for e in events if e.get("start", "")[:10] >= str(today)][:5]
    unread = [m for m in msgs if m.get("unread")]

    slipped = []
    for n in VAULT.notes.values():
        for t in n.tasks:
            if t["done"] or not t["due"]:
                continue
            try:
                due = datetime.strptime(t["due"], "%Y-%m-%d").date()
            except ValueError:
                continue
            if due < today:
                slipped.append({"note": n.title, "rel": n.rel, "task": t["text"], "due": t["due"]})
    slipped.sort(key=lambda s: s["due"])

    bits = [f"{len(soon)} on the calendar", f"{len(unread)} unread"]
    say = ", ".join(bits) + "."
    if slipped:
        say += f" {len(slipped)} overdue, oldest is {slipped[0]['task']} from {slipped[0]['note']}."
    else:
        say += " Nothing overdue."
    return {
        "say": say,
        "card": {"kind": "brief", "events": soon, "unread": unread, "slipped": slipped},
    }


def remember_tool(fact, **_):
    rec = memory.remember(fact)
    if not rec:
        return {"say": "Nothing to write.", "card": {"kind": "memory", "written": None}}
    return {
        "say": f"Written to {rec['file']}: {rec['fact']}",
        "card": {"kind": "memory", "written": rec, "all": memory.list_facts(limit=20)},
    }


def plan_day(**_):
    """Five items max, ordered by what moves money. Nothing here is invented —
    every item traces to a task in an indexed file or an unread message."""
    today = datetime.now().date()
    horizon = today + timedelta(days=14)
    candidates = []

    for n in VAULT.notes.values():
        weight_type = {"prospect": 3.0, "client": 3.0, "project": 2.0}.get(n.type, 1.0)
        status = (n.meta.get("status") or "").lower()
        weight_status = {"active": 1.5, "cold": 1.2}.get(status, 1.0)
        for t in n.tasks:
            if t["done"]:
                continue
            score = weight_type * weight_status
            due = None
            if t["due"]:
                try:
                    due = datetime.strptime(t["due"], "%Y-%m-%d").date()
                except ValueError:
                    due = None
            if due:
                if due < today:
                    score += 4.0
                elif due <= horizon:
                    score += 2.0
            candidates.append({
                "task": t["text"],
                "source": n.title,
                "rel": n.rel,
                "due": t["due"],
                "why": "overdue" if due and due < today else ("due soon" if due else n.type),
                "score": round(score, 2),
            })

    candidates.sort(key=lambda c: (-c["score"], c["due"] or "9999"))
    picks = candidates[:5]
    if not picks:
        return {
            "say": "No open tasks in your files. Nothing to plan from.",
            "card": {"kind": "plan", "items": []},
        }
    say = f"{len(picks)} things. Start with {picks[0]['task']} — {picks[0]['why']}."
    return {"say": say, "card": {"kind": "plan", "items": picks, "considered": len(candidates)}}


TOOLS = {
    "search_brain": search_brain,
    "research_web": research_web,
    "read_inbox": read_inbox,
    "brief_me": brief_me,
    "remember": remember_tool,
    "plan_day": plan_day,
}

TOOL_SCHEMAS = [
    {
        "name": "search_brain",
        "description": "Find a specific fact in Yayeh's own indexed files. Use only when the answer must come from his files.",
        "input_schema": {
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
        },
    },
    {
        "name": "research_web",
        "description": "Look something up externally. Currently not wired to a paid API; returns local context instead.",
        "input_schema": {
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
        },
    },
    {
        "name": "read_inbox",
        "description": "Read-only inbox: who wrote, what about, and whether they already appear in his files.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "brief_me",
        "description": "Calendar, unread count, and overdue tasks.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "remember",
        "description": "Write one fact to one dated file in memory/. Use when he asks, or tells you something that still matters in three months.",
        "input_schema": {
            "type": "object",
            "properties": {"fact": {"type": "string"}},
            "required": ["fact"],
        },
    },
    {
        "name": "plan_day",
        "description": "Up to five open tasks from his files, ordered by what moves money.",
        "input_schema": {"type": "object", "properties": {}},
    },
]


# ---------------------------------------------------------------- routing


GREETING_RE = re.compile(
    r"^\s*(hi|hey|hello|yo|jarvis|good (morning|afternoon|evening)|"
    r"can you hear me|are you there|you there|test(ing)?|thanks|thank you|"
    r"ok|okay|cool|nice|sure|right|hm+|huh|go on|never ?mind)\b[\s!.?,]*$",
    re.IGNORECASE,
)
FOLLOWUP_RE = re.compile(r"^\s*(why|why\?|how come|and\?|so\?|what about|which one|the second one)\b", re.IGNORECASE)

INTENT_PATTERNS = [
    ("brief_me", r"\b(brief|briefing|catch me up|what'?s (up|new)|status|today)\b"),
    ("plan_day", r"\b(plan|priorit|what should i (do|work on)|to ?do|next up)\b"),
    ("read_inbox", r"\b(inbox|email|mail|who (wrote|emailed)|messages?)\b"),
    ("remember", r"\b(remember|note that|don'?t forget|make a note|save that)\b"),
    ("research_web", r"\b(look up|search the web|google|what does .* cost|market rate|online)\b"),
]


def _score_against_files(text):
    hits = VAULT.search(text, limit=3)
    return hits[0]["score"] if hits else 0.0


def _fallback_route(text):
    """Decide between conversation and a tool without a model.

    Never presented as the model talking — main.py surfaces a badge and the
    reply is tagged routed_by='keyword'.
    """
    t = text.strip()
    if not t:
        return None, {}
    if GREETING_RE.match(t) or FOLLOWUP_RE.match(t):
        return None, {}
    for name, pattern in INTENT_PATTERNS:
        if re.search(pattern, t, re.IGNORECASE):
            if name == "remember":
                fact = re.sub(
                    r"^\s*(please\s+)?(remember|note|save)( that)?[:,\s]*", "", t, flags=re.IGNORECASE
                ).strip()
                return "remember", {"fact": fact or t}
            if name == "research_web":
                return "research_web", {"query": t}
            return name, {}
    if len(t.split()) >= 3 and _score_against_files(t) >= 6.0:
        return "search_brain", {"query": t}
    return None, {}


def _fallback_reply(text, history):
    """Conversation without a model. Honest about being a stub."""
    t = text.strip().lower()
    if GREETING_RE.match(t):
        return "Here. No model key set, so I'm running on file matching only."
    if FOLLOWUP_RE.match(t) and history:
        last = next((h for h in reversed(history) if h.get("role") == "assistant"), None)
        if last:
            return "Can't reason about that without a model — no ANTHROPIC_API_KEY. The last answer came from file matching."
    return "No model reachable, so I can't hold a conversation — only search your files. Set ANTHROPIC_API_KEY in .env."


def _call_model(messages, system, use_tools=True):
    key = _key()
    if not key:
        return None, "no key"
    payload = {
        "model": MODEL,
        "max_tokens": 700,
        "system": system,
        "messages": messages,
    }
    if use_tools:
        payload["tools"] = TOOL_SCHEMAS
    req = urllib.request.Request(
        ANTHROPIC_URL,
        data=json.dumps(payload).encode(),
        headers={
            "x-api-key": key,
            "anthropic-version": "2023-06-01",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return json.loads(resp.read()), None
    except urllib.error.HTTPError as e:
        return None, f"model {e.code}: {e.read()[:200].decode(errors='replace')}"
    except Exception as e:
        return None, f"model unreachable: {e}"


def handle_turn(text, history=None):
    text = (text or "").strip()
    if not text:
        return {"say": "", "card": None, "routed_by": "none", "tool": None}

    history = (history or [])[-MAX_TURNS * 2:]
    status = model_status()

    if not status["available"]:
        tool, args = _fallback_route(text)
        if tool:
            out = TOOLS[tool](**args) if args else TOOLS[tool]()
            return {
                "say": out["say"],
                "card": out["card"],
                "tool": tool,
                "routed_by": "keyword",
                "model_available": False,
                "notice": status["reason"],
            }
        return {
            "say": _fallback_reply(text, history),
            "card": None,
            "tool": None,
            "routed_by": "keyword",
            "model_available": False,
            "notice": status["reason"],
        }

    messages = []
    for h in history:
        role = h.get("role")
        content = (h.get("text") or "").strip()
        if role in ("user", "assistant") and content:
            messages.append({"role": role, "content": content})
    messages.append({"role": "user", "content": text})

    system = _system_prompt()
    resp, err = _call_model(messages, system)
    if err:
        tool, args = _fallback_route(text)
        if tool:
            out = TOOLS[tool](**args) if args else TOOLS[tool]()
            return {
                "say": out["say"], "card": out["card"], "tool": tool,
                "routed_by": "keyword", "model_available": False, "notice": err,
            }
        return {
            "say": "Model call failed. Say it again or check the key.",
            "card": {"kind": "error", "detail": err},
            "tool": None, "routed_by": "keyword", "model_available": False, "notice": err,
        }

    tool_uses = [b for b in resp.get("content", []) if b.get("type") == "tool_use"]
    spoken = " ".join(
        b.get("text", "") for b in resp.get("content", []) if b.get("type") == "text"
    ).strip()

    if not tool_uses:
        return {
            "say": spoken, "card": None, "tool": None,
            "routed_by": "model", "model_available": True,
        }

    use = tool_uses[0]
    name = use.get("name")
    args = use.get("input") or {}
    fn = TOOLS.get(name)
    if not fn:
        return {
            "say": spoken or "That tool doesn't exist.", "card": None, "tool": None,
            "routed_by": "model", "model_available": True,
        }
    out = fn(**args)

    # Let the model phrase the spoken line from the tool result, so the card
    # and the sentence never carry the same words.
    messages.append({"role": "assistant", "content": resp["content"]})
    messages.append({
        "role": "user",
        "content": [{
            "type": "tool_result",
            "tool_use_id": use["id"],
            "content": json.dumps(out["card"])[:6000],
        }],
    })
    follow, ferr = _call_model(messages, system, use_tools=False)
    if not ferr and follow:
        phrased = " ".join(
            b.get("text", "") for b in follow.get("content", []) if b.get("type") == "text"
        ).strip()
        if phrased:
            out = {**out, "say": phrased}

    return {
        "say": out["say"], "card": out["card"], "tool": name,
        "routed_by": "model", "model_available": True,
    }
