type Line = { who?: string; text: string; kind: string };

const CALL: Line[] = [
  { kind: "event", text: "── Ana Ruiz joined ──" },
  { kind: "agent", who: "AGENT", text: "Hi Ana, I'm Sam's AI agent." },
  { kind: "them", who: "ANA", text: "Ha, okay. Hi! So, the onboarding form?" },
  { kind: "agent", who: "AGENT", text: "Sam wants to shorten it. Which fields have to stay?" },
  { kind: "lat", text: "1.41 s" },
  { kind: "them", who: "ANA", text: "Email and company size. Do we even store company size?" },
  { kind: "ask", who: "?", text: "Do we already store company size?  → Claude Code" },
  { kind: "agent", who: "AGENT", text: "Good question. Let me check Sam's code." },
  { kind: "agent", who: "AGENT", text: "We do. It's saved already, just optional." },
  { kind: "lat", text: "1.52 s" },
  { kind: "them", who: "ANA", text: "Then make it required. And drop phone." },
  { kind: "ok", who: "✓", text: "fields: email + company size (required), no phone" },
  { kind: "event", text: "── call ended ──" },
];

const CODE: Line[] = [
  { kind: "you", who: ">", text: "/voy:call ask Ana which onboarding fields she wants" },
  { kind: "tool", who: "●", text: "voy_call_start  contact: Ana · meet: new" },
  { kind: "meta", text: "meet.google.com/kfp-zmqa-rdw · invite sent to Ana" },
  { kind: "tool", who: "●", text: "voy_call_wait" },
  { kind: "meta", text: "Ana asked: “Do we even store company size?”" },
  { kind: "tool", who: "●", text: "Read src/models/account.ts" },
  { kind: "claude", who: "●", text: "voy_call_answer  “Yes, on the Account model. Optional today.”" },
  { kind: "tool", who: "●", text: "voy_call_wait" },
  { kind: "meta", text: "Call ended · 3 of 3 goals answered" },
  { kind: "meta", text: "→ .voy/calls/2026-11-16-1030-ana.md" },
  { kind: "claude", who: "●", text: "Making company size required, removing phone." },
  { kind: "tool", who: "●", text: "Update src/onboarding/StepTwo.tsx" },
];

function Pane({ title, sub, tone, lines, offset }: { title: string; sub: string; tone: string; lines: Line[]; offset: number }) {
  return (
    <div className={`pane pane-${tone}`}>
      <div className="pane-head">
        <span className="pane-title">{title}</span>
        <span>{sub}</span>
      </div>
      <ol className="lines">
        {lines.map((l, i) => (
          <li key={i} className={`ln ln-${l.kind}`} style={{ ["--i" as string]: i * 2 + offset }}>
            {l.who && <span className="who">{l.who}</span>}
            <span className="txt">{l.text}</span>
          </li>
        ))}
      </ol>
    </div>
  );
}

/** The two brains at work, side by side: the call on the left, Claude Code on the right. */
export function DemoSplit() {
  return (
    <figure className="split-demo">
      <div className="split-bar">
        <span className="live">Example call</span>
        <span>Sam&apos;s Claude Code asks Ana, the PM, what to change</span>
        <span className="median">median 1.46 s voice-to-voice</span>
      </div>
      <div className="panes">
        <Pane title="The call" sub="voy watch" tone="talker" lines={CALL} offset={0} />
        <Pane title="Claude Code" sub="~/acme-app" tone="reasoner" lines={CODE} offset={1} />
      </div>
    </figure>
  );
}
