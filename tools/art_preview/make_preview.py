#!/usr/bin/env python3
"""Upscale Exult screenshots several ways for a side-by-side art preview.

Usage: make_preview.py OUT_DIR SCREENSHOT [SCREENSHOT ...]

For each 8-bit paletted screenshot, writes 4x versions to OUT_DIR:
  point   - plain pixel copy (what the game shows today)
  hq4x    - Exult's Hq4x scaler
  4xbr    - Exult's 4xBR scaler
  ai      - Real-ESRGAN anime model (AI upscale)
  ai-pal  - the AI upscale reduced back to the game's 256-colour palette
and an index.json describing them.
"""
import json
import os
import subprocess
import sys

from PIL import Image

UPSCALE_PREVIEW = os.environ.get("UPSCALE_PREVIEW", "upscale_preview")
ESRGAN = os.environ.get("ESRGAN", "realesrgan-ncnn-vulkan")


def to_webp(png, out, quality=88):
    Image.open(png).convert("RGB").save(out, "WEBP", quality=quality, method=6)
    return os.path.basename(out)


def main():
    out_dir, shots = sys.argv[1], sys.argv[2:]
    os.makedirs(out_dir, exist_ok=True)
    work = os.path.join(out_dir, "work")
    os.makedirs(work, exist_ok=True)
    index = []
    for shot in shots:
        name = os.path.splitext(os.path.basename(shot))[0]
        src = Image.open(shot)
        if src.mode != "P":
            print(f"skip {shot}: not paletted ({src.mode})", file=sys.stderr)
            continue
        pal_png = os.path.join(work, f"{name}.png")
        src.save(pal_png)

        # Exult's own scalers.
        subprocess.run([UPSCALE_PREVIEW, pal_png, os.path.join(work, name)], check=True)

        # AI upscale.
        rgb_png = os.path.join(work, f"{name}-rgb.png")
        src.convert("RGB").save(rgb_png)
        ai_png = os.path.join(work, f"{name}-ai.png")
        subprocess.run([ESRGAN, "-i", rgb_png, "-o", ai_png, "-n", "realesrgan-x4plus-anime"],
                       check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

        # AI upscale snapped back to the original palette, so palette effects would still work.
        pal_img = Image.new("P", (1, 1))
        pal_img.putpalette(src.getpalette()[:768])
        ai_pal = Image.open(ai_png).convert("RGB").quantize(palette=pal_img, dither=Image.Dither.NONE)
        ai_pal_png = os.path.join(work, f"{name}-ai-pal.png")
        ai_pal.save(ai_pal_png)

        entry = {"name": name, "size": [src.width * 4, src.height * 4], "variants": {}}
        for key, png in [("point", f"{name}-point4x.png"), ("hq4x", f"{name}-hq4x.png"),
                         ("4xbr", f"{name}-4xbr.png"), ("ai", f"{name}-ai.png"),
                         ("ai-pal", f"{name}-ai-pal.png")]:
            entry["variants"][key] = to_webp(os.path.join(work, png),
                                             os.path.join(out_dir, f"{name}-{key}.webp"))
        index.append(entry)
        print(f"done {name}")
    with open(os.path.join(out_dir, "index.json"), "w") as f:
        json.dump(index, f, indent=1)
    with open(os.path.join(out_dir, "index.html"), "w") as f:
        f.write(PAGE.replace("__INDEX__", json.dumps(index)))
    print(os.path.join(out_dir, "index.html"))


LABELS = {"point": "Original (pixel copy)", "hq4x": "Hq4x filter", "4xbr": "4xBR filter",
          "ai": "AI upscale", "ai-pal": "AI upscale, game palette"}

PAGE = """<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Ultima 7 Art Preview</title>
<style>
:root{--bg:#f6f4ef;--fg:#1d1b18;--muted:#6b665d;--line:#d9d4c9;--accent:#8a5a14}
@media (prefers-color-scheme:dark){:root{--bg:#16150f;--fg:#ece8df;--muted:#a49e92;--line:#38352d;--accent:#e0a84a}}
body{margin:0;background:var(--bg);color:var(--fg);font:15px/1.45 -apple-system,system-ui,sans-serif}
main{max-width:1320px;margin:0 auto;padding:20px 16px}
h1{font-size:22px;margin:0 0 4px}p{color:var(--muted);margin:0 0 16px}
.bar{display:flex;flex-wrap:wrap;gap:8px 16px;align-items:center;margin:12px 0}
select,button{font:inherit;padding:5px 8px;border:1px solid var(--line);border-radius:6px;background:transparent;color:var(--fg)}
button.on{border-color:var(--accent);color:var(--accent)}
.cmp{position:relative;width:100%;max-width:1280px;border:1px solid var(--line);overflow:hidden;cursor:ew-resize;user-select:none}
.cmp img{display:block;width:100%;image-rendering:auto}.cmp .top{position:absolute;inset:0;overflow:hidden}
.cmp .top img{width:auto;height:100%;max-width:none}
.div{position:absolute;top:0;bottom:0;width:2px;background:var(--accent)}
.tag{position:absolute;top:8px;padding:2px 8px;background:#000a;color:#fff;font-size:12px;border-radius:4px}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(300px,1fr));gap:12px;margin-top:20px}
.grid figure{margin:0}.grid img{width:100%;display:block;border:1px solid var(--line)}
.grid figcaption{font-size:13px;color:var(--muted);margin-top:4px}
</style></head><body><main>
<h1>Ultima 7 art preview</h1>
<p>Your screenshots, upscaled 4x in five ways. Drag across the big image to compare two styles, or scroll down to see them all. Private: this contains EA's original art.</p>
<div class="bar" id="shots"></div>
<div class="bar">Left <select id="a"></select> Right <select id="b"></select></div>
<div class="cmp" id="cmp"><img id="ib"><div class="top" id="top"><img id="ia"></div><div class="div" id="div"></div>
<span class="tag" style="left:8px" id="ta"></span><span class="tag" style="right:8px" id="tb"></span></div>
<div class="grid" id="grid"></div>
</main><script>
const INDEX=__INDEX__, LABELS=""" + json.dumps(LABELS) + """;
let cur=0,pos=.5;const $=id=>document.getElementById(id);
for(const s of ["a","b"]) for(const k in LABELS){const o=document.createElement("option");o.value=k;o.textContent=LABELS[k];$(s).append(o)}
$("a").value="point";$("b").value="4xbr";
INDEX.forEach((e,i)=>{const b=document.createElement("button");b.textContent=e.name;b.onclick=()=>{cur=i;draw()};$("shots").append(b)});
function draw(){const e=INDEX[cur];[...$("shots").children].forEach((b,i)=>b.classList.toggle("on",i==cur));
$("ia").src=e.variants[$("a").value];$("ib").src=e.variants[$("b").value];
$("ta").textContent=LABELS[$("a").value];$("tb").textContent=LABELS[$("b").value];
$("grid").innerHTML=Object.keys(LABELS).map(k=>`<figure><img src="${e.variants[k]}"><figcaption>${LABELS[k]}</figcaption></figure>`).join("");slide()}
function slide(){const w=$("cmp").clientWidth;$("top").style.width=pos*w+"px";$("ia").style.height=$("cmp").clientHeight+"px";$("div").style.left=pos*w+"px"}
function mv(x){const r=$("cmp").getBoundingClientRect();pos=Math.min(1,Math.max(0,(x-r.left)/r.width));slide()}
$("cmp").addEventListener("pointermove",e=>{if(e.buttons||e.pointerType=="mouse")mv(e.clientX)});
$("a").onchange=$("b").onchange=draw;addEventListener("resize",slide);$("ib").onload=slide;draw();
</script></body></html>"""


if __name__ == "__main__":
    main()
