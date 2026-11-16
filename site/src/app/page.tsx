import { CommandBox } from "@/components/CommandBox";
import { DemoSplit } from "@/components/DemoSplit";
import { Pixel } from "@/components/Pixel";
import { ProductChip } from "@/components/ProductChip";
import { ThemeToggle } from "@/components/ThemeToggle";
import { GITHUB_URL, INSTALL, REPO, VERSION } from "@/lib/site";
import { PIGEON_A, PIGEON_B, PIGEON_PALETTE, WORDMARK, WORDMARK_PALETTE } from "@/lib/sprites";

function GitHubMark() {
  return (
    <svg width="18" height="18" viewBox="0 0 16 16" aria-hidden="true" fill="currentColor">
      <path d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82.64-.18 1.32-.27 2-.27.68 0 1.36.09 2 .27 1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.013 8.013 0 0016 8c0-4.42-3.58-8-8-8z" />
    </svg>
  );
}

function Logo({ scale = 3 }: { scale?: number }) {
  return (
    <a className="logo" href="#top" aria-label="VoyVoy home">
      <Pixel frames={[PIGEON_A]} palette={PIGEON_PALETTE} scale={scale / 2} />
      <Pixel frames={[WORDMARK]} palette={WORDMARK_PALETTE} scale={scale} />
    </a>
  );
}

const SPECS: [string, string][] = [
  ["Starts the call", "Opens a Google Meet in its own purple Chrome window, waits for them, and greets them by name."],
  ["Or takes yours", "Hand over the call you're already in, in Google Meet or a Slack huddle."],
  ["Answers from your code", "Questions only the code can answer go to Claude Code mid-call, and come back in plain words."],
  ["Your keys, your Mac", "Runs on your own LiveKit project. There's no VoyVoy server in the middle."],
  ["Silent on your Mac", "The call never plays through your speakers, so you keep working while it talks."],
  ["English and Spanish", "Spanglish and tech jargon come through fine."],
  ["Always disclosed", "Its first words say it's an AI. No setting turns that off."],
  ["Notes for Claude", "Every call lands in .voy/calls/ with the answers, ready to act on."],
  ["Yours to shape", "A markdown playbook sets how it sounds. Updates improve the rest and never touch your file."],
];

const STACK: { part: string; full: string; model: string; note: string; tone: "talker" | "reasoner" }[] = [
  { part: "STT", full: "speech-to-text", model: "deepgram/nova-3", note: "hears English, Spanish, and both at once", tone: "talker" },
  { part: "LLM", full: "the talker", model: "google/gemini-2.5-flash", note: "about 0.4 s to its first word", tone: "talker" },
  { part: "TTS", full: "the voice", model: "inworld/inworld-tts-2", note: "Edward in English, Daniela in Spanish", tone: "talker" },
  { part: "Reasoner", full: "the brain", model: "your Claude Code session", note: "over MCP: ask · answer · steer", tone: "reasoner" },
];

const TIMELINE: { title: string; text: string; who: "reasoner" | "talker" | "voy" }[] = [
  { title: "Prepare", text: "Claude reads the code that matters, writes the goals, and finds the person.", who: "reasoner" },
  { title: "Call", text: "VoyVoy opens a Meet in its own window. Claude shows you the link, or sends the invite.", who: "voy" },
  { title: "Talk", text: "They join. The agent says it's an AI and works through the goals.", who: "talker" },
  { title: "Delegate", text: "A code question goes to Claude. The agent keeps talking while it checks.", who: "reasoner" },
  { title: "Wrap up", text: "It recaps the answers, waits for their OK, and says goodbye.", who: "talker" },
  { title: "Back to work", text: "The notes land in your session, and Claude makes the change.", who: "reasoner" },
];

