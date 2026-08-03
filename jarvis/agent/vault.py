"""
Folders -> searchable graph.

Read-only. Nothing in this file opens a file for writing.
"""
import os
import re
import zlib
from datetime import datetime

import data

MAX_FILE_BYTES = 2 * 1024 * 1024
SKIP_DIRS = {"node_modules", ".git", ".obsidian", "__pycache__", ".venv", "venv", ".trash"}
TEXT_EXT = {".md", ".markdown", ".txt"}
PDF_EXT = {".pdf"}

WIKILINK_RE = re.compile(r"\[\[([^\]|#]+)(?:[|#][^\]]*)?\]\]")
FRONTMATTER_RE = re.compile(r"\A---\s*\n(.*?)\n---\s*\n", re.DOTALL)
TASK_RE = re.compile(r"^\s*[-*]\s+\[( |x|X)\]\s+(.+)$", re.MULTILINE)
DUE_RE = re.compile(r"due:\s*(\d{4}-\d{2}-\d{2})", re.IGNORECASE)

STOPWORDS = {
    "the", "a", "an", "and", "or", "but", "is", "are", "was", "were", "be",
    "been", "to", "of", "in", "on", "for", "with", "at", "by", "from", "as",
    "it", "this", "that", "these", "those", "i", "you", "my", "your", "we",
    "what", "which", "who", "how", "when", "where", "why", "do", "does", "did",
    "can", "could", "should", "would", "have", "has", "had", "not", "no",
    "about", "me", "up", "out", "so", "if", "then", "than", "there",
}


def _tokens(text):
    return [t for t in re.findall(r"[a-z0-9']+", text.lower()) if t not in STOPWORDS and len(t) > 1]


