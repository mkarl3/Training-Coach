import React from "react";

// Coach Wattson — live SVG sprite, ported VERBATIM from the Watt Smith brand book
// (brand/watt-smith-brand-book.html §02 + its <script>). One base, recolorable, crisp at any
// size; he always wears the cap. Do not redraw or rasterize — this is the only 8-bit thing that
// carries meaning; the data stays clean.
const S = 6;
const FACE = [[7,6,10],[8,5,12],[9,5,12],[10,5,12],[11,5,12],[12,5,12],[13,5,12],[14,6,10],[15,6,10],[16,7,8],[17,8,6],[18,9,4]];
const CAP = [[2,8,6],[3,6,10],[4,5,12],[5,5,12],[6,5,12]];
const O = "#14121f";
const sk = { b:"#e0a878", s:"#b07f50", h:"#f4cd9a" };
const DEFAULT_CAP = { m:"#e84444", d:"#a82828", l:"#ff8a8a" };
const acc = "#f0f0f0";
const DEFAULT_JAC = { m:"#3a6ad8", d:"#2444a0", l:"#5c8cde" };
const hair = "#5a3a28", brow = "#3e2618", fc = "#5a3a28", eye = "#2a2438";

// ── Easter egg: Wattson honors the Grand Tours by wearing the leader's colors ──
// Cap + jersey both recolor during each Grand Tour. No date table to maintain — the
// windows are derived from each tour's reliable weekday anchor, so it works every year
// on its own. Phases: giro→pink, tdf wk1-2→yellow, tdf wk3→polka, vuelta→red.
//   Giro:   first Saturday of May,    next 23 days
//   TDF:    first Friday of July,     next 14 days yellow, then 8 days polka
//   Vuelta: fourth Saturday of August, next 23 days

// Leader-jersey palettes { cap, jac, dots? }. dots=true → KOM polka overlay.
const TOUR_PALETTES = {
  giro:   { cap:{ m:"#e6398a", d:"#b01e68", l:"#ff7ab8" }, jac:{ m:"#e6398a", d:"#b01e68", l:"#ff7ab8" } }, // maglia rosa
  yellow: { cap:{ m:"#f7d51d", d:"#c9a800", l:"#ffe96b" }, jac:{ m:"#f7d51d", d:"#c9a800", l:"#ffe96b" } }, // maillot jaune
  polka:  { cap:{ m:"#f4f4f6", d:"#d0d0d8", l:"#ffffff" }, jac:{ m:"#f4f4f6", d:"#d0d0d8", l:"#ffffff" }, dots:true }, // maillot à pois
  vuelta: { cap:{ m:"#e8202a", d:"#a8121a", l:"#ff6066" }, jac:{ m:"#e8202a", d:"#a8121a", l:"#ff6066" } }, // la roja
};
const DEFAULT_PALETTE = { cap: DEFAULT_CAP, jac: DEFAULT_JAC };

const DAY = 86400000;
const dayDiff = (a, b) => Math.floor((a - b) / DAY);

// nth occurrence (1-based) of a weekday (0=Sun…6=Sat) in a given month (0=Jan…11=Dec).
function nthWeekdayOfMonth(year, month, weekday, n) {
  const first = new Date(year, month, 1);
  const offset = (weekday - first.getDay() + 7) % 7;
  return new Date(year, month, 1 + offset + (n - 1) * 7);
}

// Which tour phase (if any) is active on `now`. Returns a TOUR_PALETTES key or null.
function activeTourKey(now) {
  const y = now.getFullYear();
  const giro = dayDiff(now, nthWeekdayOfMonth(y, 4, 6, 1));   // 1st Saturday of May
  if (giro >= 0 && giro < 23) return "giro";
  const tdf = dayDiff(now, nthWeekdayOfMonth(y, 6, 5, 1));    // 1st Friday of July
  if (tdf >= 0 && tdf < 14) return "yellow";
  if (tdf >= 14 && tdf < 22) return "polka";
  const vuelta = dayDiff(now, nthWeekdayOfMonth(y, 7, 6, 4)); // 4th Saturday of August
  if (vuelta >= 0 && vuelta < 23) return "vuelta";
  return null;
}

export function paletteForDate(now = new Date()) {
  const key = activeTourKey(now);
  return key ? TOUR_PALETTES[key] : DEFAULT_PALETTE;
}

