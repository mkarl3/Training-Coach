import React, { useEffect } from "react";
import Wattson, { VB_PRESENT } from "./Wattson.jsx";

// The big-ride celebration "moment" — Coach Wattson, in his presenting pose, holds an oversized
// object up FOR you (you earned it; he never wears the prize). Shown in the weekly check-in.
// Objects cycle cowbell → champagne → trophy (see celebrationFlair in Wattson.jsx). The object is
// drawn at the sprite's own pixel grid (S=6) and handed to <Wattson present accessory=…/>, so it
// sits in his hand and the sleeve recolors with the active jersey.
// SOUND: bundled WAV samples in public/sounds/ (generated, not recordings) — drop a different file
// at the same path to retune, no code change.

const S = 6;
const R = (x, y, w, h, c) => (c ? `<rect x="${x*S}" y="${y*S}" width="${w*S}" height="${h*S}" fill="${c}"/>` : "");

// ---- the three held objects, positioned in his hand (cols ~21-23, rows ~12-14) ----
function cowbellMarkup() {
  const X = 18, br = "#cf9a1e", brL = "#ecc94f", brD = "#8a6410", mouth = "#241c06", strap = "#5a4018", clap = "#4a3608";
  let s = ""; const P = (x, y, w, h, c) => { s += R(x + X, y, w, h, c); };
  P(4,0,3,1,strap); P(3,1,1,1,strap); P(7,1,1,1,strap); P(2,2,8,1,brD);
  [[3,3,6],[4,3,6],[5,2,8],[6,2,8],[7,1,10],[8,1,10],[9,1,10],[10,0,12]]
    .forEach(([y,x,w]) => { P(x,y,w,1,br); P(x,y,1,1,brL); P(x+w-1,y,1,1,brD); });
  P(5,3,1,7,brL); P(0,11,12,1,brD); P(1,12,10,1,mouth); P(5,12,2,2,clap);
  return `<g class="cb-bell">${s}</g>`;
}
function champagneMarkup() {
  const X = 19, g = "#1d6e3a", gL = "#3aa564", gD = "#0d4222", foil = "#d4af37", label = "#f2f4f8", cork = "#c9a46a";
  let b = ""; const P = (x, y, w, h, c) => { b += R(x + X, y, w, h, c); };
  P(2,1,2,4,g); P(2,1,1,4,gL); P(2,1,2,1,foil); P(2,2,2,1,"#b8932c");
  P(1,5,4,1,g); P(0,6,6,2,g); P(0,8,6,6,g); P(0,6,1,8,gL); P(5,6,1,8,gD); P(0,10,6,2,label); P(1,13,4,1,gD);
  const corkM = `<g class="cb-cork">${R(2+X,-1,2,1,cork) + R(2+X,-2,2,1,"#e0c089")}</g>`;
  const bottle = `<g class="cb-bottle">${b}${corkM}</g>`;
  const vecs = [[-7,-30],[7,-34],[0,-44],[-12,-20],[12,-22]]; let fz = "";
  vecs.forEach((v, i) => { fz += `<g class="cb-fizz" style="--tx:${v[0]}px;--ty:${v[1]}px;animation-delay:${i*0.05}s">${R(2+X,0,1,1,"#dff0ff")}</g>`; });
  return bottle + fz;
}
function trophyMarkup() {
  const X = 17, gold = "#e6c12f", goldL = "#f6dd6b", goldD = "#b8881a", plinth = "#7a5a18";
  let t = ""; const P = (x, y, w, h, c) => { t += R(x + X, y, w, h, c); };
  P(3,1,8,1,goldD); P(2,2,10,1,gold); P(2,3,10,2,gold); P(3,5,8,1,gold); P(4,6,6,1,gold); P(5,7,4,1,gold);
  P(3,2,1,3,goldL); P(10,2,1,3,goldD);
  P(0,2,2,1,gold); P(0,3,1,2,gold); P(1,4,1,1,gold); P(12,2,2,1,gold); P(13,3,1,2,gold); P(12,4,1,1,gold);
  P(6,8,2,2,goldD); P(4,10,6,1,gold); P(3,11,8,2,plinth); P(3,13,8,1,goldD);
  return t + `<g class="cb-glint">${R(3+X,2,1,7,"#fff8d8")}</g>`;
}
const OBJ = { cowbell: cowbellMarkup, champagne: champagneMarkup, trophy: trophyMarkup };
const CONFETTI = ["#e02030","#f5d020","#1f6fd0","#1e9e6a","#e6398a","#f7d51d"];

