import React from "react";
import Wattson, { VB_FULL } from "./Wattson.jsx";

// The big-ride celebration "moment" — a dismissible card Wattson shows when you've earned it
// (century / Everesting / longest-ever ride). The flourish (cowbell / champagne / chapeau) is
// drawn LARGE here, at a high pixel budget, so it actually reads — unlike a 5px sprite prop.
// Wattson celebrates YOU; he never wears the prize. Stays until the next ride (caller's job).

const PS = 10; // prop pixel size
function buildProp(draw) {
  let r = "";
  const P = (x, y, w, h, c) => { if (c) r += `<rect x="${x*PS}" y="${y*PS}" width="${w*PS}" height="${h*PS}" fill="${c}"/>`; };
  const [w, h] = draw(P);
  return { __html: r, vb: `0 0 ${w*PS} ${h*PS}` };
}

// roadside cowbell — brass bell, hanger strap, clapper, ring-motion marks
function cowbell(P) {
  const br = "#d2a02a", brL = "#f0cf63", brD = "#9a6f12", mouth = "#241c06", strap = "#6e4a22", clap = "#4a3608";
  P(6,0,3,1,strap); P(5,1,1,2,strap); P(9,1,1,2,strap);                 // hanger loop
  [[3,5,5],[4,5,5],[5,4,7],[6,4,7],[7,3,9],[8,3,9],[9,3,9],[10,2,11],[11,2,11],[12,2,11]]
    .forEach(([y,x,w]) => { P(x,y,w,1,br); P(x,y,1,1,brL); P(x+w-1,y,1,1,brD); }); // trapezoid body
  P(1,13,13,1,brD); P(2,14,11,1,mouth);                                 // flared lip + mouth
  P(6,14,2,2,clap); P(7,16,1,1,clap);                                   // clapper
  P(0,5,1,1,"#cfd6e0"); P(1,4,1,1,"#cfd6e0"); P(13,5,1,1,"#cfd6e0"); P(12,4,1,1,"#cfd6e0"); // ringing
  return [14, 17];
}

// podium champagne — green bottle, cork popping, spray + confetti
function champagne(P) {
  const g = "#1d6e3a", gL = "#2f9e57", gD = "#0f4a26", foil = "#d4af37", label = "#eef1f5", cork = "#caa46a";
  P(5,8,5,9,g); P(5,8,1,9,gL); P(9,8,1,9,gD);                           // body
  P(6,11,3,2,label);                                                    // label
  P(6,6,3,2,g); P(6,6,1,2,gL); P(7,4,2,2,g); P(7,4,2,1,foil);           // shoulder + neck + foil
  P(8,1,1,1,cork); P(9,0,1,1,cork); P(8,2,1,1,cork);                    // cork flying
  P(7,2,1,1,"#fff"); P(10,2,1,1,"#fff"); P(9,3,1,1,"#fff");             // spray
  [[2,3,"#e02030"],[12,4,"#f5d020"],[1,6,"#1f6fd0"],[12,8,"#1e9e6a"],[3,1,"#f5d020"],[11,1,"#e02030"],[2,9,"#1f6fd0"]]
    .forEach(([x,y,c]) => P(x,y,1,1,c));                                // confetti
  return [14, 18];
}

// chapeau — his cycling cap, doffed (hats off, the cyclist's salute), with a little tip-sparkle
function chapeau(P) {
  const m = "#e84444", d = "#a82828", l = "#ff8a8a", acc = "#f0f0f0", O = "#14121f";
  P(5,0,4,1,O);                                                         // top outline (rounded crown)
  P(5,1,4,1,m); P(4,2,6,1,m); P(3,3,8,1,m); P(3,4,8,1,m); P(3,5,8,1,m); // crown
  P(3,3,1,3,d); P(10,3,1,3,d); P(5,1,2,1,l);                            // shade + highlight
  P(3,4,8,1,acc);                                                       // accent stripe
  P(3,6,11,1,l); P(13,6,1,1,l); P(3,7,12,1,d);                          // forward peak (points right)
  P(13,0,1,1,"#f7d51d"); P(14,1,2,1,"#f7d51d"); P(13,2,1,1,"#f7d51d");  // tip sparkle
  return [16, 9];
}

const PROPS = { cowbell, champagne, chapeau };
const CONFETTI = ["#e02030","#f5d020","#1f6fd0","#1e9e6a","#e6398a","#f7d51d"];

export default function Celebration({ title = "You earned this!", subtitle = "", flair = "cowbell", onDismiss }) {
  const prop = buildProp(PROPS[flair] || PROPS.cowbell);
  return (
    <div style={{ position: "relative", display: "flex", alignItems: "center", gap: 18, overflow: "hidden",
                  background: "#1b1930", border: "2px solid #2f2c4a", borderRadius: 14, padding: "18px 20px",
                  fontFamily: "var(--font-sans, system-ui)", color: "#f0eefc" }}>
      <div style={{ position: "absolute", top: 0, left: 0, right: 0, height: 10, display: "flex" }}>
        {Array.from({ length: 28 }).map((_, i) => (
          <div key={i} style={{ flex: 1, height: i % 3 ? 6 : 10, background: CONFETTI[i % CONFETTI.length] }} />
        ))}
      </div>
      <div style={{ width: 96, flexShrink: 0 }}><Wattson mood="approving" viewBox={VB_FULL} /></div>
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ fontSize: 20, fontWeight: 600, marginBottom: 4 }}>{title}</div>
        {subtitle && <div style={{ fontSize: 15, color: "#c7c3e6" }}>{subtitle}</div>}
      </div>
      <svg viewBox={prop.vb} width={110} shapeRendering="crispEdges"
           style={{ imageRendering: "pixelated", flexShrink: 0 }} dangerouslySetInnerHTML={{ __html: prop.__html }} />
      {onDismiss && (
        <button onClick={onDismiss} aria-label="Dismiss" style={{ position: "absolute", top: 8, right: 10,
                background: "none", border: "none", color: "#9a96bd", fontSize: 18, cursor: "pointer" }}>×</button>
      )}
    </div>
  );
}
