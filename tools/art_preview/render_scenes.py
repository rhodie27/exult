#!/usr/bin/env python3
"""Render sample scenes straight from Ultima 7 game files as paletted PNGs.

Usage: render_scenes.py STATIC_DIR OUT_DIR [--scenes N]

Reads shapes.vga, palettes.flx, u7map, u7chunks and u7ifixNN from the game's
STATIC folder and writes, at the game's native resolution:
  scene-NN.png  terrain plus fixed objects (buildings, trees, walls) for the
                busiest parts of the map
  avatar.png    the Avatar's walking frames
  tiles.png     a sheet of the flat ground tiles
Moveable objects and NPCs (stored in save games) are not drawn, and objects
are painted in a simple back-to-front order rather than Exult's full sort.
"""
import os
import struct
import sys

from PIL import Image

TILE = 8
CHUNK_TILES = 16
CHUNK = TILE * CHUNK_TILES
NUM_CHUNKS = 192
FIRST_OBJ_SHAPE = 0x96
TRANSPARENT = 255
AVATAR_SHAPE = 721


def find(static, name):
    """Case-insensitive lookup, since GOG and DOS copies differ."""
    want = name.lower()
    for f in os.listdir(static):
        if f.lower() == want:
            return os.path.join(static, f)
    return None


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


class Frame:
    def __init__(self, w, h, xleft, yabove, pixels):
        self.w, self.h, self.xleft, self.yabove, self.pixels = w, h, xleft, yabove, pixels

    def image(self, palette):
        im = Image.frombytes("P", (self.w, self.h), bytes(self.pixels))
        im.putpalette(palette)
        im.info["transparency"] = TRANSPARENT
        return im


class Shapes:
    def __init__(self, path):
        self.flex = Flex(path)
        self.cache = {}

    def frame(self, shnum, frnum):
        key = (shnum, frnum)
        if key not in self.cache:
            self.cache[key] = self._read(shnum, frnum)
        return self.cache[key]

    def _read(self, shnum, frnum):
        if shnum >= len(self.flex):
            return None
        data = self.flex.get(shnum)
        if len(data) < 8:
            return None
        dlen, hdrlen = struct.unpack_from("<II", data, 0)
        rle = dlen == len(data) or (len(data) % 2 == 0 and dlen == len(data) - 1)
        if not rle:    # Flat 8x8 tile.
            frnum &= 31
            raw = data[frnum * 64:frnum * 64 + 64]
            if len(raw) < 64:
                return None
            return Frame(TILE, TILE, TILE, TILE, bytearray(raw))
        nframes = (hdrlen - 4) // 4
        if frnum >= nframes:
            return None
        offs = [struct.unpack_from("<I", data, 4 + 4 * i)[0] for i in range(nframes)]
        pos = offs[frnum]
        xright, xleft, yabove, ybelow = struct.unpack_from("<hhhh", data, pos)
        pos += 8
        w, h = xleft + xright + 1, yabove + ybelow + 1
        if w <= 0 or h <= 0 or w > 2048 or h > 2048:
            return None
        pix = bytearray([TRANSPARENT]) * (w * h)
        while pos + 2 <= len(data):
            scanlen = struct.unpack_from("<H", data, pos)[0]
            pos += 2
            if scanlen == 0:
                break
            encoded, scanlen = scanlen & 1, scanlen >> 1
            sx, sy = struct.unpack_from("<hh", data, pos)
            pos += 4
            x, y = xleft + sx, yabove + sy
            row = y * w
            if not encoded:
                for i in range(scanlen):
                    if 0 <= x + i < w and 0 <= y < h:
                        pix[row + x + i] = data[pos + i]
                pos += scanlen
                continue
            b = 0
            while b < scanlen:
                bcnt = data[pos]
                pos += 1
                repeat, bcnt = bcnt & 1, bcnt >> 1
                for i in range(bcnt):
                    px = data[pos] if repeat else data[pos + i]
                    if 0 <= x + b + i < w and 0 <= y < h:
                        pix[row + x + b + i] = px
                pos += 1 if repeat else bcnt
                b += bcnt
        return Frame(w, h, xleft, yabove, pix)