export default function Home() {
  return (
    <>
      <header className="nav">
        <div className="wrap nav-inner">
          <Logo />
          <nav className="nav-links" aria-label="Sections">
            <a href="#how">How it works</a>
            <a href="#timeline">A call</a>
            <a href="#roadmap">Roadmap</a>
          </nav>
          <div className="nav-tools">
            <ThemeToggle />
            <a className="icon-btn" href={GITHUB_URL} aria-label="VoyVoy on GitHub">
              <GitHubMark />
            </a>
            <a className="btn btn-primary btn-small" href="#install">
              Install
            </a>
          </div>
        </div>
      </header>

      <main id="top">
        <section className="wrap hero">
          <div className="mascot rise" aria-hidden="true">
            <Pixel frames={[PIGEON_A, PIGEON_B]} palette={PIGEON_PALETTE} scale={4} className="bob" />
            <span className="bubble">¡voy, voy!</span>
          </div>
          <a className="tag rise" style={{ ["--d" as string]: 1 }} href={`${GITHUB_URL}/releases`}>
            Open source · MIT · {VERSION} <span aria-hidden="true">↗</span>
          </a>
          <h1 className="rise" style={{ ["--d" as string]: 2 }}>
            Let Claude Code <em>call people.</em>
          </h1>
          <p className="lede rise" style={{ ["--d" as string]: 3 }}>
            A Claude Code plugin for macOS. Claude starts a call on <ProductChip product="meet" /> or{" "}
            <ProductChip product="zoom" soon /> and invites the person. A voice agent asks them your questions, and
            Claude answers anything about your code mid-call. When they hang up, the answers are back in your session.
          </p>
          <div className="hero-cta rise" style={{ ["--d" as string]: 4 }}>
            <CommandBox command={INSTALL[0]} />
            <a className="btn btn-ghost" href={GITHUB_URL}>
              <GitHubMark /> GitHub
            </a>
          </div>
          <p className="then rise" style={{ ["--d" as string]: 4 }}>
            then <code>{INSTALL[1]}</code> and <code>{INSTALL[2]}</code> in Claude Code
          </p>
        </section>

        <section className="wrap demo-wrap rise" style={{ ["--d" as string]: 5 }} aria-label="An example call">
          <DemoSplit />
        </section>

        <section className="section" aria-labelledby="specs-title">
          <div className="wrap">
            <div className="section-head">
              <span className="eyebrow">What it does</span>
              <h2 id="specs-title">A phone for Claude Code.</h2>
            </div>
            <dl className="specs">
              {SPECS.map(([title, text]) => (
                <div key={title}>
                  <dt>{title}</dt>
                  <dd>{text}</dd>
                </div>
              ))}
            </dl>
          </div>
        </section>

        <section className="section" id="how" aria-labelledby="brains">
          <div className="wrap how">
            <div className="section-head">
              <span className="eyebrow">How it works</span>
              <h2 id="brains">
                Two brains on every call.
              </h2>
              <p>
                Voice needs speed and your codebase needs depth, so VoyVoy splits the job. A fast{" "}
                <strong className="talker">talker</strong> runs the conversation on LiveKit. The slow{" "}
                <strong className="reasoner">reasoner</strong> is the Claude Code session you&apos;re already in, with
                your whole repo in context.
              </p>
              <p className="footnote">
                It&apos;s the <a href="https://arxiv.org/abs/2410.08328">Talker–Reasoner pattern</a> from Google
                DeepMind, built on LiveKit&apos;s{" "}
                <a href="https://docs.livekit.io/agents/logic/patterns/subagent-delegation/">subagent delegation</a>.
                The twist: the reasoner isn&apos;t another model call. It&apos;s you, plus Claude.
              </p>
            </div>
            <div className="stack">
              <table>
                <caption className="sr-only">What runs each part of a call</caption>
                <tbody>
                  {STACK.map((s) => (
                    <tr key={s.part} className={`row-${s.tone}`}>
                      <th scope="row">
                        {s.part} <span>({s.full})</span>
                      </th>
                      <td>
                        <code>{s.model}</code>
                        <small>{s.note}</small>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <p className="stack-foot">
                Swap any line in <code>~/.voy/config.toml</code>. Voice-to-voice is about 1.5 s, measured on your Mac.
              </p>
            </div>
          </div>
        </section>

        <section className="section" id="timeline" aria-labelledby="timeline-title">
          <div className="wrap">
            <div className="section-head">
              <span className="eyebrow">A call, start to finish</span>
              <h2 id="timeline-title">From /voy:call to a finished change.</h2>
              <p className="legend">
                <span className="key key-reasoner">Claude Code</span>
                <span className="key key-talker">the talker</span>
                <span className="key key-voy">VoyVoy</span>
              </p>
            </div>
            <ol className="timeline">
              {TIMELINE.map((t) => (
                <li key={t.title} className={`tl-${t.who}`}>
                  <strong>{t.title}</strong>
                  <span>{t.text}</span>
                </li>
              ))}
            </ol>
          </div>
        </section>

        <section className="section" id="install" aria-labelledby="install-title">
          <div className="wrap install">
            <div className="section-head">
              <span className="eyebrow">Install</span>
              <h2 id="install-title">Three commands, all inside Claude Code.</h2>
              <p>
                You need a Mac with macOS 14.2 or later, Google Chrome and a free{" "}
                <a href="https://cloud.livekit.io">LiveKit Cloud</a> project. Setup handles the rest.
              </p>
            </div>
            <div>
              <ol className="cmds">
                {INSTALL.map((c) => (
                  <li key={c}>
                    <CommandBox command={c} />
                  </li>
                ))}
              </ol>
              <div className="setup-notes">
                <p>
                  <code>/voy:setup</code> walks you through it from the chat:
                </p>
                <ul>
                  <li>installs the voy command line and asks for your first name and LiveKit keys;</li>
                  <li>builds the audio helper and installs BlackHole, the free virtual mic your agent speaks through (signature checked);</li>
                  <li>opens the purple VoyVoy agent window so you sign into Google once;</li>
                  <li>ends with a short live tour: your agent calls you on Meet, says what it is, and asks Claude Code about your project live.</li>
                </ul>
              </div>
              <details>
                <summary>Prefer the terminal?</summary>
                <ol className="cmds">
                  <li>
                    <CommandBox command="uv tool install voyvoy" />
                  </li>
                  <li>
                    <CommandBox command="voy init" />
                  </li>
                  <li>
                    <CommandBox command="voy doctor" />
                  </li>
                </ol>
              </details>
            </div>
          </div>
        </section>

        <section className="section" id="roadmap" aria-label="Principles and roadmap">
          <div className="wrap split">
            <div>
              <h2>Principles</h2>
              <dl className="principles">
                <div>
                  <dt>Always disclosed.</dt>
                  <dd>
                    The first words of every call say it&apos;s an AI. Code speaks that line, not the model, and there&apos;s
                    no setting to turn it off.
                  </dd>
                </div>
                <div>
                  <dt>Never calls without your yes.</dt>
                  <dd>Claude asks before calling anyone, and the invite says an AI agent is joining.</dd>
                </div>
                <div>
                  <dt>Call content isn&apos;t a command.</dt>
                  <dd>
                    What people say reaches Claude as their request, never as instructions. Claude Code&apos;s
                    permissions still apply.
                  </dd>
                </div>
                <div>
                  <dt>Local first.</dt>
                  <dd>
                    Audio goes from your Mac to your own LiveKit project. The agent&apos;s Chrome window is a separate
                    profile that never touches yours.
                  </dd>
                </div>
              </dl>
            </div>
            <div className="roadmap">
              <h2>Roadmap</h2>
              <div>
                <h3 className="eyebrow">Next</h3>
                <ul>
                  <li>Gemini Live speech-to-speech as an option</li>
                  <li>A menu-bar light that shows when a call is on</li>
                  <li>A signed audio helper, so permissions survive updates</li>
                  <li>One-line install from PyPI</li>
                </ul>
              </div>
              <div>
                <h3 className="eyebrow">Later</h3>
                <ul>
                  <li>Your own voice, with a consent check</li>
                  <li>Phone calls and WhatsApp</li>
                  <li>Slack huddles started by the agent</li>
                  <li>More languages, and harnesses beyond Claude Code</li>
                </ul>
              </div>
            </div>
          </div>
        </section>

        <section className="section cta" aria-labelledby="cta-title">
          <div className="wrap cta-inner">
            <h2 id="cta-title">
              Install it in <em>Claude Code.</em>
            </h2>
            <div className="hero-cta">
              <CommandBox command={INSTALL[0]} />
              <a className="btn btn-primary" href="#install">
                Install guide
              </a>
            </div>
          </div>
        </section>
      </main>

      <footer className="footer">
        <div className="track" aria-hidden="true">
          <div className="walker">
            <Pixel frames={[PIGEON_A, PIGEON_B]} palette={PIGEON_PALETTE} scale={3} />
          </div>
        </div>
        <div className="wrap foot">
          <div>
            <Logo scale={2} />
            <p>
              <dfn>voy, voy</dfn> (Spanish): &ldquo;coming, coming!&rdquo;, what you shout when someone calls you.
            </p>
            <p>Not affiliated with LiveKit, Google or Anthropic.</p>
          </div>
          <nav aria-label="Footer">
            <a href={GITHUB_URL}>GitHub</a>
            <a href={`${GITHUB_URL}/blob/main/LICENSE`}>MIT license</a>
            <a href="#install">Install</a>
          </nav>
        </div>
      </footer>
    </>
  );
}
