// Renders the social card (public/og.png, 1200x630 at 2x) from og/card.html with headless Chrome.
//   npm run og
import { execFileSync } from "node:child_process";
import { mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { PIGEON_A, PIGEON_PALETTE, WORDMARK, WORDMARK_PALETTE, type Palette } from "../src/lib/sprites.ts";

const root = new URL("..", import.meta.url).pathname;
const CHROME = process.env.CHROME ?? "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";

function pixel(rows: string[], palette: Palette, scale: number, cls = ""): string {
  const rects: string[] = [];
  rows.forEach((row, y) => {
    let x = 0;
    while (x < row.length) {
      const c = row[x];
      let end = x + 1;
      while (end < row.length && row[end] === c) end++;
      if (palette[c]) rects.push(`<rect x="${x}" y="${y}" width="${end - x}" height="1" fill="${palette[c]}"/>`);
      x = end;
    }
  });
  const w = rows[0].length, h = rows.length;
  return `<svg class="${cls}" width="${w * scale}" height="${h * scale}" viewBox="0 0 ${w} ${h}" shape-rendering="crispEdges">${rects.join("")}</svg>`;
}

const MEET = `<svg width="22" height="22" viewBox="0 0 24 24"><path fill="#EA4335" d="M5.53 2.13 0 7.75h5.53z"/><path fill="#FFBA00" d="M5.928 2.13v5.62h7.608v3.65l5.47-4.45c-.014-1.22.031-2.25-.025-3.46-.148-1.09-1.287-1.47-2.236-1.36z"/><path fill="#00AC47" d="M23.1 4.32c-.802.295-1.358.995-2.047 1.49-2.506 2.05-4.982 4.12-7.468 6.19 3.025 2.59 6.04 5.18 9.065 7.76 1.218.671 1.428-.814 1.328-1.64v-13a.828.828 0 0 0-.877-.825z"/><path fill="#2684FC" d="M.038 8.15v7.7h5.53v-7.7z"/><path fill="#00832D" d="M13.615 16.25H6.008v5.62c3.864-.006 7.737.011 11.58-.009 1.02-.07 1.618-1.12 1.468-2.07v-2.51l-5.47-4.68v3.65z"/><path fill="#0066DA" d="M.038 16.25c.02 1.44-.041 2.88.033 4.31.162.948 1.158 1.43 2.047 1.31h3.464v-5.62z"/></svg>`;
const ZOOM = `<svg width="22" height="22" viewBox="0 0 24 24"><rect width="24" height="24" rx="6" fill="#0B5CFF"/><rect x="4.5" y="8" width="10.5" height="8" rx="2" fill="#fff"/><path d="M15.8 11.1 19.5 8.6v6.8l-3.7-2.5z" fill="#fff"/></svg>`;

// a scatter of pixel stars: [x, y, size, tone]
const STARS: [number, number, number, string][] = [
  [612, 46, 4, "dim"], [700, 132, 4, "dim"], [1012, 38, 6, "blue"], [1140, 120, 4, "dim"], [560, 300, 4, "dim"],
  [1160, 300, 4, "red"], [640, 580, 4, "dim"], [36, 40, 4, "dim"], [1088, 590, 6, "dim"], [520, 120, 6, "red"],
  [860, 30, 4, "dim"], [36, 590, 4, "blue"],
];

const html = `<!doctype html>
<html><head><meta charset="utf-8">
<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Chakra+Petch:wght@600;700&family=Hanken+Grotesk:wght@400;500;600&family=Kode+Mono:wght@400;500;600&display=block" rel="stylesheet">
<style>
:root {
  --bg: oklch(0.155 0.006 255); --sunk: oklch(0.125 0.006 255); --line: oklch(0.28 0.01 255);
  --text: oklch(0.96 0.004 255); --text-2: oklch(0.78 0.01 255); --text-3: oklch(0.6 0.012 255);
  --red: oklch(0.68 0.2 33); --blue: oklch(0.82 0.13 216);
  --px-ink: oklch(0.09 0.006 255); --px-light: oklch(0.86 0.012 255); --px-mid: oklch(0.69 0.016 255);
  --px-dark: oklch(0.48 0.02 255); --px-sheen: oklch(0.82 0.13 216); --px-violet: oklch(0.56 0.17 292); --px-white: oklch(0.985 0.003 255);
}
* { box-sizing: border-box; margin: 0; }
html, body { width: 1200px; height: 630px; overflow: hidden; }
body {
  position: relative; background: var(--bg); color: var(--text); font-family: "Hanken Grotesk", sans-serif;
  background-image: radial-gradient(color-mix(in oklch, var(--text) 9%, transparent) 1px, transparent 1.2px);
  background-size: 24px 24px; background-position: 12px 12px;
}
svg { display: block; }
.star { position: absolute; }
.star.dim { background: color-mix(in oklch, var(--text) 30%, transparent); }
.star.red { background: var(--red); } .star.blue { background: var(--blue); }

.left { position: absolute; left: 72px; top: 64px; width: 560px; }
.eyebrow { display: flex; align-items: center; gap: 12px; font: 500 17px "Kode Mono", monospace; letter-spacing: .16em; text-transform: uppercase; color: var(--text-3); }
.eyebrow i { width: 10px; height: 10px; background: var(--red); }
.wordmark { margin-top: 30px; color: var(--text); }
h1 { margin-top: 34px; font: 700 70px/0.98 "Chakra Petch", sans-serif; letter-spacing: -0.02em; }
h1 em { font-style: normal; color: var(--red); }
.chips { display: flex; align-items: center; gap: 10px; margin-top: 30px; font: 500 22px "Hanken Grotesk"; color: var(--text-2); }
.chip { display: inline-flex; align-items: center; gap: 8px; padding: 4px 14px 4px 9px; border-radius: 999px; font-weight: 600; font-size: 21px; }
.chip.meet { background: color-mix(in oklch, #00897b 14%, transparent); border: 1.5px solid color-mix(in oklch, #00897b 45%, transparent); color: oklch(0.82 0.1 178); }
.chip.zoom { background: color-mix(in oklch, #0b5cff 16%, transparent); border: 1.5px solid color-mix(in oklch, #0b5cff 50%, transparent); color: oklch(0.78 0.13 262); }
.chip small { padding-left: 9px; border-left: 1.5px solid color-mix(in oklch, #0b5cff 50%, transparent); font: 500 13px "Kode Mono"; letter-spacing: .14em; text-transform: uppercase; opacity: .85; }
.url { position: absolute; left: 72px; bottom: 54px; display: flex; align-items: center; gap: 10px; font: 600 30px "Kode Mono", monospace; letter-spacing: 0.02em; }
.url b { width: 15px; height: 30px; background: var(--red); }

.scene { position: absolute; right: 64px; top: 0; width: 470px; height: 630px; }
.pigeon { position: absolute; left: 70px; top: 154px; } /* feet on the card's top edge */
.bubble { position: absolute; left: 252px; top: 108px; padding: 10px 16px; background: var(--text); color: var(--bg); font: 600 22px "Kode Mono", monospace;
  box-shadow: 0 -4px 0 0 var(--text), 0 4px 0 0 var(--text), -4px 0 0 0 var(--text), 4px 0 0 0 var(--text); }
.bubble::after { content: ""; position: absolute; left: -16px; bottom: -4px; width: 12px; height: 12px; background: var(--text);
  box-shadow: -6px 6px 0 -1px var(--text); }
.card { position: absolute; left: 0; right: 0; top: 272px; border: 1.5px solid var(--line); border-radius: 12px; background: var(--sunk); overflow: hidden; }
.card-head { display: flex; align-items: center; gap: 10px; padding: 12px 18px; border-bottom: 1.5px solid var(--line); font: 500 14px "Kode Mono", monospace; letter-spacing: .14em; text-transform: uppercase; color: var(--text-2); }
.card-head .dot { width: 10px; height: 10px; background: var(--red); }
.card-head .meet { margin-left: auto; display: flex; align-items: center; gap: 8px; letter-spacing: .04em; text-transform: none; color: var(--text-3); }
.card-head .meet svg { width: 18px; height: 18px; }
.lines { padding: 14px 18px 16px; display: grid; gap: 7px; font: 400 17px/1.35 "Kode Mono", monospace; color: var(--text-2); }
.ln { display: grid; grid-template-columns: 7.2ch 1fr; }
.who { color: var(--text-3); }
.agent .who { color: var(--red); } .agent .txt { color: var(--text); }
.them .who { color: var(--text); }
.claude .who, .claude .txt { color: var(--blue); }
.lat { display: flex; justify-content: flex-end; font-size: 14px; color: var(--text-3); }
</style></head>
<body>
${STARS.map(([x, y, s, t]) => `<i class="star ${t}" style="left:${x}px;top:${y}px;width:${s}px;height:${s}px"></i>`).join("")}
<div class="left">
  <div class="eyebrow"><i></i>Open source · Claude Code plugin</div>
  <div class="wordmark">${pixel(WORDMARK, WORDMARK_PALETTE, 10)}</div>
  <h1>Let Claude Code<br><em>call people.</em></h1>
  <div class="chips">on <span class="chip meet">${MEET}Google Meet</span> <span class="chip zoom">${ZOOM}Zoom<small>soon</small></span></div>
</div>
<div class="url">voyvoy.sh<b></b></div>
<div class="scene">
  <div class="pigeon">${pixel(PIGEON_A, PIGEON_PALETTE, 7)}</div>
  <div class="bubble">¡voy, voy!</div>
  <div class="card">
    <div class="card-head"><i class="dot"></i>Live call<span class="meet">${MEET}Google Meet</span></div>
    <div class="lines">
      <div class="ln agent"><span class="who">AGENT</span><span class="txt">Hi Ana, I'm Sam's AI agent.</span></div>
      <div class="ln them"><span class="who">ANA</span><span class="txt">Do we store company size?</span></div>
      <div class="ln claude"><span class="who">CLAUDE</span><span class="txt">Yes, on the Account model.</span></div>
      <div class="ln agent"><span class="who">AGENT</span><span class="txt">We do, it's already saved.</span></div>
      <div class="lat">voice-to-voice 1.41 s</div>
    </div>
  </div>
</div>
</body></html>`;

const card = join(root, "og", "card.html");
writeFileSync(card, html);
const profile = mkdtempSync(join(tmpdir(), "voy-og-"));
execFileSync(CHROME, [
  "--headless=new", "--disable-gpu", "--hide-scrollbars", `--user-data-dir=${profile}`,
  "--window-size=1200,630", "--force-device-scale-factor=2", "--virtual-time-budget=8000",
  `--screenshot=${join(root, "public", "og.png")}`, `file://${card}`,
], { stdio: "ignore" });
console.log("wrote public/og.png from og/card.html");
