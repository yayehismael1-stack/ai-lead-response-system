"""
THE ONLY FILE THAT TOUCHES MY REAL DATA.

JARVIS_DEMO controls everything:
  1 (default) -> invented fixtures in data/demo/, safe to screen-record
  0           -> real folders, read from JARVIS_VAULT_PATHS

Every other module asks this file "where do I read from" and never
touches os.environ or a real path directly.
"""
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEMO_VAULT_DIR = os.path.join(ROOT, "data", "demo", "vault")
DEMO_INBOX_FILE = os.path.join(ROOT, "data", "demo", "inbox.json")
DEMO_CALENDAR_FILE = os.path.join(ROOT, "data", "demo", "calendar.json")


def is_demo() -> bool:
    return os.environ.get("JARVIS_DEMO", "1").strip() != "0"


def vault_paths():
    """List of read-only folders to index."""
    if is_demo():
        return [DEMO_VAULT_DIR]
    raw = os.environ.get("JARVIS_VAULT_PATHS", "")
    paths = [p.strip() for p in raw.split(",") if p.strip()]
    return paths


def inbox_source():
    """Path to a read-only inbox export (JSON list of messages)."""
    if is_demo():
        return DEMO_INBOX_FILE
    return os.environ.get("JARVIS_INBOX_PATH", "")


def calendar_source():
    """Path to a read-only calendar export (JSON list of events)."""
    if is_demo():
        return DEMO_CALENDAR_FILE
    return os.environ.get("JARVIS_CALENDAR_PATH", "")


def memory_dir():
    return os.path.join(ROOT, "memory")
