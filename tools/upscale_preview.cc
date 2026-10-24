/*
 *  upscale_preview: run Exult's own pixel-art scalers on a paletted image.
 *
 *  Usage: upscale_preview IN.png OUT_PREFIX
 *  Writes OUT_PREFIX-point4x.png, -hq4x.png and -4xbr.png, so art can be
 *  compared offline with exactly what the in-game scalers produce.
 */

#ifdef HAVE_CONFIG_H
#	include <config.h>
#endif

#include "common_types.h"
// The scaler kernels live in the .cc files alongside Image_window glue.
#include "imagewin/scale_hq4x.cc"
#include "imagewin/scale_xbr.cc"

#include <SDL3_image/SDL_image.h>

#include <cstring>
#include <iostream>
#include <string>
#include <vector>

SDL_PixelFormatDetails ManipBase::fmt;
SDL_Color              ManipBase::colors[256];

namespace {
	constexpr int guard = 4;    // Scalers read a few pixels past the edges.
	constexpr int scale = 4;

	bool save(SDL_Surface* surf, const std::string& name) {
		if (!IMG_SavePNG(surf, name.c_str())) {
			std::cerr << "Failed to write " << name << ": " << SDL_GetError() << std::endl;
			return false;
		}
		std::cout << name << std::endl;
		return true;
	}
}    // namespace

int main(int argc, char** argv) {
	if (argc != 3) {
		std::cerr << "Usage: upscale_preview IN.png OUT_PREFIX" << std::endl;
		return 1;
	}
	SDL_Surface* in = IMG_Load(argv[1]);
	if (!in) {
		std::cerr << "Failed to read " << argv[1] << ": " << SDL_GetError() << std::endl;
		return 1;
	}
	SDL_Palette* pal = SDL_GetSurfacePalette(in);
	if (in->format != SDL_PIXELFORMAT_INDEX8 || !pal) {
		std::cerr << argv[1] << " is not an 8-bit paletted image" << std::endl;
		return 1;
	}
	const int w = in->w;
	const int h = in->h;

	// Copy into a buffer with an edge-replicated guard band.
	const int                  sw = w + 2 * guard;
	const int                  sh = h + 2 * guard;
	std::vector<unsigned char> src(static_cast<size_t>(sw) * sh);
	const auto*                pixels = static_cast<const unsigned char*>(in->pixels);
	for (int y = 0; y < sh; y++) {
		const int sy = std::min(std::max(y - guard, 0), h - 1);
		for (int x = 0; x < sw; x++) {
			const int sx                           = std::min(std::max(x - guard, 0), w - 1);
			src[static_cast<size_t>(y) * sw + x] = pixels[sy * in->pitch + sx];
		}
	}

	SDL_Color colors[256] = {};
	std::memcpy(colors, pal->colors, sizeof(SDL_Color) * std::min(pal->ncolors, 256));

	const std::string prefix = argv[2];
	bool              ok     = true;
	auto              run    = [&](const char* name, auto scaler) {
        SDL_Surface* out = SDL_CreateSurface(sw * scale, sh * scale, SDL_PIXELFORMAT_XRGB8888);
        const SDL_PixelFormatDetails* fmt = SDL_GetPixelFormatDetails(out->format);
        const Manip8to32              manip(colors, fmt);
        scaler(src.data(), sw, sh, static_cast<uint32*>(out->pixels), out->pitch / 4, manip);
        // Crop the guard band back off.
        SDL_Surface*    cropped = SDL_CreateSurface(w * scale, h * scale, SDL_PIXELFORMAT_XRGB8888);
        const SDL_Rect  srect{guard * scale, guard * scale, w * scale, h * scale};
        SDL_BlitSurface(out, &srect, cropped, nullptr);
        ok = save(cropped, prefix + "-" + name + ".png") && ok;
        SDL_DestroySurface(cropped);
        SDL_DestroySurface(out);
	};

	run("point4x", [](unsigned char* s, int sw_, int sh_, uint32* d, int dline, const Manip8to32& manip) {
		for (int y = 0; y < sh_ * scale; y++) {
			for (int x = 0; x < sw_ * scale; x++) {
				d[y * dline + x] = manip.copy(s[(y / scale) * sw_ + x / scale]);
			}
		}
	});
	run("hq4x", [](unsigned char* s, int sw_, int sh_, uint32* d, int dline, const Manip8to32& manip) {
		Scale_Hq4x<uint32, Manip8to32>(s, 0, 0, sw_, sh_, sw_, sh_, d, dline, manip);
	});
	run("4xbr", [](unsigned char* s, int sw_, int sh_, uint32* d, int dline, const Manip8to32& manip) {
		Scale_xBR<uint32, Manip8to32, Scaler4xBR>(s, 0, 0, sw_, sh_, sw_, sh_, d, dline, manip);
	});

	SDL_DestroySurface(in);
	return ok ? 0 : 1;
}
