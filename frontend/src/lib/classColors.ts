// Same colours as the boxes in the annotated video. The backend (app/pipeline/visualizer.py)
// derives a hue from zlib.crc32(class_name) % 360 with saturation 0.75 and value 0.95.

const CRC_TABLE = (() => {
  const table = new Uint32Array(256);
  for (let n = 0; n < 256; n++) {
    let c = n;
    for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1;
    table[n] = c >>> 0;
  }
  return table;
})();

function crc32(text: string): number {
  const bytes = new TextEncoder().encode(text);
  let crc = 0xffffffff;
  for (const b of bytes) crc = CRC_TABLE[(crc ^ b) & 0xff] ^ (crc >>> 8);
  return (crc ^ 0xffffffff) >>> 0;
}

function hsvToHex(h: number, s: number, v: number): string {
  const i = Math.floor(h * 6);
  const f = h * 6 - i;
  const p = v * (1 - s);
  const q = v * (1 - f * s);
  const t = v * (1 - (1 - f) * s);
  const [r, g, b] = [
    [v, t, p], [q, v, p], [p, v, t], [p, q, v], [t, p, v], [v, p, q],
  ][i % 6];
  const hex = (x: number) => Math.round(x * 255).toString(16).padStart(2, "0");
  return `#${hex(r)}${hex(g)}${hex(b)}`;
}

const cache = new Map<string, string>();

export function classColor(className: string): string {
  if (className === "Unresolved") return "var(--muted)";
  let color = cache.get(className);
  if (!color) {
    color = hsvToHex((crc32(className) % 360) / 360, 0.75, 0.95);
    cache.set(className, color);
  }
  return color;
}

/** Short label for the sequence strip. */
export function classAbbreviation(className: string): string {
  const known: Record<string, string> = { Locomotive: "LOCO", Brake_Van: "BV", Flat_Wagon: "FLAT", Unresolved: "?" };
  return known[className] ?? className;
}
