/*
 *  ibuf8.h - 8-bit image buffer.
 *
 *  Copyright (C) 1998-1999  Jeffrey S. Freedman
 *  Copyright (C) 2000-2022  The Exult Team
 *
 *  This program is free software; you can redistribute it and/or modify
 *  it under the terms of the GNU General Public License as published by
 *  the Free Software Foundation; either version 2 of the License, or
 *  (at your option) any later version.
 *
 *  This program is distributed in the hope that it will be useful,
 *  but WITHOUT ANY WARRANTY; without even the implied warranty of
 *  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
 *  GNU General Public License for more details.
 *
 *  You should have received a copy of the GNU General Public License
 *  along with this program; if not, write to the Free Software
 *  Foundation, Inc., 59 Temple Place - Suite 330, Boston, MA 02111-1307, USA.
 */

#ifndef INCL_IBUF8
#define INCL_IBUF8 1

#include "imagebuf.h"

#include <cstring>

/*
 *  An 8-bit image buffer:
 */
class Image_buffer8 : public Image_buffer {
	bool bits_owned;

	// Private ctor. for Image_window8.
	Image_buffer8(unsigned int w, unsigned int h, Image_buffer*) : Image_buffer(w, h, 8), bits_owned(false) {}

public:
	Image_buffer8(unsigned int w, unsigned int h, int r = 1) : Image_buffer(w, h, 8), bits_owned(true) {
		res        = r;
		line_width = w * r;
		bits       = new unsigned char[w * r * h * r];
	}
	friend class Image_window8;

	// for Image_window::Layer to create a buffer backed by a SDL_Surface with a guard band
	Image_buffer8(unsigned int w, unsigned int h, unsigned int pitch, unsigned char* bits, int guard_band)
			: Image_buffer(w - guard_band * 2, h - guard_band * 2, 8), bits_owned(false) {
		this->line_width = pitch;
		this->bits       = bits + guard_band + pitch * guard_band;
	}

	~Image_buffer8() {
		if (!bits_owned) {
			bits = nullptr;
		}
	}

	/*
	 *  Depth-independent methods:
	 */
	std::unique_ptr<Image_buffer> create_another(int w, int h) override {
		return std::make_unique<Image_buffer8>(w, h, res);
	}

	// Copy within itself.
	void copy(int srcx, int srcy, int srcw, int srch, int destx, int desty) override;
	// Get rect. into another buf.
	void get(Image_buffer* dest, int srcx, int srcy) override;
	// Put rect. back.
	void put(Image_buffer* src, int destx, int desty) override;

	void fill_static(int black, int gray, int white) override;

	/*
	 *  8-bit color methods:
	 */
	// Fill with given (8-bit) value.
	void fill8(unsigned char pix) override;
	// Fill rect. wth pixel.
	void fill8(unsigned char pix, int srcw, int srch, int destx, int desty) override;
	// Fill line with pixel.
	void fill_hline8(unsigned char pix, int srcw, int destx, int desty) override;
	// Draw an arbitrary line from any point to any point inclusive. Accuracy
	// not guarenteed
	void draw_line8(unsigned char val, int startx, int starty, int endx, int endy, const Xform_palette* xform = nullptr) override;
	// Copy rectangle into here.
	void copy8(const unsigned char* src_pixels, int srcw, int srch, int destx, int desty) override;
	// Copy line to here.
	void copy_hline8(const unsigned char* src_pixels, int srcw, int destx, int desty) override;
	// Copy with translucency table.
	void copy_hline_translucent8(
			const unsigned char* src_pixels, int srcw, int destx, int desty, int first_translucent, int last_translucent,
			const Xform_palette* xforms) override;
	// Apply translucency to a line.
	void fill_hline_translucent8(unsigned char val, int srcw, int destx, int desty, const Xform_palette& xform) override;
	// Apply translucency to a rectangle
	void fill_translucent8(unsigned char val, int srcw, int srch, int destx, int desty, const Xform_palette& xform) override;
	// Copy rect. with transp. color.
	void copy_transparent8(const unsigned char* src_pixels, int srcw, int srch, int destx, int desty) override;

	// Get/put a single pixel.
	unsigned char get_pixel8(int x, int y) override {
		return *pixel_ptr(x, y);
	}

	void put_pixel8(unsigned char pix, int x, int y) override {
		if (x >= clipx && x < clipx + clipw && y >= clipy && y < clipy + cliph) {
			if (res == 1) {
				bits[y * line_width + x] = pix;
			} else {
				fill_block(pixel_ptr(x, y), pix, 1);
			}
		}
	}

	void paint_rle(int xoff, int yoff, const unsigned char* in);
	void paint_rle_remapped(int xoff, int yoff, const unsigned char* inptr, const unsigned char*& trans);

	// Paint high-resolution art: pixels is a (w x h) image at this buffer's
	// res, transparent where it equals 'transparent' (-1 for none), with its
	// origin at (xleft, yabove) in physical pixels. xoff/yoff are game
	// coordinates. Pixels from xfstart to 0xfe are translucent if xforms is
	// given, as in Shape_frame::paint_rle_translucent.
	void paint_hires(
			int xoff, int yoff, const unsigned char* pixels, int w, int h, int xleft, int yabove, int transparent,
			const unsigned char* trans = nullptr, const Xform_palette* xforms = nullptr, int xfstart = 0x100);

	void draw_beveled_box(
			int x, int y, int w, int h, int depth, uint8 colfill, uint8 coltop, uint8 coltr, uint8 colbottom, uint8 colbl,
			std::optional<uint8> coltlbr = {}) override;

private:
	// First physical pixel of game pixel (x, y).
	unsigned char* pixel_ptr(int x, int y) {
		return bits + y * res * line_width + x * res;
	}

	// Set an n game pixel wide run starting at 'to' (one res x res block per
	// game pixel) to a single value.
	void fill_block(unsigned char* to, unsigned char pix, int n) {
		for (int r = 0; r < res; r++, to += line_width) {
			std::memset(to, pix, n * res);
		}
	}

	// Write n game pixels from 'from', each expanded to a res x res block.
	void copy_blocks(unsigned char* to, const unsigned char* from, int n);

	// Shared body of paint_rle/paint_rle_remapped for res > 1.
	void paint_rle_scaled(int xoff, int yoff, const unsigned char* in, const unsigned char* trans);

};

#endif
