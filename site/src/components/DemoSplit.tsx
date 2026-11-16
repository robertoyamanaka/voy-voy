type Line = { who?: string; text: string; kind: string };

const CALL: Line[] = [
  { kind: "event", text: "── Sam joined ──" },
  { kind: "agent", who: "AGENT", text: "Hi Sam, I'm Yama's AI agent." },
  { kind: "them", who: "SAM", text: "Hi! Is this about the landing?" },
  { kind: "agent", who: "AGENT", text: "Yes. It needs two things from you: the font and the main color." },
  { kind: "lat", text: "1.41 s" },
  { kind: "them", who: "SAM", text: "Hm. What are we using right now?" },
  { kind: "ask", who: "?", text: "What font and color does the landing use now?  → Claude Code" },
  { kind: "agent", who: "AGENT", text: "Good question. Let me check the code." },
  { kind: "agent", who: "AGENT", text: "Helvetica for the headings, with a blue accent." },
  { kind: "lat", text: "1.52 s" },
  { kind: "them", who: "SAM", text: "Too plain. Chakra Petch, and make it orange." },
  { kind: "ok", who: "✓", text: "font: Chakra Petch · main color: orange" },
  { kind: "event", text: "── call ended ──" },
];

const CODE: Line[] = [
  { kind: "you", who: ">", text: "polish the landing for launch" },
  { kind: "claude", who: "●", text: "Font and color are Sam's call. Want me to call Sam?" },
  { kind: "you", who: ">", text: "yes" },
  { kind: "tool", who: "●", text: "voy_call_start  contact: Sam · meet: new" },
  { kind: "meta", text: "meet.google.com/kfp-zmqa-rdw · invite sent to Sam" },
  { kind: "tool", who: "●", text: "voy_call_wait" },
  { kind: "meta", text: "Sam asked: “What are we using right now?”" },
  { kind: "tool", who: "●", text: "Read src/app/globals.css" },
  { kind: "claude", who: "●", text: "voy_call_answer  “Helvetica for the headings, with a blue accent.”" },
  { kind: "meta", text: "Call ended · 2 of 2 goals answered" },
  { kind: "claude", who: "●", text: "Switching the headings to Chakra Petch and the accent to orange." },
  { kind: "tool", who: "●", text: "Update src/app/globals.css" },
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
        <span>Yama&apos;s Claude Code asks Sam, the designer, about the landing</span>
        <span className="median">median 1.46 s voice-to-voice</span>
      </div>
      <div className="panes">
        <Pane title="The call" sub="voy watch" tone="talker" lines={CALL} offset={0} />
        <Pane title="Claude Code" sub="~/voyvoy-landing" tone="reasoner" lines={CODE} offset={1} />
      </div>
    </figure>
  );
}
