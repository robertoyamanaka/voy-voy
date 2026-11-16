---
name: setup
description: Use when the user wants to install, set up, test or repair VoyVoy, when the voy_* tools are missing, or when a voy tool says setup is incomplete (no config, voy-tap, BlackHole, Google sign-in or audio permission).
---

# Set up VoyVoy

The user shouldn't need a terminal: you run each step. One step at a time, short messages, and say what
macOS is about to show before it shows it. Every step is safe to re-run.

## 0. Make sure the voy tools exist
If the `voy_setup_check` tool is available, go to step 1. Otherwise the VoyVoy command line isn't installed yet:
1. Check with Bash: `command -v voy || ls ~/.local/bin/voy`. If it's there, go to 4.
2. Check `command -v uv`. If it's missing, ask, then install it: `brew install uv` if Homebrew is there,
   otherwise `curl -LsSf https://astral.sh/uv/install.sh | sh`.
3. Ask, then run `uv tool install voyvoy` (about a minute; `uv tool upgrade voyvoy` updates it later).
4. Ask the user to run `/mcp`, pick **voy**, then **Reconnect** (or restart Claude Code), and tell you when
   that's done. Then continue.

## 1. See what's missing
Say they'll hear a short test sentence, then call `voy_setup_check`. Show a short ✓/✗ checklist. If
`ready` is true, go to step 4 (the Google Meet window isn't part of this check).

## 2. Name and LiveKit keys
Needed if "Your name" or "LiveKit credentials" failed. The agent introduces itself as "<name>'s AI agent",
and it runs on the user's own LiveKit Cloud project (the free tier is enough). In one message, ask for their
first name and, if they don't have keys yet, walk them through it:
1. Sign up at https://cloud.livekit.io (free) and create a project.
2. Open **Settings → API Keys** and create a key.
3. Copy the project URL (starts with `wss://`), the API key and the API secret.

Offer two ways to hand them over:
- Paste them here: you pass them to `voy_setup`, which saves them only in `~/.voy/config.toml`, readable only
  by them.
- Or keep the secret out of this chat: they run `voy init` in their own terminal and tell you when it's done.

Pass only the values you got. An empty value keeps what's saved, so fixing one key never wipes the others.

## 3. Install the pieces
First warn about two macOS dialogs:
- a **password** dialog to install BlackHole, the free virtual mic the agent speaks through;
- **"voy-tap would like to record audio"**: that's how the agent hears the meeting. They click **Allow**.
  It usually appears during the first check, so the audio check fails once. That's expected.

Then call `voy_setup(...)` with the values from step 2, or `voy_setup()` if the config already passed. For
each failing item, give its `hint` in one line and fix what you can. Once they've clicked Allow, call
`voy_setup_check` again. Repeat until everything passes ("Google Chrome" only matters for step 4).

## 4. The agent's Google Meet window (always do this step)
The agent starts calls from its own purple Chrome window, signed into a Google account. It's a separate
Chrome profile: the user's own browser is untouched. Guests see that account's name in the Meet. Call
`voy_meet_setup` and follow its `next`:
- `signed_in` false: ask them to sign into Google in the purple window that just opened (the account the
  agent should call from), then call it again.
- The first time, Chrome asks to use the microphone: they click **Allow**. Any mic is fine; VoyVoy picks
  BlackHole inside Meet.
- When `mic_ok` is true, setup is done. Prepare the tour (step 5, "Prepare first"), then send **one**
  message with: the banner below in a code block, exactly as written; one line saying the agent starts Meets
  as `account` (guests see that name; to switch, they sign out in the purple window and sign in with the
  other account); and the tour offer from step 5. One message, one answer from the user.
- If they don't want Google Meet (they'll only hand over calls they're already in) or can't install Chrome:
  skip to step 6, then show the banner there, without the account line or the tour.

```
             ▄████▄
            █████▄█▀█▄▄     ¡voy, voy!
            ████████▀▀
     ▄▄▄▄▄▄██████████▄      VoyVoy is ready.
  ▄███████████████████      Your agent can call people now.
█████████████████████▀
 ▀▀████████████████▀▀
          ▄█  ▄█
```

## 5. The first call: a short live tour (recommended)
This is the moment the user sees what VoyVoy does: make it a short, scripted tour, never a quiz.

**Prepare first (before offering):** look at the folder this session runs in (`ls`; `git log -3 --oneline`
if it's a repo).
- **A project:** write a one-sentence, plain-language summary of it, and pick one demo question you can
  answer well from it, such as "What changed most recently?" or "What does this app do?". Work out your
  answer now, as one or two spoken sentences.
- **No project** (empty folder, home folder): the tour skips the code demo. Tell the user once that the
  code part shines when Claude Code runs inside a project.

The offer (sent with the banner in step 4): "Want to meet your agent? It calls you on Google Meet: join from
your phone, and it'll show you what it can do." If yes:
1. Say what's about to happen in two lines: you start a Meet, they join from their phone, the agent talks
   and you (Claude) answer its questions live. The link takes about 10 seconds. Tip: `voy watch` in a
   terminal split shows the transcript and latency as it happens.
2. Call `voy_call_start` with `meet="new"`, `self_call=true`, **no `contact`** (the agent greets them by the
   name Meet shows), one goal: "What's your favorite color?", and this context (with a project):

   "A short intro call for the person who just set you up. Don't ask if they can hear you, and don't repeat
   that you're their AI agent (your first line said it). Take it one beat at a time; after each beat, stop
   and let them reply:
   1) Say what you do in one sentence and offer a demo: 'Claude Code sends me to talk to people for you and
   bring the answers back. Want a quick demo?'
   2) The thinking brain: 'While I talk, I can ask Claude Code about your code. Let me ask it <demo
   question, about <project name>>.' Call ask_engineer with that question, say it's checking their project
   right now, and say nothing else until the answer arrives. Give the answer in a sentence.
   3) The other way around: 'Now I'll take something back to Claude Code. Just to try it: what's your
   favorite color?' When they answer, call wrap_up right away (its goodbye says you'll bring it back).
   If they ask what you can do: you call people for them (a PM, a client, a teammate) or take over a call
   they're already in, and Claude Code answers code questions while you talk. One sentence. Their project:
   <summary>. Warm and relaxed, no promises."

   With no project: beat 1 ends with 'Want to try it?', skip beat 2, and leave out the project line.