def _read_pdf_text(path):
    """Minimal PDF text extraction, stdlib only. Best-effort; returns '' on failure."""
    try:
        with open(path, "rb") as f:
            raw = f.read()
    except OSError:
        return ""
    chunks = []
    for match in re.finditer(rb"stream\r?\n(.*?)endstream", raw, re.DOTALL):
        blob = match.group(1)
        try:
            blob = zlib.decompress(blob)
        except zlib.error:
            pass
        for tj in re.finditer(rb"\((?:\\.|[^\\()])*\)", blob):
            s = tj.group(0)[1:-1]
            try:
                chunks.append(s.decode("latin-1"))
            except UnicodeDecodeError:
                continue
    text = " ".join(chunks)
    text = re.sub(r"\\[nrt]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _parse_frontmatter(text):
    meta = {}
    m = FRONTMATTER_RE.match(text)
    if not m:
        return meta, text
    for line in m.group(1).splitlines():
        if ":" in line:
            k, _, v = line.partition(":")
            meta[k.strip().lower()] = v.strip().strip("\"'")
    return meta, text[m.end():]


def _infer_type(meta, path, root):
    if meta.get("type"):
        return meta["type"].lower()
    rel = os.path.relpath(path, root)
    top = rel.split(os.sep)[0].lower() if os.sep in rel else ""
    for key, label in (
        ("project", "project"), ("client", "client"), ("prospect", "prospect"),
        ("tool", "tool"), ("learn", "note"), ("note", "note"), ("meeting", "meeting"),
        ("invoice", "invoice"),
    ):
        if key in top:
            return label
    return "note"


class Note:
    __slots__ = ("id", "title", "path", "rel", "type", "text", "links", "meta",
                 "tasks", "mtime", "size", "tokens", "backlinks")

    def __init__(self, **kw):
        for k in self.__slots__:
            setattr(self, k, kw.get(k))

    def as_dict(self, include_text=False):
        d = {
            "id": self.id,
            "title": self.title,
            "rel": self.rel,
            "type": self.type,
            "links": self.links,
            "backlinks": self.backlinks,
            "degree": len(set(self.links) | set(self.backlinks)),
            "tasks": self.tasks,
            "meta": self.meta,
            "mtime": self.mtime,
            "size": self.size,
        }
        if include_text:
            d["text"] = self.text
        return d


class Vault:
    def __init__(self):
        self.notes = {}          # id -> Note
        self.by_title = {}       # lowercased title -> id
        self.roots = []
        self.errors = []
        self.indexed_at = None

    # ---------- indexing ----------

    def index(self):
        self.notes.clear()
        self.by_title.clear()
        self.errors.clear()
        self.roots = data.vault_paths()

        for root in self.roots:
            if not os.path.isdir(root):
                self.errors.append(f"not a directory: {root}")
                continue
            self._walk(root)

        self._resolve_links()
        self.indexed_at = datetime.now().isoformat(timespec="seconds")
        return self.stats()

    def _walk(self, root):
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS and not d.startswith(".")]
            for fn in filenames:
                ext = os.path.splitext(fn)[1].lower()
                if ext not in TEXT_EXT and ext not in PDF_EXT:
                    continue
                full = os.path.join(dirpath, fn)
                try:
                    st = os.stat(full)
                except OSError as e:
                    self.errors.append(f"{full}: {e}")
                    continue
                if st.st_size > MAX_FILE_BYTES:
                    continue
                self._add(full, root, st, ext)

    def _add(self, full, root, st, ext):
        if ext in PDF_EXT:
            text = _read_pdf_text(full)
            meta = {}
        else:
            try:
                with open(full, "r", errors="replace") as f:
                    raw = f.read()
            except OSError as e:
                self.errors.append(f"{full}: {e}")
                return
            meta, text = _parse_frontmatter(raw)

        title = meta.get("title") or os.path.splitext(os.path.basename(full))[0]
        rel = os.path.relpath(full, root)
        nid = rel.replace(os.sep, "/")
        if nid in self.notes:
            nid = f"{os.path.basename(root)}/{nid}"

        tasks = []
        for m in TASK_RE.finditer(text):
            body = m.group(2).strip()
            due = DUE_RE.search(body)
            tasks.append({
                "done": m.group(1).lower() == "x",
                "text": DUE_RE.sub("", body).strip(" ()"),
                "due": due.group(1) if due else None,
            })

        note = Note(
            id=nid,
            title=title,
            path=full,
            rel=rel,
            type=_infer_type(meta, full, root),
            text=text,
            links=sorted({m.group(1).strip() for m in WIKILINK_RE.finditer(text)}),
            meta=meta,
            tasks=tasks,
            mtime=datetime.fromtimestamp(st.st_mtime).isoformat(timespec="seconds"),
            size=st.st_size,
            tokens=None,
            backlinks=[],
        )
        note.tokens = _tokens(note.title + " " + note.text)
        self.notes[nid] = note
        self.by_title.setdefault(title.lower(), nid)

    def _resolve_links(self):
        for note in self.notes.values():
            note.backlinks = []
        for note in self.notes.values():
            resolved = []
            for link in note.links:
                target = self.by_title.get(link.lower())
                if target and target != note.id:
                    resolved.append(target)
                    self.notes[target].backlinks.append(note.id)
            note.links = sorted(set(resolved))
        for note in self.notes.values():
            note.backlinks = sorted(set(note.backlinks))

    # ---------- queries ----------

    def stats(self):
        by_type = {}
        for n in self.notes.values():
            by_type[n.type] = by_type.get(n.type, 0) + 1
        edges = sum(len(n.links) for n in self.notes.values())
        return {
            "roots": self.roots,
            "demo": data.is_demo(),
            "count": len(self.notes),
            "edges": edges,
            "by_type": by_type,
            "top_hubs": [
                {"title": n.title, "id": n.id, "degree": len(set(n.links) | set(n.backlinks))}
                for n in self.hubs(10)
            ],
            "errors": self.errors,
            "indexed_at": self.indexed_at,
        }

    def hubs(self, limit=10):
        return sorted(
            self.notes.values(),
            key=lambda n: (-(len(set(n.links) | set(n.backlinks))), n.title.lower()),
        )[:limit]

    def graph(self):
        nodes = []
        edges = []
        seen = set()
        for n in self.notes.values():
            nodes.append({
                "id": n.id,
                "title": n.title,
                "type": n.type,
                "degree": len(set(n.links) | set(n.backlinks)),
            })
            for t in n.links:
                key = tuple(sorted((n.id, t)))
                if key not in seen:
                    seen.add(key)
                    edges.append({"source": key[0], "target": key[1]})
        return {"nodes": nodes, "edges": edges}

    def note(self, nid):
        return self.notes.get(nid)

    def search(self, query, limit=6):
        """Score notes against a query. Title hits count heavily."""
        q = _tokens(query)
        if not q:
            return []
        qset = set(q)
        results = []
        for n in self.notes.values():
            title_tokens = set(_tokens(n.title))
            body = n.tokens or []
            body_counts = {}
            for t in body:
                if t in qset:
                    body_counts[t] = body_counts.get(t, 0) + 1
            if not body_counts and not (title_tokens & qset):
                continue
            score = 6.0 * len(title_tokens & qset)
            score += sum(1.0 + 0.3 * (c - 1) for c in body_counts.values())
            score += 0.4 * len(set(n.links) | set(n.backlinks)) ** 0.5
            results.append((score, n))
        results.sort(key=lambda p: (-p[0], p[1].title.lower()))
        out = []
        for score, n in results[:limit]:
            out.append({
                "id": n.id,
                "title": n.title,
                "rel": n.rel,
                "type": n.type,
                "score": round(score, 2),
                "excerpt": self._excerpt(n, qset),
                "tasks": n.tasks,
                "links": [self.notes[l].title for l in n.links if l in self.notes],
            })
        return out

    def _excerpt(self, note, qset, width=240):
        text = re.sub(r"\s+", " ", note.text).strip()
        if not text:
            return ""
        lowered = text.lower()
        best, best_pos = -1, 0
        for i in range(0, max(1, len(text) - width + 1), 60):
            window = lowered[i:i + width]
            hits = sum(1 for t in qset if t in window)
            if hits > best:
                best, best_pos = hits, i
        snippet = text[best_pos:best_pos + width].strip()
        prefix = "..." if best_pos > 0 else ""
        suffix = "..." if best_pos + width < len(text) else ""
        return f"{prefix}{snippet}{suffix}"

    def shortest_path(self, a, b):
        """BFS over the undirected link graph."""
        if a not in self.notes or b not in self.notes:
            return []
        if a == b:
            return [a]
        seen = {a: None}
        queue = [a]
        while queue:
            nxt = []
            for cur in queue:
                node = self.notes[cur]
                for adj in set(node.links) | set(node.backlinks):
                    if adj in seen or adj not in self.notes:
                        continue
                    seen[adj] = cur
                    if adj == b:
                        path = [b]
                        while seen[path[-1]] is not None:
                            path.append(seen[path[-1]])
                        return list(reversed(path))
                    nxt.append(adj)
            queue = nxt
        return []


VAULT = Vault()


if __name__ == "__main__":
    stats = VAULT.index()
    mode = "DEMO" if stats["demo"] else "REAL"
    print(f"[{mode}] indexed {stats['count']} notes, {stats['edges']} edges")
    print(f"  roots: {', '.join(stats['roots']) or '(none)'}")
    print("  by type:")
    for t, c in sorted(stats["by_type"].items(), key=lambda p: -p[1]):
        print(f"    {t:<10} {c}")
    print("  top 10 hubs:")
    for h in stats["top_hubs"]:
        print(f"    {h['degree']:>3}  {h['title']}")
    for e in stats["errors"]:
        print(f"  ! {e}")
