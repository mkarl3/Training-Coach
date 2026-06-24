"""Render the Watt Smith app logo from the real Coach Wattson sprite (rects() ported verbatim
from app/frontend/src/Wattson.jsx) + the Press Start 2P wordmark with the brand red drop-shadow."""
from PIL import Image, ImageDraw, ImageFont
import os

S = 24                                                    # px per sprite cell
FACE = [[7,6,10],[8,5,12],[9,5,12],[10,5,12],[11,5,12],[12,5,12],[13,5,12],[14,6,10],[15,6,10],[16,7,8],[17,8,6],[18,9,4]]
CAP  = [[2,8,6],[3,6,10],[4,5,12],[5,5,12],[6,5,12]]
O="#14121f"; skb="#e0a878"; sks="#b07f50"; skh="#f4cd9a"
capm="#e84444"; capd="#a82828"; capl="#ff8a8a"; acc="#f0f0f0"
jacm="#3a6ad8"; jacd="#2444a0"; jacl="#5c8cde"
hair="#5a3a28"; brow="#3e2618"; fc="#5a3a28"; eye="#2a2438"

# sprite layer (22 cols x 29 rows), transparent
spr = Image.new("RGBA", (22*S, 29*S), (0,0,0,0))
sd = ImageDraw.Draw(spr)
def P(x,y,w,h,c):
    if not c: return
    sd.rectangle([x*S, y*S, x*S + w*S - 1, y*S + h*S - 1], fill=c)

expr = "approving"
for y,x,w in CAP+FACE: P(x-1,y,w+2,1,O)
P(7,1,8,1,O); P(3,6,16,1,O); P(9,19,4,1,O)
for y,x,w in FACE: P(x,y,w,1,skb)
for y,x,w in FACE: P(x+w-1,y,1,1,sks)
P(5,8,1,6,skh); P(4,11,1,2,skb); P(17,11,1,2,skb); P(3,11,1,2,O); P(18,11,1,2,O)
P(5,7,1,2,hair); P(16,7,1,2,hair)
for y,x,w in CAP: P(x,y,w,1,capm)
for y,x,w in CAP: P(x+w-1,y,1,1,capd)
P(6,2,2,1,capl); P(6,3,2,1,capl); P(5,4,12,1,acc)
P(4,6,14,1,capl); P(4,7,14,1,capd)
P(7,8,3,1,brow); P(12,8,3,1,brow)
P(7,9,3,2,"#ffffff"); P(8,9,1,2,eye); P(12,9,3,2,"#ffffff"); P(13,9,1,2,eye)
P(10,11,2,2,sks); P(9,12,1,1,sks)
P(6,13,10,1,fc); P(7,14,8,1,fc); P(5,12,1,1,fc); P(16,12,1,1,fc)
# approving mouth + cheeks + sparkle
P(8,15,6,1,"#5a2a22"); P(9,15,4,1,"#ffffff"); P(8,14,1,1,"#7a3b2e"); P(13,14,1,1,"#7a3b2e")
P(2,2,1,1,"#f7d51d"); P(1,3,3,1,"#f7d51d"); P(2,4,1,1,"#f7d51d")
# neck + jacket
P(7,19,8,1,sks); P(5,20,12,1,jacl); P(7,20,1,2,"#f0f0f0"); P(13,20,1,2,"#f0f0f0")
P(4,21,14,1,jacm); P(3,22,16,6,jacm); P(3,22,1,6,jacd); P(18,22,1,6,jacd)
P(5,21,1,7,"#f0f0f0"); P(14,21,1,7,"#f0f0f0"); P(10,20,1,8,"#c8c8d0"); P(10,21,1,1,"#9a9aa6")
P(8,20,1,1,"#1a1a24"); P(8,21,1,1,"#1a1a24"); P(9,22,1,1,"#1a1a24")
P(13,20,1,1,"#1a1a24"); P(13,21,1,1,"#1a1a24"); P(12,22,1,1,"#1a1a24")
P(10,22,1,1,"#9a9aa6"); P(10,23,1,1,"#c0c0c8")
P(9,24,3,1,O); P(8,25,1,2,O); P(12,25,1,2,O); P(9,27,3,1,O)
P(9,24,3,1,"#cfcfd8"); P(9,25,3,2,"#eef0f6"); P(10,24,1,1,"#e84444"); P(10,26,1,1,"#2a2a38"); P(11,25,1,1,"#2a2a38")

spr = spr.crop(spr.getbbox())                             # trim transparent margins

# ---- compose the square logo ----
SZ = 1024
bg = "#0b0b14"; panel = "#16213e"; cream = "#f4f4f0"; gold = "#f7d51d"; red = "#e84444"
img = Image.new("RGB", (SZ, SZ), bg)
d = ImageDraw.Draw(img)
# pixel-window frame (NES chrome): cream inset border
m = 26
d.rectangle([m, m, SZ-m-1, SZ-m-1], outline=cream, width=8)
d.rectangle([m+16, m+16, SZ-m-17, SZ-m-17], fill=panel)

# place Wattson, scaled to fit
target_h = 560
scale = target_h / spr.height
spr2 = spr.resize((int(spr.width*scale), target_h), Image.NEAREST)
sx = (SZ - spr2.width)//2
sy = 95
img.paste(spr2, (sx, sy), spr2)

# wordmark "WATT SMITH" with red drop-shadow (brand rule)
FONT = os.path.join(os.path.dirname(__file__), "assets", "PressStart2P.ttf")
font = ImageFont.truetype(FONT, 96)
def centered(text, y, fill, shadow, off):
    w = d.textlength(text, font=font)
    x = (SZ - w)/2
    d.text((x+off, y+off), text, font=font, fill=shadow)
    d.text((x, y), text, font=font, fill=fill)
centered("WATT", 712, gold, red, 7)
centered("SMITH", 820, gold, red, 7)

OUT = os.path.join(os.path.expanduser("~"), "OneDrive", "Documents", "watt-smith-logo.png")
img.save(OUT)
# Strava-friendly 512 copy too
img.resize((512,512), Image.LANCZOS).save(OUT.replace(".png", "-512.png"))
print("saved:", OUT)
print("sprite bbox:", spr.size)
