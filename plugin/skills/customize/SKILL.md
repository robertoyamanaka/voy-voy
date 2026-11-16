---
name: customize
description: Use when the user wants to change how their VoyVoy agent talks or behaves (tone, formality, pace, how it closes), add or update a contact (email, role, language, how to address them), set a project's call language, change the agent's voice or models, or change their name or LiveKit keys; also after a call, when you learned someone's details worth saving.
---

# Customize VoyVoy for the user

The user changes VoyVoy by telling you, not by editing files: you edit the files, then tell them in one
line what changed. VoyVoy never overwrites these files, and its updates keep improving the defaults
underneath them.

| The user says | You change |
|---|---|
| "Save Ana's email", "Marco speaks Spanish", "call him Mr. Lee" | `~/.voy/contacts.md` |
| "Be more formal", "always ask if there's anything else", "slower" | `~/.voy/playbook.md` (every call) |
| "With this client, use usted", "calls here are in Spanish" | `<project>/.voy/playbook.md`, `<project>/.voy/config.toml` |
| "Use a different voice", "try a faster model" | `~/.voy/config.toml` |
| "Call me Sam", new LiveKit keys | `voy_setup(owner=…)` or `voy_setup(livekit_url=…, api_key=…, api_secret=…)` |

## Contacts: `~/.voy/contacts.md`
One `## Full Name` section per person, free-form lines below it:

```
## Ana Ruiz
Role: PM for the side project
Email: ana@example.com
Language: Spanish
Notes: prefers short calls; decides on scope, not on tech
```

- Check `voy_contacts` first and update an existing card instead of adding a duplicate.
- `Email:` is what you invite them with. `Language: Spanish` means you pass `language="es"` when calling them.
- Save what the user told you. For things the person said on a call (their email, a better time to call),
  ask the user before saving.

## How the agent sounds: the playbook
VoyVoy's default playbook has these sections: `## How this call should feel`, `## Pace`, `## Answers`,
`## Closing`, `## Overlaps`, `## Tone`. The user's playbook file adds to it:
- A section with the **same heading replaces** that default section. So rewrite the whole section: run
  `voy playbook` first to see its current text, and keep what still applies.
- Any **other heading is added**.
- `<project>/.voy/playbook.md` works the same way for one project and wins over `~/.voy/playbook.md`.

Write short, plain instructions for a voice agent ("When an answer is vague, ask one follow-up."). Then
run `voy playbook` (from the project folder for a project playbook) and show the user the section that
changed. A one-off instruction for a single call goes in that call's briefing instead.

The AI disclosure, the goals and the call rules can't be changed. If the user asks for that (for example
"don't say you're an AI"), say so plainly.

## Language, voice and models
- A project's default call language: `language = "es"` in `<project>/.voy/config.toml`. VoyVoy speaks
  English (`en`) and Spanish (`es`) so far.
- Models and voices: `~/.voy/config.toml`, `[models]` (`stt`, `llm`, `tts`, `voice`) and `[voices]`
  (`es = "cartesia/sonic-3:<voice id>"`). Change only the line asked for and keep the comments. Model names
  are LiveKit Inference strings (https://docs.livekit.io/agents/models/inference/).
- These apply from the next call. A new name or LiveKit keys go through `voy_setup`, which reloads them.
