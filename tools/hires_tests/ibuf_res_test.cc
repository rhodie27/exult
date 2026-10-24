// Checks that an Image_buffer8 with res > 1 draws exactly like res 1, block for block.
#include "ibuf8.h"
#include "endianio.h"
#include <cstdio>
#include <cstdlib>
#include <vector>

static std::vector<unsigned char> make_rle(int w, int h, unsigned seed) {
	std::vector<unsigned char> d;
	auto put2 = [&](int v) { d.push_back(v & 0xff); d.push_back((v >> 8) & 0xff); };
	srand(seed);
	for (int y = 0; y < h; y++) {
		int x = rand() % 3;
		int len = 1 + rand() % (w - x);
		if (rand() % 2) {    // raw
			put2(len << 1); put2(x - w / 2); put2(y - h / 2);
			for (int i = 0; i < len; i++) d.push_back(rand() % 250);
		} else {             // encoded
			put2((len << 1) | 1); put2(x - w / 2); put2(y - h / 2);
			int b = 0;
			while (b < len) {
				int c = 1 + rand() % std::min(10, len - b);
				if (rand() % 2) { d.push_back((c << 1) | 1); d.push_back(rand() % 250); }
				else { d.push_back(c << 1); for (int i = 0; i < c; i++) d.push_back(rand() % 250); }
				b += c;
			}
		}
	}
	put2(0);
	return d;
}

int main() {
	const int W = 64, H = 48;
	int fails = 0;
	for (int R : {2, 3, 4}) {
		for (unsigned seed = 1; seed <= 200; seed++) {
			Image_buffer8 a(W, H), b(W, H, R);
			a.fill8(7); b.fill8(7);
			srand(seed * 7919);
			unsigned char src[40 * 40];
			for (auto& c : src) c = rand() % 4 ? rand() % 256 : 0;
			Xform_palette xf; for (int i = 0; i < 256; i++) xf.colors[i] = 255 - i;
			Xform_palette xfs[3]; for (int k = 0; k < 3; k++) for (int i = 0; i < 256; i++) xfs[k].colors[i] = (i + 17 * (k + 1)) & 255;
			for (int op = 0; op < 12; op++) {
				int kind = rand() % 12, x = rand() % 80 - 8, y = rand() % 60 - 6, w = 1 + rand() % 40, h = 1 + rand() % 40, v = rand() % 256;
				if (rand() % 3 == 0) { int cx = rand() % 40, cy = rand() % 30, cw = 10 + rand() % 40, ch = 10 + rand() % 30; a.set_clip(cx, cy, cw, ch); b.set_clip(cx, cy, cw, ch); }
				if (getenv("TRACE") && seed == 10 && R == 2) printf("op %d kind %d x %d y %d w %d h %d\n", op, kind, x, y, w, h);
				switch (kind) {
				case 0: a.fill8(v, w, h, x, y); b.fill8(v, w, h, x, y); break;
				case 1: a.fill_hline8(v, w, x, y); b.fill_hline8(v, w, x, y); break;
				case 2: a.copy8(src, w, h, x, y); b.copy8(src, w, h, x, y); break;
				case 3: a.copy_transparent8(src, w, h, x, y); b.copy_transparent8(src, w, h, x, y); break;
				case 4: a.copy_hline8(src, w, x, y); b.copy_hline8(src, w, x, y); break;
				case 5: a.fill_translucent8(0, w, h, x, y, xf); b.fill_translucent8(0, w, h, x, y, xf); break;
				case 6: a.fill_hline_translucent8(0, w, x, y, xf); b.fill_hline_translucent8(0, w, x, y, xf); break;
				case 7: a.copy_hline_translucent8(src, w, x, y, 100, 102, xfs); b.copy_hline_translucent8(src, w, x, y, 100, 102, xfs); break;
				case 8: { auto r = make_rle(20, 16, seed * 31 + op); a.paint_rle(x, y, r.data()); b.paint_rle(x, y, r.data()); break; }
				case 9: a.put_pixel8(v, x, y); b.put_pixel8(v, x, y); break;
				case 10: { int sx = rand() % 40, sy = rand() % 30; int cw = std::min(w, W - std::max(sx, x)), ch = std::min(h, H - std::max(sy, y));
					if (x >= 0 && y >= 0 && cw > 0 && ch > 0) { a.copy(sx, sy, cw, ch, x, y); b.copy(sx, sy, cw, ch, x, y); } break; }
				case 11: { auto ta = a.create_another(w, h); auto tb = b.create_another(w, h); static_cast<Image_buffer8*>(ta.get())->fill8(3); static_cast<Image_buffer8*>(tb.get())->fill8(3);
					a.get(ta.get(), x, y); b.get(tb.get(), x, y); int dx = rand() % 50, dy = rand() % 40; a.put(ta.get(), dx, dy); b.put(tb.get(), dx, dy); break; }
				}
				a.clear_clip(); b.clear_clip();
			}
			// Compare.
			for (int y = 0; y < H && !fails; y++)
				for (int x = 0; x < W; x++) {
					unsigned char ea = a.get_bits()[y * a.get_line_width() + x];
					for (int r = 0; r < R; r++) for (int k = 0; k < R; k++) {
						unsigned char eb = b.get_bits()[(y * R + r) * b.get_line_width() + x * R + k];
						if (ea != eb) { if (fails < 5) printf("R=%d seed=%u mismatch at %d,%d (+%d,%d): %d vs %d\n", R, seed, x, y, k, r, ea, eb); fails++; }
					}
				}
		}
	}
	printf(fails ? "FAIL %d\n" : "PASS\n", fails);
	return fails != 0;
}