function rects(expr, palette = DEFAULT_PALETTE) {
  const cap = palette.cap, jac = palette.jac;
  let r = "";
  const P = (x, y, w, h, c) => { if (c) r += `<rect x="${x*S}" y="${y*S}" width="${w*S}" height="${h*S}" fill="${c}"/>`; };
  CAP.concat(FACE).forEach(([y,x,w]) => P(x-1,y,w+2,1,O)); P(7,1,8,1,O); P(3,6,16,1,O); P(9,19,4,1,O);
  FACE.forEach(([y,x,w]) => P(x,y,w,1,sk.b)); FACE.forEach(([y,x,w]) => P(x+w-1,y,1,1,sk.s)); P(5,8,1,6,sk.h);
  P(4,11,1,2,sk.b); P(17,11,1,2,sk.b); P(3,11,1,2,O); P(18,11,1,2,O);
  P(5,7,1,2,hair); P(16,7,1,2,hair);
  CAP.forEach(([y,x,w]) => P(x,y,w,1,cap.m)); CAP.forEach(([y,x,w]) => P(x+w-1,y,1,1,cap.d));
  P(6,2,2,1,cap.l); P(6,3,2,1,cap.l); P(5,4,12,1,acc);
  P(4,6,14,1,cap.l); P(4,7,14,1,cap.d);
  if (expr === "alarmed") { P(6,7,3,1,brow); P(13,7,3,1,brow); P(6,6,1,1,brow); P(15,6,1,1,brow); }
  else { P(7,8,3,1,brow); P(12,8,3,1,brow); }
  P(7,9,3,2,"#fff"); P(8,9,1,2,eye); P(12,9,3,2,"#fff"); P(13,9,1,2,eye);
  P(10,11,2,2,sk.s); P(9,12,1,1,sk.s);
  P(6,13,10,1,fc); P(7,14,8,1,fc); P(5,12,1,1,fc); P(16,12,1,1,fc);
  if (expr === "alarmed") { P(9,15,4,2,"#5a2a22"); P(10,15,2,1,"#2a1410"); }
  else if (expr === "approving") { P(8,15,6,1,"#5a2a22"); P(9,15,4,1,"#fff"); P(8,14,1,1,"#7a3b2e"); P(13,14,1,1,"#7a3b2e"); }
  else { P(9,15,4,1,"#7a3b2e"); P(8,14,1,1,"#7a3b2e"); P(13,14,1,1,"#7a3b2e"); }
  if (expr === "alarmed") { P(17,8,1,1,"#6ab4ff"); P(17,9,1,1,"#6ab4ff"); }
  if (expr === "approving") { P(2,2,1,1,"#f7d51d"); P(1,3,3,1,"#f7d51d"); P(2,4,1,1,"#f7d51d"); }
  P(7,19,8,1,sk.s); P(5,20,12,1,jac.l); P(7,20,1,2,"#f0f0f0"); P(13,20,1,2,"#f0f0f0");
  P(4,21,14,1,jac.m); P(3,22,16,6,jac.m); P(3,22,1,6,jac.d); P(18,22,1,6,jac.d);
  P(5,21,1,7,"#f0f0f0"); P(14,21,1,7,"#f0f0f0"); P(10,20,1,8,"#c8c8d0"); P(10,21,1,1,"#9a9aa6");
  P(8,20,1,1,"#1a1a24"); P(8,21,1,1,"#1a1a24"); P(9,22,1,1,"#1a1a24");
  P(13,20,1,1,"#1a1a24"); P(13,21,1,1,"#1a1a24"); P(12,22,1,1,"#1a1a24");
  P(10,22,1,1,"#9a9aa6"); P(10,23,1,1,"#c0c0c8");
  P(9,24,3,1,O); P(8,25,1,2,O); P(12,25,1,2,O); P(9,27,3,1,O);
  P(9,24,3,1,"#cfcfd8"); P(9,25,3,2,"#eef0f6"); P(10,24,1,1,"#e84444"); P(10,26,1,1,"#2a2a38"); P(11,25,1,1,"#2a2a38");
  if (palette.dots) {                                  // maillot à pois: scatter red dots over the white kit
    const R = "#d81e3c";
    [[8,2],[12,2],[7,5]].forEach(([x,y]) => P(x, y, 2, 2, R));                     // cap
    [[5,22],[11,22],[15,22],[6,25],[14,25]].forEach(([x,y]) => P(x, y, 2, 2, R));  // jersey — 2x2 dots, scattered
  }
  return r;
}

export const VB_FULL = "0 0 132 174";
export const VB_HEAD = "0 0 132 132";

// mood from board status: alert/watch -> alarmed; green -> approving (a clean board is earned).
export function moodFromStatus(status) {
  return status === "green" ? "approving" : status === "awaiting" ? "calm" : "alarmed";
}

export default function Wattson({ mood = "calm", viewBox = VB_HEAD, className, style, date }) {
  const palette = paletteForDate(date ? new Date(date) : new Date()); // date override aids testing
  return (
    <svg className={className} viewBox={viewBox} shapeRendering="crispEdges"
      style={{ width: "100%", height: "auto", imageRendering: "pixelated", display: "block", ...style }}
      dangerouslySetInnerHTML={{ __html: rects(mood, palette) }} />
  );
}