3. Show the link the moment it returns, in a short message by itself. They join **from their phone** (Meet
   app or browser), not from this Mac: the agent would hear itself.
4. Run the call like `/voy:call` step 3, and narrate in one line each: "Waiting for you to join…", "The
   agent asked me '…'. Answering from your project.", "Wrapping up." Answer the demo question at once with
   the answer you prepared.
5. After the call, close the loop in a few lines: "Your agent brought back: favorite color, <answer>." Add
   the voice-to-voice latency (`latency_ms`) and where the record is (`record_path`). That's the whole idea:
   next time Claude needs an answer from someone, it can call them. With no project, add that running
   setup from a project folder also shows the agent asking Claude about the code mid-call.
6. If it didn't work, ask: did you hear the agent, and did it hear you?
   - They didn't hear it: run `voy_meet_setup` again (Meet's mic in the purple window must be BlackHole 2ch).
   - It didn't hear them: run `voy_setup_check` (audio permission).
   - Anything else: the details are in `~/.voy/logs/worker.log` and `bridge.log`.

## 6. Calls they're already in (optional)
To hand over a call they're already in (Meet in their own browser, a Slack huddle, Zoom), they set that
app's microphone to **System default** once. VoyVoy switches the Mac's default mic to BlackHole only while
the agent has the call, and switches it back after.

## 7. Done
After the tour (or if they skip it), close with a few lines written for someone who'll just talk to you:
- Calls: "Ask me to call someone, or say `/voy:call` and who. I always ask before calling anyone."
- Changes: "Tell me things like 'save Ana's email', 'make the agent more formal' or 'calls in this project
  are in Spanish', and I'll update it." (That's the `/voy:customize` skill.)