def load_palette(static):
    raw = Flex(find(static, "palettes.flx")).get(0)[:768]
    return [min(255, v * 255 // 63) for v in raw]


class World:
    def __init__(self, static):
        self.static = static
        with open(find(static, "u7map"), "rb") as f:
            umap = f.read()
        self.terrain = [[0] * NUM_CHUNKS for _ in range(NUM_CHUNKS)]    # [cy][cx] -> chunk #
        for schunk in range(144):
            scy, scx = 16 * (schunk // 12), 16 * (schunk % 12)
            for i in range(256):
                cy, cx = divmod(i, 16)
                self.terrain[scy + cy][scx + cx] = struct.unpack_from("<H", umap, (schunk * 256 + i) * 2)[0]
        with open(find(static, "u7chunks"), "rb") as f:
            self.chunks = f.read()
        self.v2 = self.chunks[:8] == b"\xff\xff\xff\xffexlt"    # Exult's 3-byte format.
        self.ifix = {}    # (cx, cy) -> [(tx, ty, tz, shnum, frnum)]
        for schunk in range(144):
            path = find(static, "u7ifix%02x" % schunk)
            if not path:
                continue
            flex = Flex(path)
            scy, scx = 16 * (schunk // 12), 16 * (schunk % 12)
            for i in range(min(256, len(flex))):
                ent = flex.get(i)
                objs = []
                for j in range(0, len(ent) - 3, 4):
                    b0, b1, b2, b3 = ent[j:j + 4]
                    objs.append(((b0 >> 4) & 15, b0 & 15, b1 & 15, b2 + 256 * (b3 & 3), b3 >> 2))
                if objs:
                    cy, cx = divmod(i, 16)
                    self.ifix[(scx + cx, scy + cy)] = objs

    def terrain_tiles(self, cx, cy):
        num = self.terrain[cy][cx]
        tiles = []
        if self.v2:
            base = 10 + num * 768
            for i in range(256):
                b = self.chunks[base + 3 * i:base + 3 * i + 3]
                tiles.append((b[0] + 256 * b[1], b[2]))
        else:
            base = num * 512
            for i in range(256):
                b0, b1 = self.chunks[base + 2 * i], self.chunks[base + 2 * i + 1]
                tiles.append((b0 + 256 * (b1 & 3), (b1 >> 2) & 31))
        return tiles


def render(world, shapes, palette, cx0, cy0, cw, ch):
    """Render cw x ch chunks starting at (cx0, cy0). Objects reach up and left
    from their tile, so one extra chunk to the right and below is drawn too."""
    pw, ph = cw + 1, ch + 1
    img = Image.new("P", (pw * CHUNK, ph * CHUNK), 0)
    img.putpalette(palette)
    objects = []
    for dy in range(ph):
        for dx in range(pw):
            cx, cy = (cx0 + dx) % NUM_CHUNKS, (cy0 + dy) % NUM_CHUNKS
            for i, (sh, fr) in enumerate(world.terrain_tiles(cx, cy)):
                ty, tx = divmod(i, 16)
                f = shapes.frame(sh, fr)
                if f is None:
                    continue
                if sh < FIRST_OBJ_SHAPE and f.w == TILE and f.h == TILE and f.xleft == TILE:
                    img.paste(f.image(palette), (dx * CHUNK + tx * TILE, dy * CHUNK + ty * TILE))
                else:
                    objects.append((dx * 16 + tx, dy * 16 + ty, 0, sh, fr))
            for tx, ty, tz, sh, fr in world.ifix.get((cx, cy), []):
                objects.append((dx * 16 + tx, dy * 16 + ty, tz, sh, fr))
    # Back to front: lower lifts first, then by distance down-right.
    objects.sort(key=lambda o: (o[2], o[0] + o[1], o[1]))
    for tx, ty, tz, sh, fr in objects:
        f = shapes.frame(sh, fr)
        if f is None:
            continue
        x = (tx + 1) * TILE - 1 - 4 * tz - f.xleft
        y = (ty + 1) * TILE - 1 - 4 * tz - f.yabove
        im = f.image(palette)
        mask = im.point(lambda v: 0 if v == TRANSPARENT else 255, "L")
        img.paste(im, (x, y), mask)
    return img.crop((0, 0, cw * CHUNK, ch * CHUNK))


def pick_regions(world, n, cw, ch):
    """Pick the n busiest cw x ch areas, spread across the map."""
    scored = []
    for cy in range(0, NUM_CHUNKS - ch, 2):
        for cx in range(0, NUM_CHUNKS - cw, 2):
            objs = [o for dy in range(ch) for dx in range(cw) for o in world.ifix.get((cx + dx, cy + dy), [])]
            if objs:
                scored.append((len({o[3] for o in objs}) * 4 + len(objs), cx, cy))
    scored.sort(reverse=True)
    picked = []
    for _, cx, cy in scored:
        if all(abs(cx - px) > 24 or abs(cy - py) > 24 for px, py in picked):
            picked.append((cx, cy))
        if len(picked) == n:
            break
    return picked


def sheet(frames, palette, cols, bg=0, pad=4):
    frames = [f for f in frames if f is not None]
    if not frames:
        return None
    cw = max(f.w for f in frames) + pad
    chh = max(f.h for f in frames) + pad
    rows = (len(frames) + cols - 1) // cols
    img = Image.new("P", (cols * cw, rows * chh), bg)
    img.putpalette(palette)
    for i, f in enumerate(frames):
        r, c = divmod(i, cols)
        im = f.image(palette)
        mask = im.point(lambda v: 0 if v == TRANSPARENT else 255, "L")
        img.paste(im, (c * cw + pad // 2, r * chh + pad // 2), mask)
    return img


def main():
    args = sys.argv[1:]
    nscenes = 5
    if "--scenes" in args:
        i = args.index("--scenes")
        nscenes = int(args[i + 1])
        del args[i:i + 2]
    static, out = args
    os.makedirs(out, exist_ok=True)
    palette = load_palette(static)
    shapes = Shapes(find(static, "shapes.vga"))
    world = World(static)

    cw, ch = 3, 2    # 384x256, close to the game's 320x200 view.
    for i, (cx, cy) in enumerate(pick_regions(world, nscenes, cw, ch)):
        path = os.path.join(out, "scene-%02d.png" % (i + 1))
        render(world, shapes, palette, cx, cy, cw, ch).save(path)
        print(path, "chunks", cx, cy)

    avatar = sheet([shapes.frame(AVATAR_SHAPE, fr) for fr in range(32)], palette, 8)
    if avatar:
        avatar.save(os.path.join(out, "avatar.png"))
        print(os.path.join(out, "avatar.png"))
    tiles = sheet([shapes.frame(sh, 0) for sh in range(FIRST_OBJ_SHAPE)], palette, 15, pad=0)
    if tiles:
        tiles.save(os.path.join(out, "tiles.png"))
        print(os.path.join(out, "tiles.png"))


if __name__ == "__main__":
    main()
