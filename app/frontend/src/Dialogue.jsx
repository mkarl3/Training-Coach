import React from "react";
import Wattson, { VB_HEAD } from "./Wattson.jsx";

// Coach Wattson's dialogue box (brand book §07): cream portrait panel + sprite, a green
// "Coach Wattson" label, the message, and a blinking ▼ affordance. This is how Wattson speaks
// throughout onboarding. The message text is passed in — the UI never synthesizes coaching copy.
export default function Dialogue({ mood = "calm", text, children, cta }) {
  return (
    <div className="dlg pbox">
      <div className="port"><Wattson mood={mood} viewBox={VB_HEAD} /></div>
      <div className="txt">
        <div className="who">Coach Wattson</div>
        {text && <p className="dlg-msg">{text}<span className="blink" /></p>}
        {children}
        {cta && <div className="dlg-cta">{cta}</div>}
      </div>
    </div>
  );
}
