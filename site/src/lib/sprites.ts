// 8-bit art as rows of characters. Each character maps to a CSS color variable,
// so the sprites follow the light/dark theme.

export type Palette = Record<string, string>;

export const PIGEON_PALETTE: Palette = {
  k: "var(--px-ink)",
  a: "var(--px-light)",
  s: "var(--px-mid)",
  d: "var(--px-dark)",
  b: "var(--px-dark)",
  n: "var(--px-sheen)",
  m: "var(--px-violet)",
  w: "var(--px-white)",
  e: "var(--red)",
};

// Facing right. Frame B pushes the head forward a pixel: together they make the pigeon head-bob.
export const PIGEON_A = [
  "........................",
  "..............kkkk......",
  ".............kaaaak.....",
  "............kaaaaeakk...",
  "............kaaaaaawbbk.",
  "............knnaaaakkk..",
  "............knnnaaak....",
  "...........knnmnnaaak...",
  ".....kkkkkknnmmnnaaaak..",
  "...kkssssssknnnnaaaaak..",
  "..ksssdsssdsknaaaaaaak..",
  "kkssssdsssdssaaaaaaaak..",
  "kddssssdsssdsaaaaaaak...",
  ".kkdddsssssssaaaaaakk...",
  "...kkkkkkkkkkkkkkkk.....",
  "...........e...e........",
  "..........ee..ee........",
];

export const PIGEON_B = PIGEON_A.map((row, y) => {
  if (y >= 1 && y <= 5) return "." + row.slice(0, -1);
  if (y === 15) return "............e.e.........";
  if (y === 16) return "...........ee.ee........";
  return row;
});

// "VOYVOY" in chunky pixel letters; the second VOY is red, like the answer to a call ("¡voy, voy!").
const V = ["kk..kk", "kk..kk", "kk..kk", "kk..kk", ".kkkk.", ".kkkk.", "..kk.."];
const O = [".kkkk.", "kk..kk", "kk..kk", "kk..kk", "kk..kk", "kk..kk", ".kkkk."];
const Y = ["kk..kk", "kk..kk", ".kkkk.", "..kk..", "..kk..", "..kk..", "..kk.."];
const red = (rows: string[]) => rows.map((r) => r.replaceAll("k", "r"));

export const WORDMARK = V.map((_, y) => [V[y], O[y], Y[y], red(V)[y], red(O)[y], red(Y)[y]].join("."));
export const WORDMARK_PALETTE: Palette = { k: "currentColor", r: "var(--red)" };

export const CHECK = ["......k", ".....kk", "k...kk.", "kk.kk..", ".kkk...", "..k...."];
