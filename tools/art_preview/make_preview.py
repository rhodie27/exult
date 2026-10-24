#!/usr/bin/env python3
"""Upscale game images several ways for a side-by-side art preview.

Usage: make_preview.py [--models DIR] [--redraw] OUT_DIR IMAGE [IMAGE ...]

Each input must be an 8-bit paletted image at the game's native resolution
(see render_scenes.py). For each one, OUT_DIR gets 4x versions:
  point     plain pixel copy (what the game shows today)
  hq4x      Exult's Hq4x scaler
  4xbr      Exult's 4xBR scaler
  <model>   every ESRGAN-style .pth/.safetensors upscaler found in --models
            (pixel-art models from OpenModelDB, run through spandrel)
  redraw-*  with --redraw, an SDXL img2img repaint of the best upscale at two
            strengths, which adds detail rather than only smoothing edges
plus index.html, a comparison page.
"""
import argparse
import glob
import json
import os
import subprocess
import sys

from PIL import Image

UPSCALE_PREVIEW = os.environ.get("UPSCALE_PREVIEW", "upscale_preview")

# Models fetched by run_macos.sh, in preference order for the redraw base.
MODEL_LABELS = {
    "4x-NXbrz": "AI: NXbrz (pixel art)",
    "4x-Fatal-Pixels": "AI: Fatal Pixels (pixel art)",
    "4x-Fatality-MK2": "AI: Fatality MK2 (pixel art)",
    "2x-Faithful-Lite": "AI: Faithful Lite (game textures)",
}

REDRAW_PROMPT = ("detailed hand-painted fantasy RPG game art, top-down oblique view, medieval stone, "
                 "wood and foliage, crisp clean edges, rich texture, 1990s Ultima style, high resolution")
REDRAW_NEGATIVE = "blurry, photo, 3d render, text, watermark, frame, border, jpeg artifacts, smeared"
REDRAW_STRENGTHS = (0.3, 0.5)


def device():
    import torch
    if torch.backends.mps.is_available():
        return "mps"
    if torch.cuda.is_available():
        return "cuda"
    return "cpu"


def load_upscalers(models_dir):
    if not models_dir or not os.path.isdir(models_dir):
        return []
    import spandrel
    import torch
    dev = device()
    found = []
    for path in sorted(glob.glob(os.path.join(models_dir, "*.pth")) + glob.glob(os.path.join(models_dir, "*.safetensors"))):
        key = os.path.splitext(os.path.basename(path))[0]
        try:
            model = spandrel.ModelLoader(device=dev).load_from_file(path).eval()
        except Exception as e:    # Unsupported architecture or bad download.
            print(f"skip model {key}: {e}", file=sys.stderr)
            continue
        found.append((key, model))
    order = list(MODEL_LABELS)
    found.sort(key=lambda m: order.index(m[0]) if m[0] in order else len(order))
    return found


def run_upscaler(model, img, scale=4):
    """Upscale an RGB image to exactly scale x."""
    import numpy as np
    import torch
    arr = np.asarray(img.convert("RGB"), dtype=np.float32) / 255.0
    t = torch.from_numpy(arr).permute(2, 0, 1).unsqueeze(0).to(model.device)
    with torch.no_grad():
        out = model(t)
    out = out.squeeze(0).permute(1, 2, 0).clamp(0, 1).cpu().numpy()
    res = Image.fromarray((out * 255.0 + 0.5).astype("uint8"), "RGB")
    want = (img.width * scale, img.height * scale)
    if res.size != want:    # 2x or 8x models.
        res = res.resize(want, Image.LANCZOS)
    return res


