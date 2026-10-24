#!/usr/bin/env python3
"""Make hi-res replacement art for shapes.vga with an AI upscaling model.

Usage: upscale_shapes.py --model MODEL.pth [--res 4] [--shapes 0-149] [--sheet]
                         STATIC_DIR PATCH_DIR

Writes PATCH_DIR/hires/shapes/SSSS_FF.png for each frame of the chosen
shapes, in the format Exult loads when config/video/hires_art is set:
8-bit PNGs in the game palette, index 255 transparent, exactly res times the
size of the original frame.

Each frame is drawn in the day palette, upscaled by the model (4x models
such as 4x-PixelPerfectV4), resized to res if that differs, and snapped
back to the palette.  So that the game's effects keep working:
  - the outline comes from the original frame (no new transparent or
    opaque pixels), and
  - pixels whose original colour is a palette-cycling or translucent one
    (index 224 and up) keep that index, so water, fire and glass still
    animate and blend.
Flat ground tiles are padded with copies of themselves before upscaling so
their edges match when tiled.

--sheet also writes PATCH_DIR/hires/sheet-SSSS-SSSS.png comparing the
original (point scaled) with the new art for a quick look.

The game art stays on this computer; nothing is uploaded.
"""
import argparse
import os
import struct
import sys

import numpy as np
from PIL import Image

TILE = 8
FIRST_OBJ_SHAPE = 0x96    # Shapes below this are flat 8x8 ground tiles.
TRANSPARENT = 255
FIRST_SPECIAL = 224       # Palette cycling and translucent colours.
PAD = TILE                # Padding around frames for the model, in pixels.


def find(static, name):
    """Case-insensitive lookup, since GOG and DOS copies differ."""
    want = name.lower()
    for f in os.listdir(static):
        if f.lower() == want:
            return os.path.join(static, f)
    sys.exit(f"{name} not found in {static}")


class Flex:
    def __init__(self, path):
        with open(path, "rb") as f:
            self.data = f.read()
        count = struct.unpack_from("<I", self.data, 0x54)[0]
        self.entries = [struct.unpack_from("<II", self.data, 0x80 + 8 * i) for i in range(count)]

    def __len__(self):
        return len(self.entries)

    def get(self, i):
        off, size = self.entries[i]
        return self.data[off:off + size] if size else b""


