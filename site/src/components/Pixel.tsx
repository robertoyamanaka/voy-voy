import type { Palette } from "@/lib/sprites";

/** Merge each row into horizontal runs of one color: far fewer rects than one per pixel. */
function runs(rows: string[], palette: Palette) {
  const out: { x: number; y: number; w: number; fill: string }[] = [];
  rows.forEach((row, y) => {
    let x = 0;
    while (x < row.length) {
      const c = row[x];
      let end = x + 1;
      while (end < row.length && row[end] === c) end++;
      if (palette[c]) out.push({ x, y, w: end - x, fill: palette[c] });
      x = end;
    }
  });
  return out;
}

export function PixelFrame({ rows, palette, className }: { rows: string[]; palette: Palette; className?: string }) {
  return (
    <g className={className}>
      {runs(rows, palette).map((r, i) => (
        <rect key={i} x={r.x} y={r.y} width={r.w} height={1} fill={r.fill} />
      ))}
    </g>
  );
}

type Props = {
  frames: string[][];
  palette: Palette;
  scale: number;
  label?: string;
  className?: string;
};

/** Pixel art as crisp SVG. Several frames = a sprite animation (styled in CSS by frame index). */
export function Pixel({ frames, palette, scale, label, className }: Props) {
  const w = frames[0][0].length;
  const h = frames[0].length;
  return (
    <svg
      className={className}
      width={w * scale}
      height={h * scale}
      viewBox={`0 0 ${w} ${h}`}
      shapeRendering="crispEdges"
      role={label ? "img" : undefined}
      aria-label={label}
      aria-hidden={label ? undefined : true}
    >
      {frames.map((rows, i) => (
        <PixelFrame key={i} rows={rows} palette={palette} className={frames.length > 1 ? `frame frame-${i}` : undefined} />
      ))}
    </svg>
  );
}