const CSS = `
.cb-bell{transform-box:fill-box;transform-origin:50% 4%;animation:cbring 1.5s ease-in-out infinite}
@keyframes cbring{0%,100%{transform:rotate(-12deg)}50%{transform:rotate(12deg)}}
.cb-bottle{transform-box:fill-box;transform-origin:50% 96%;transform:rotate(13deg)}
.cb-cork{animation:cbpop 2.6s ease-out infinite}
@keyframes cbpop{0%,6%{transform:translateY(0);opacity:1}74%{opacity:1}100%{transform:translateY(-104px);opacity:0}}
.cb-fizz{animation:cbburst 2.6s ease-out infinite;opacity:0}
@keyframes cbburst{0%{transform:translate(0,0);opacity:0}12%{opacity:1}100%{transform:translate(var(--tx),var(--ty));opacity:0}}
.cb-glint{animation:cbsweep 2.6s linear infinite;opacity:0}
@keyframes cbsweep{0%,55%{transform:translateX(-26px) skewX(-20deg);opacity:0}68%,82%{opacity:.85}100%{transform:translateX(70px) skewX(-20deg);opacity:0}}
`;

// ---- sound: bundled WAV samples (served from public/sounds; swap the files to retune) ----
const SOUND = { cowbell: "/sounds/cowbell.wav", champagne: "/sounds/champagne.wav", trophy: "/sounds/trophy.wav" };
function playSound(flair) {
  const a = new Audio(SOUND[flair] || SOUND.cowbell);
  a.volume = 0.85;
  a.play().catch(() => {});   // autoplay is fine here — the check-in is reached via user gestures
}

export default function Celebration({ title = "You earned this!", subtitle = "", flair = "cowbell", sound = true, onDismiss }) {
  const markup = (OBJ[flair] || OBJ.cowbell)();
  useEffect(() => { if (sound) { try { playSound(flair); } catch (e) { /* autoplay may be blocked until a gesture */ } } }, [flair, sound]);
  return (
    <div style={{ position: "relative", overflow: "hidden", background: "#1b1930", border: "2px solid #2f2c4a",
                  borderRadius: 14, padding: "20px 20px 18px", textAlign: "center",
                  fontFamily: "var(--font-sans, system-ui)", color: "#f0eefc" }}>
      <style>{CSS}</style>
      <div style={{ position: "absolute", top: 0, left: 0, right: 0, height: 10, display: "flex" }}>
        {Array.from({ length: 30 }).map((_, i) => (
          <div key={i} style={{ flex: 1, height: i % 3 ? 6 : 10, background: CONFETTI[i % CONFETTI.length] }} />
        ))}
      </div>
      <div style={{ width: 250, maxWidth: "70%", margin: "6px auto 0" }}>
        <Wattson mood="approving" present accessory={markup} viewBox={VB_PRESENT} />
      </div>
      <div style={{ fontSize: 22, fontWeight: 600, marginTop: 6 }}>{title}</div>
      {subtitle && <div style={{ fontSize: 15, color: "#c7c3e6", marginTop: 2 }}>{subtitle}</div>}
      {onDismiss && (
        <button onClick={onDismiss} aria-label="Dismiss" style={{ position: "absolute", top: 8, right: 10,
                background: "none", border: "none", color: "#9a96bd", fontSize: 18, cursor: "pointer" }}>×</button>
      )}
    </div>
  );
}
