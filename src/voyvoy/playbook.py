"""The talker's style guide ("playbook"): VoyVoy's default plus your own layers.

Layers add to the default, like CLAUDE.md files do. A `## Heading` that matches
one of the default's replaces that section; any other heading is added. So you
can change one thing (say, `## Tone`) and still get every improvement VoyVoy
ships to the rest. VoyVoy never writes to your layers after creating the
starter file.

  1. the default            ships with VoyVoy, updated with it
  2. ~/.voy/playbook.md      you, on every call
  3. <project>/.voy/playbook.md   this project only (wins over yours)

HTML comments are ignored, so the starter file changes nothing until you edit it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from voyvoy.protocol import VOY_HOME

MAX_LAYER_BYTES = 8_000
FILENAMES = ("playbook.md", "talker.md")  # talker.md: the old name, still read
_COMMENT = re.compile(r"<!--.*?-->", re.S)
_H2 = re.compile(r"^##[ \t]+(.+?)[ \t#]*$", re.M)

STARTER = """\
<!--
Your VoyVoy playbook: how your agent should sound on every call.

Everything inside these comment markers is ignored, so this file changes nothing yet.
Easiest: ask Claude ("make my agent more formal") and it edits this file for you.
Or write below the closing marker yourself. `voy playbook` shows what your agent gets.

How it combines with VoyVoy's default playbook:
- A section whose heading matches a default one replaces it. The default headings are:
  ## How this call should feel, ## Pace, ## Answers, ## Closing, ## Overlaps, ## Tone
- Any other heading is added. Text before the first heading becomes "## Your notes".
- <project>/.voy/playbook.md works the same way for one project, and wins over this file.
- You can't change the disclosure: your agent always says it's your AI agent first.

Examples:

## Tone
Formal and polite. In Spanish, use "usted".

## Closing
Before saying goodbye, ask once if there's anything else I should know.
-->
"""


@dataclass
class Section:
    heading: str
    body: str
    source: str


@dataclass
class Layer:
    source: str  # shown by `voy playbook`, e.g. "~/.voy/playbook.md"
    lead_heading: str  # heading for text written before the first `##`
    text: str


def parse(text: str, source: str, lead_heading: str = "Notes") -> list[Section]:
    text = _COMMENT.sub("", text)
    if len(text.encode()) > MAX_LAYER_BYTES:
        text = text.encode()[:MAX_LAYER_BYTES].decode(errors="ignore")
        source += " (cut at 8 KB)"
    matches = list(_H2.finditer(text))
    sections: list[Section] = []
    lead = text[: matches[0].start()] if matches else text
    if lead.strip():
        sections.append(Section(lead_heading, lead.strip(), source))
    for i, m in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        body = text[m.end():end].strip()
        if body:
            sections.append(Section(m.group(1).strip(), body, source))
    return sections


def compose(default: str, layers: list[Layer]) -> list[Section]:
    sections = parse(default, "default")
    for layer in layers:
        for new in parse(layer.text, layer.source, layer.lead_heading):
            at = next((i for i, s in enumerate(sections) if s.heading.casefold() == new.heading.casefold()), None)
            if at is None:
                sections.append(new)
            else:
                sections[at] = new
    return sections


def render(sections: list[Section], with_sources: bool = False) -> str:
    out = []
    for s in sections:
        tag = f"   <!-- from {s.source} -->" if with_sources else ""
        out.append(f"## {s.heading}{tag}\n{s.body}")
    return "\n\n".join(out)


def _find(directory: Path) -> Path | None:
    return next((directory / n for n in FILENAMES if (directory / n).is_file()), None)


def layers_for(project_dir: Path | None, home: Path | None = None) -> list[Layer]:
    home = home or VOY_HOME
    candidates = [(home, "~/.voy/{}", "Your notes")]
    if project_dir:
        candidates.append((project_dir / ".voy", ".voy/{} (this project)", "Notes for this project"))
    layers: list[Layer] = []
    seen: set[Path] = set()
    for directory, label, lead in candidates:
        path = _find(directory)
        if path and path.resolve() not in seen:  # running from ~ would read ~/.voy twice
            seen.add(path.resolve())
            layers.append(Layer(label.format(path.name), lead, path.read_text()))
    return layers


def default_playbook() -> str:
    from voyvoy.agent.talker import DEFAULT_PLAYBOOK

    return DEFAULT_PLAYBOOK


def effective(project_dir: Path | None, home: Path | None = None, with_sources: bool = False) -> str:
    return render(compose(default_playbook(), layers_for(project_dir, home)), with_sources)


def ensure_starter(home: Path | None = None) -> bool:
    """Write the commented starter ~/.voy/playbook.md once. Never touches an existing file."""
    home = home or VOY_HOME
    if _find(home):
        return False
    home.mkdir(parents=True, exist_ok=True)
    (home / "playbook.md").write_text(STARTER)
    return True
