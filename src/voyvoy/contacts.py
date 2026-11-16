"""~/.voy/contacts.md: one `## Name` section per person, free-form lines below it."""

from __future__ import annotations

import re
from pathlib import Path

from voyvoy.protocol import VOY_HOME

CONTACTS_PATH = VOY_HOME / "contacts.md"

CONTACTS_TEMPLATE = """\
# Contacts

The people your agent talks to: one `## Name` section each. Claude reads the card before a call,
and the agent sees it during the call. Easiest: ask Claude ("save Ana's email, she prefers Spanish").
Write whatever helps: role, email (for invites), language, how to address them, what they decide on.

<!-- An example (inside this comment, so it isn't a real contact):

## Ana Ruiz
Role: PM for the side project
Email: ana@example.com
Language: English
Notes: prefers short calls; decides on scope, not on tech
-->
"""

_COMMENT = re.compile(r"<!--.*?-->", re.S)
_HEADING = re.compile(r"^## +(.+?)\s*$", re.MULTILINE)


def load_contacts(path: Path = CONTACTS_PATH) -> dict[str, str]:
    if not path.exists():
        return {}
    text = _COMMENT.sub("", path.read_text())
    matches = list(_HEADING.finditer(text))
    contacts: dict[str, str] = {}
    for i, m in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        contacts[m.group(1)] = text[m.end():end].strip()
    return contacts


def find_contact(contacts: dict[str, str], query: str) -> tuple[str, str] | None:
    """Exact name first, then a name or one of its words starting with the query.
    Never a mid-word match: "Ana" must not find "Dana"."""
    q = query.strip().casefold()
    if not q:
        return None
    for name, card in contacts.items():
        if name.casefold() == q:
            return name, card
    for name, card in contacts.items():
        n = name.casefold()
        if n.startswith(q) or any(word.startswith(q) for word in n.split()):
            return name, card
    return None