def read_frames(data):
    """All frames of one shapes.vga entry as (flat, 2D uint8 array) pairs."""
    if len(data) < 8:
        return []
    dlen, hdrlen = struct.unpack_from("<II", data, 0)
    if dlen != len(data):    # Flat tiles: 64 raw bytes per frame.
        return [(True, np.frombuffer(data[i:i + 64], np.uint8).reshape(TILE, TILE).copy())
                for i in range(0, len(data) - 63, 64)]
    frames = []
    for fr in range((hdrlen - 4) // 4):
        pos = struct.unpack_from("<I", data, 4 + 4 * fr)[0]
        xright, xleft, yabove, ybelow = struct.unpack_from("<hhhh", data, pos)
        pos += 8
        w, h = xleft + xright + 1, yabove + ybelow + 1
        if w <= 0 or h <= 0 or w > 2048 or h > 2048:
            frames.append(None)
            continue
        pix = np.full((h, w), TRANSPARENT, np.uint8)
        while True:
            scanlen = struct.unpack_from("<H", data, pos)[0]
            pos += 2
            if scanlen == 0:
                break
            encoded, scanlen = scanlen & 1, scanlen >> 1
            sx, sy = struct.unpack_from("<hh", data, pos)
            pos += 4
            x, y = xleft + sx, yabove + sy
            if not encoded:
                pix[y, x:x + scanlen] = np.frombuffer(data, np.uint8, scanlen, pos)
                pos += scanlen
                continue
            b = 0
            while b < scanlen:
                bcnt = data[pos]
                pos += 1
                repeat, bcnt = bcnt & 1, bcnt >> 1
                if repeat:
                    pix[y, x + b:x + b + bcnt] = data[pos]
                    pos += 1
                else:
                    pix[y, x + b:x + b + bcnt] = np.frombuffer(data, np.uint8, bcnt, pos)
                    pos += bcnt
                b += bcnt
        frames.append((False, pix))
    return frames


def load_palette(static):
    raw = np.frombuffer(Flex(find(static, "palettes.flx")).get(0)[:768], np.uint8)
    return (np.minimum(raw.astype(np.int32) * 255 // 63, 255)).astype(np.uint8).reshape(256, 3)


def nearest_lut(palette):
    """64x64x64 table: nearest normal palette entry for each 6-bit colour."""
    pal = palette[:FIRST_SPECIAL].astype(np.float32)
    levels = (np.arange(64, dtype=np.float32) * 255 / 63)
    lut = np.empty((64, 64, 64), np.uint8)
    g, b = np.meshgrid(levels, levels, indexing="ij")
    for r in range(64):
        rgb = np.stack([np.full_like(g, levels[r]), g, b], -1).reshape(-1, 1, 3)
        # "Redmean" weighting: closer to how different colours look.
        rmean = (rgb[..., 0] + pal[None, :, 0]) / 2
        d = rgb - pal[None]
        dist = (2 + rmean / 256) * d[..., 0] ** 2 + 4 * d[..., 1] ** 2 + (2 + (255 - rmean) / 256) * d[..., 2] ** 2
        lut[r] = dist.argmin(1).reshape(64, 64)
    return lut


def device():
    import torch
    if torch.backends.mps.is_available():
        return "mps"
    if torch.cuda.is_available():
        return "cuda"
    return "cpu"


class Upscaler:
    def __init__(self, path):
        import spandrel
        self.model = spandrel.ModelLoader(device=device()).load_from_file(path).eval()
        self.scale = self.model.scale

    def __call__(self, rgb):
        import torch
        t = torch.from_numpy(rgb.astype(np.float32) / 255).permute(2, 0, 1).unsqueeze(0).to(self.model.device)
        with torch.no_grad():
            out = self.model(t)
        return (out.squeeze(0).permute(1, 2, 0).clamp(0, 1).cpu().numpy() * 255 + 0.5).astype(np.uint8)


def fill_transparent(rgb, opaque):
    """Spread edge colours into transparent pixels so the model doesn't see
    a hard edge against black (which would darken outlines)."""
    rgb = rgb.copy()
    known = opaque.copy()
    if not known.any():
        return rgb
    while not known.all():
        grown = known.copy()
        acc = np.zeros(rgb.shape, np.int32)
        cnt = np.zeros(known.shape, np.int32)
        for dy, dx in ((-1, 0), (1, 0), (0, -1), (0, 1)):
            src = np.roll(known, (dy, dx), (0, 1))
            col = np.roll(rgb, (dy, dx), (0, 1))
            take = src & ~known
            acc[take] += col[take]
            cnt[take] += 1
        new = cnt > 0
        rgb[new] = (acc[new] // cnt[new, None]).astype(np.uint8)
        grown |= new
        if (grown == known).all():
            break
        known = grown
    return rgb


def upscale_frame(flat, pix, palette, lut, model, res):
    h, w = pix.shape
    if flat:    # Tile with copies of itself so edges line up.
        padded = np.pad(pix, PAD, mode="wrap")
    else:
        padded = np.pad(pix, PAD, mode="constant", constant_values=TRANSPARENT)
    opaque = padded != TRANSPARENT
    rgb = fill_transparent(palette[padded], opaque)
    big = model(rgb)
    s = model.scale
    big = big[PAD * s:(PAD + h) * s, PAD * s:(PAD + w) * s]
    if s != res:
        big = np.asarray(Image.fromarray(big).resize((w * res, h * res), Image.LANCZOS))
    q = big.astype(np.int32) * 63 // 255    # Map to 6-bit levels for the table.
    out = lut[q[..., 0], q[..., 1], q[..., 2]]
    orig = np.repeat(np.repeat(pix, res, 0), res, 1)
    keep = orig >= FIRST_SPECIAL    # Transparent, cycling and translucent.
    out[keep] = orig[keep]
    return out


def save_png(path, pix, palette):
    im = Image.fromarray(pix, "P")
    im.putpalette(palette.reshape(-1).tolist())
    im.save(path, transparency=TRANSPARENT, optimize=True)


def parse_range(text):
    out = []
    for part in text.split(","):
        a, _, b = part.partition("-")
        out.extend(range(int(a), int(b or a) + 1))
    return out


def make_sheet(path, pairs, palette, res, cols=8):
    """Original (point scaled) beside the new art, on a grey background."""
    cell = min(256, max(max(new.shape) for _, new in pairs)) + 8
    rows = (len(pairs) + cols - 1) // cols
    sheet = Image.new("RGB", (cols * cell * 2, rows * cell), (60, 60, 60))
    for i, (orig, new) in enumerate(pairs):
        x, y = (i % cols) * cell * 2, (i // cols) * cell
        for j, pix in enumerate((np.repeat(np.repeat(orig, res, 0), res, 1), new)):
            im = Image.fromarray(palette[pix])
            mask = Image.fromarray(((pix != TRANSPARENT) * 255).astype(np.uint8))
            if max(im.size) > cell - 8:
                f = (cell - 8) / max(im.size)
                size = (max(1, int(im.width * f)), max(1, int(im.height * f)))
                im, mask = im.resize(size, Image.NEAREST), mask.resize(size, Image.NEAREST)
            sheet.paste(im, (x + j * cell + 4, y + 4), mask)
    sheet.save(path)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("static")
    ap.add_argument("patch")
    ap.add_argument("--model", required=True, help="upscaling model (.pth or .safetensors) spandrel can load")
    ap.add_argument("--res", type=int, default=4, choices=(2, 3, 4), help="detail level, matching hires_art")
    ap.add_argument("--shapes", default=f"0-{FIRST_OBJ_SHAPE - 1}", help="shape numbers, e.g. 0-149,500")
    ap.add_argument("--sheet", action="store_true", help="also write a before/after sheet")
    args = ap.parse_args()

    palette = load_palette(args.static)
    lut = nearest_lut(palette)
    shapes = Flex(find(args.static, "shapes.vga"))
    model = Upscaler(args.model)
    outdir = os.path.join(args.patch, "hires", "shapes")
    os.makedirs(outdir, exist_ok=True)

    wanted = [s for s in parse_range(args.shapes) if s < len(shapes)]
    pairs = []
    done = 0
    for n, shnum in enumerate(wanted):
        for frnum, frame in enumerate(read_frames(shapes.get(shnum))):
            if frame is None or frnum > 31:
                continue
            flat, pix = frame
            if (pix == TRANSPARENT).all():
                continue
            new = upscale_frame(flat, pix, palette, lut, model, args.res)
            save_png(os.path.join(outdir, f"{shnum:04d}_{frnum:02d}.png"), new, palette)
            if args.sheet and len(pairs) < 512:
                pairs.append((pix, new))
            done += 1
        if n % 10 == 9 or n + 1 == len(wanted):
            print(f"shape {shnum} ({n + 1}/{len(wanted)}), {done} frames so far", flush=True)
    if args.sheet and pairs:
        path = os.path.join(args.patch, "hires", f"sheet-{wanted[0]:04d}-{wanted[-1]:04d}.png")
        make_sheet(path, pairs, palette, args.res)
        print("sheet:", path)


if __name__ == "__main__":
    main()