class Redrawer:
    def __init__(self):
        import torch
        from diffusers import AutoencoderKL, StableDiffusionXLImg2ImgPipeline
        dev = device()
        dtype = torch.float16 if dev != "cpu" else torch.float32
        vae = AutoencoderKL.from_pretrained("madebyollin/sdxl-vae-fp16-fix", torch_dtype=dtype)
        self.pipe = StableDiffusionXLImg2ImgPipeline.from_pretrained(
            "stabilityai/stable-diffusion-xl-base-1.0", vae=vae, torch_dtype=dtype,
            variant="fp16" if dtype == torch.float16 else None, use_safetensors=True).to(dev)
        self.pipe.set_progress_bar_config(disable=True)
        self.dev = dev

    def __call__(self, base, strength, seed=7):
        import torch
        # SDXL wants sides that are multiples of 8, and works best near 1 megapixel.
        w, h = base.size
        f = min(1.0, (1024 * 1024 / (w * h)) ** 0.5)
        sw, sh = max(8, int(w * f) // 8 * 8), max(8, int(h * f) // 8 * 8)
        gen = torch.Generator("cpu").manual_seed(seed)
        out = self.pipe(prompt=REDRAW_PROMPT, negative_prompt=REDRAW_NEGATIVE, image=base.resize((sw, sh), Image.LANCZOS),
                        strength=strength, guidance_scale=6.0, num_inference_steps=30, generator=gen).images[0]
        return out.resize((w, h), Image.LANCZOS)


def to_webp(img, out, quality=90):
    img.convert("RGB").save(out, "WEBP", quality=quality, method=6)
    return os.path.basename(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--models")
    ap.add_argument("--redraw", action="store_true")
    ap.add_argument("out_dir")
    ap.add_argument("images", nargs="+")
    args = ap.parse_args()

    out_dir = args.out_dir
    work = os.path.join(out_dir, "work")
    os.makedirs(work, exist_ok=True)
    upscalers = load_upscalers(args.models)
    redrawer = Redrawer() if args.redraw else None

    labels = {"point": "Original (pixel copy)", "hq4x": "Hq4x filter", "4xbr": "4xBR filter"}
    for key, _ in upscalers:
        labels[key] = MODEL_LABELS.get(key, "AI: " + key)
    if redrawer:
        for s in REDRAW_STRENGTHS:
            labels[f"redraw-{int(s * 100)}"] = f"AI redraw, {'light' if s < 0.4 else 'strong'} ({int(s * 100)}%)"

    index = []
    for path in args.images:
        name = os.path.splitext(os.path.basename(path))[0]
        src = Image.open(path)
        if src.mode != "P":
            print(f"skip {path}: not paletted ({src.mode})", file=sys.stderr)
            continue
        pal_png = os.path.join(work, f"{name}.png")
        src.save(pal_png)
        subprocess.run([UPSCALE_PREVIEW, pal_png, os.path.join(work, name)], check=True, stdout=subprocess.DEVNULL)
        results = {
            "point": Image.open(os.path.join(work, f"{name}-point4x.png")),
            "hq4x": Image.open(os.path.join(work, f"{name}-hq4x.png")),
            "4xbr": Image.open(os.path.join(work, f"{name}-4xbr.png")),
        }
        rgb = src.convert("RGB")
        for key, model in upscalers:
            print(f"{name}: {key}")
            results[key] = run_upscaler(model, rgb)
        if redrawer:
            base = results[upscalers[0][0]] if upscalers else results["4xbr"]
            for s in REDRAW_STRENGTHS:
                print(f"{name}: redraw {s}")
                results[f"redraw-{int(s * 100)}"] = redrawer(base, s)

        entry = {"name": name, "variants": {}}
        for key, img in results.items():
            entry["variants"][key] = to_webp(img, os.path.join(out_dir, f"{name}-{key}.webp"))
        index.append(entry)
        print(f"done {name}")

    if not index:
        sys.exit("No usable images: inputs must be 8-bit paletted (native game resolution).")
    with open(os.path.join(out_dir, "index.html"), "w") as f:
        f.write(PAGE.replace("__INDEX__", json.dumps(index)).replace("__LABELS__", json.dumps(labels)))
    print(os.path.join(out_dir, "index.html"))


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
.cmp img{display:block;width:100%}.cmp .top{position:absolute;inset:0;overflow:hidden}
.cmp .top img{width:auto;height:100%;max-width:none}
.div{position:absolute;top:0;bottom:0;width:2px;background:var(--accent)}
.tag{position:absolute;top:8px;padding:2px 8px;background:#000a;color:#fff;font-size:12px;border-radius:4px}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(300px,1fr));gap:12px;margin-top:20px}
.grid figure{margin:0}.grid img{width:100%;display:block;border:1px solid var(--line);cursor:pointer}
.grid figcaption{font-size:13px;color:var(--muted);margin-top:4px}
</style></head><body><main>
<h1>Ultima 7 art preview</h1>
<p>Each image upscaled 4x in several ways. Drag across the big image to compare the two styles picked below, or click any thumbnail to put it on the right. Private: this contains EA's original art.</p>
<div class="bar" id="shots"></div>
<div class="bar">Left <select id="a"></select> Right <select id="b"></select></div>
<div class="cmp" id="cmp"><img id="ib"><div class="top" id="top"><img id="ia"></div><div class="div" id="div"></div>
<span class="tag" style="left:8px" id="ta"></span><span class="tag" style="right:8px" id="tb"></span></div>
<div class="grid" id="grid"></div>
</main><script>
const INDEX=__INDEX__, LABELS=__LABELS__;
let cur=0,pos=.5;const $=id=>document.getElementById(id);
for(const s of ["a","b"]) for(const k in LABELS){const o=document.createElement("option");o.value=k;o.textContent=LABELS[k];$(s).append(o)}
const keys=Object.keys(LABELS);$("a").value="4xbr";$("b").value=keys[keys.length-1];
INDEX.forEach((e,i)=>{const b=document.createElement("button");b.textContent=e.name;b.onclick=()=>{cur=i;draw()};$("shots").append(b)});
function draw(){const e=INDEX[cur];[...$("shots").children].forEach((b,i)=>b.classList.toggle("on",i==cur));
$("ia").src=e.variants[$("a").value];$("ib").src=e.variants[$("b").value];
$("ta").textContent=LABELS[$("a").value];$("tb").textContent=LABELS[$("b").value];
$("grid").innerHTML=keys.filter(k=>e.variants[k]).map(k=>`<figure><img data-k="${k}" src="${e.variants[k]}"><figcaption>${LABELS[k]}</figcaption></figure>`).join("");
$("grid").querySelectorAll("img").forEach(im=>im.onclick=()=>{$("b").value=im.dataset.k;draw();scrollTo({top:0,behavior:"smooth"})});slide()}
function slide(){const w=$("cmp").clientWidth;$("top").style.width=pos*w+"px";$("ia").style.height=$("cmp").clientHeight+"px";$("div").style.left=pos*w+"px"}
function mv(x){const r=$("cmp").getBoundingClientRect();pos=Math.min(1,Math.max(0,(x-r.left)/r.width));slide()}
$("cmp").addEventListener("pointermove",e=>{if(e.buttons||e.pointerType=="mouse")mv(e.clientX)});
$("a").onchange=$("b").onchange=draw;addEventListener("resize",slide);$("ib").onload=slide;draw();
</script></body></html>"""


if __name__ == "__main__":
    main()
