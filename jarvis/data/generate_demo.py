#!/usr/bin/env python3
"""
Builds data/demo/ — invented fixtures shaped like Yayeh's actual work
(IT automation / workflow-building, pre-revenue, portfolio stage), so the
graph looks the same on every run.

Run: python3 jarvis/data/generate_demo.py
"""
import json
import os
import random

random.seed(20260803)  # fixed seed -> identical graph every run

HERE = os.path.dirname(os.path.abspath(__file__))
VAULT = os.path.join(HERE, "demo", "vault")

os.makedirs(os.path.join(VAULT, "Projects"), exist_ok=True)
os.makedirs(os.path.join(VAULT, "Prospects"), exist_ok=True)
os.makedirs(os.path.join(VAULT, "Learning"), exist_ok=True)
os.makedirs(os.path.join(VAULT, "Tools"), exist_ok=True)
os.makedirs(os.path.dirname(os.path.join(HERE, "demo")), exist_ok=True)


def write(path, content):
    full = os.path.join(VAULT, path)
    os.makedirs(os.path.dirname(full), exist_ok=True)
    with open(full, "w") as f:
        f.write(content.strip() + "\n")


# ---- Projects (portfolio work, no paying clients yet) ----

write(
    "Projects/AI Lead Response System.md",
    """
---
type: project
status: active
---
# AI Lead Response System

Portfolio build: [[Tally]] form -> [[Make]] automation -> [[OpenAI API]]
analysis -> priority routing -> [[Gmail]] notification.

Built for home-service businesses (garage door, HVAC, plumbing, electrical,
roofing, restoration, property management) who currently triage leads by hand.

- [ ] Add SMS notifications (due: 2026-08-10)
- [ ] Appointment booking step (due: 2026-08-20)
- [x] Emergency vs standard routing
- [x] Customer confirmation email

See [[Automation Pricing Notes]] for what this kind of build should cost a client.
Related: [[Garage Door Co Prospect]], [[HVAC Prospect]].
""",
)

write(
    "Projects/Home Inventory Automation.md",
    """
---
type: project
status: idea
---
# Home Inventory Automation

Small n8n workflow idea: barcode scan -> Google Sheet -> low-stock alert.
Built to learn [[n8n]] properly before pitching it as a paid workflow.

Related: [[Make]], [[n8n]].
""",
)

write(
    "Projects/Portfolio Site.md",
    """
---
type: project
status: active
---
# Portfolio Site

Static site listing automation case studies, including
[[AI Lead Response System]]. Needs a pricing page once
[[Automation Pricing Notes]] is finalized.

- [ ] Write case study copy (due: 2026-08-05)
- [ ] Deploy to a real domain
""",
)

# ---- Prospects (no real clients yet — these are practice/target profiles) ----

write(
    "Prospects/Garage Door Co Prospect.md",
    """
---
type: prospect
status: cold
---
# Garage Door Co (target profile)

Hypothetical target for [[AI Lead Response System]] — the kind of business
that gets emergency vs. routine calls and currently answers both the same way.

Not a real client yet. Use as the reference case when pricing automation work.
""",
)

write(
    "Prospects/HVAC Prospect.md",
    """
---
type: prospect
status: cold
---
# HVAC Prospect (target profile)

Second target profile for the lead-response pitch. Emergency no-heat calls
vs. routine maintenance requests — same routing logic as
[[AI Lead Response System]].
""",
)

# ---- Learning / reference ----

write(
    "Learning/Automation Pricing Notes.md",
    """
---
type: note
status: reference
---
# Automation Pricing Notes

Rough numbers gathered while researching what to charge once this becomes
a real business (not client-confirmed, just market research):

- Simple lead-routing automation (form -> AI -> email): ~$500-1,500 one-off
- Multi-step workflow with CRM integration: ~$2,000-5,000
- Ongoing maintenance retainer: ~$150-400/month

Reference build: [[AI Lead Response System]].
""",
)

write(
    "Learning/Prompt Engineering Notes.md",
    """
---
type: note
status: reference
---
# Prompt Engineering Notes

Patterns that worked in [[OpenAI API]] calls for [[AI Lead Response System]]:
- Force structured JSON output (priority, urgency, category, summary)
- Few-shot examples for edge cases (vague requests, multiple issues in one form)
- Explicit "if unsure, mark for human review" instruction
""",
)

# ---- Tools referenced ----

for name, body in [
    ("Tally", "Form builder used to capture the initial customer request."),
    ("Make", "Automation platform (formerly Integromat) running the workflow."),
    ("OpenAI API", "Used for request analysis: priority, urgency, category, summary."),
    ("Gmail", "Sends business-owner notifications and customer confirmations."),
    ("n8n", "Open-source workflow tool, being learned as a Make alternative."),
]:
    write(f"Tools/{name}.md", f"---\ntype: tool\n---\n# {name}\n\n{body}\n")

print(f"Wrote demo vault to {VAULT}")

# ---- Inbox fixture (read-only, demo) ----

inbox = [
    {
        "id": "m1",
        "from": "no-reply@tally.so",
        "subject": "New response: Garage Door Service Request",
        "date": "2026-08-02T09:14:00",
        "unread": True,
        "preview": "Emergency - door off track, car trapped inside garage.",
    },
    {
        "id": "m2",
        "from": "hello@n8n.io",
        "subject": "New in n8n: native queue mode improvements",
        "date": "2026-08-01T16:40:00",
        "unread": True,
        "preview": "This release focuses on scaling workflow execution...",
    },
    {
        "id": "m3",
        "from": "billing@openai.com",
        "subject": "Your July API usage",
        "date": "2026-07-31T08:00:00",
        "unread": False,
        "preview": "Your usage this month was $4.12.",
    },
]
with open(os.path.join(HERE, "demo", "inbox.json"), "w") as f:
    json.dump(inbox, f, indent=2)

# ---- Calendar fixture (read-only, demo) ----

calendar = [
    {
        "id": "e1",
        "title": "Record portfolio walkthrough video",
        "start": "2026-08-03T14:00:00",
        "end": "2026-08-03T15:00:00",
    },
    {
        "id": "e2",
        "title": "n8n workflow tutorial (self-study block)",
        "start": "2026-08-04T10:00:00",
        "end": "2026-08-04T11:30:00",
    },
]
with open(os.path.join(HERE, "demo", "calendar.json"), "w") as f:
    json.dump(calendar, f, indent=2)

print("Wrote demo inbox.json and calendar.json")
