// Renders the same scene through Image_window8 at res 1 and res 2 and checks
// the final screen pixels match (point scaling, scale 4).
#include "ibuf8.h"
#include "iwin8.h"
#include <SDL3/SDL.h>
#include <SDL3_image/SDL_image.h>
#include <cstdio>
#include <algorithm>
#include <vector>

static std::vector<uint32_t> run(int res, int scaler, int fill_scaler, Image_window::FillMode fm, int& w, int& h) {
	Image_window::requested_res = res;
	Image_window8 win(1280, 800, 320, 200, 4, false, scaler, fm, fill_scaler);
	unsigned char pal[768];
	for (int i = 0; i < 256; i++) {
		pal[3 * i] = (i * 7) & 63; pal[3 * i + 1] = (i * 13) & 63; pal[3 * i + 2] = (i * 29) & 63;
	}
	Image_window8::set_gamma(1, 1, 1);
	win.set_palette(pal, 63);
	auto* ib = win.get_ib8();
	ib->clear_clip();
	ib->fill8(5);
	ib->fill8(77, 50, 40, 10, 10);
	ib->fill8(200, 60, 30, 270, 160);
	ib->draw_line8(150, 0, 0, 319, 199);
	for (int i = 0; i < 256; i++) ib->put_pixel8(i, i, 100);
	win.show();
	{
		SDL_Surface* d = win.get_draw_surface();
		printf("draw %dx%d pix %d %d\n", d->w, d->h, ((unsigned char*)d->pixels)[d->pitch * 50 + 100], ib->get_pixel8(15, 15));
		char pn[64];
		snprintf(pn, sizeof(pn), "/tmp/pal_%d.png", res);
		win.screenshot(SDL_IOFromFile(pn, "wb"), true);
	}
	char name[64];
	snprintf(name, sizeof(name), "/tmp/iwin_%d_%d_%d.png", res, scaler, fill_scaler);
	win.screenshot(SDL_IOFromFile(name, "wb"), false);
	SDL_Surface* s = IMG_Load(name);
	SDL_Surface* c = SDL_ConvertSurface(s, SDL_PIXELFORMAT_XRGB8888);
	w = c->w; h = c->h;
	std::vector<uint32_t> out(w * h);
	for (int y = 0; y < h; y++) memcpy(&out[y * w], (char*)c->pixels + y * c->pitch, w * 4);
	printf("res %d (actual %d): screen %dx%d ibuf %ux%u\n", res, win.get_res(), w, h, ib->get_width(), ib->get_height());
	SDL_DestroySurface(s); SDL_DestroySurface(c);
	return out;
}

int main() {
	SDL_SetHint(SDL_HINT_VIDEO_DRIVER, "offscreen");
	SDL_SetHint(SDL_HINT_RENDER_DRIVER, "software");
	if (!SDL_Init(SDL_INIT_VIDEO)) { printf("init: %s\n", SDL_GetError()); return 1; }
	int fails = 0;
	struct { int scaler, fill; Image_window::FillMode fm; const char* name; } cfgs[] = {
		{Image_window::point, Image_window::point, Image_window::Fit, "point/point fit"},
		{Image_window::point, Image_window::bilinear, Image_window::AspectCorrectCentre, "point/bilinear aspect"},
		{Image_window::point, Image_window::SDLScaler, Image_window::Fit, "point/SDL fit"},
	};
	for (auto& c : cfgs) {
		int w1, h1, w2, h2;
		auto a = run(1, c.scaler, c.fill, c.fm, w1, h1);
		auto b = run(c.fill == Image_window::point ? 4 : 2, c.scaler, c.fill, c.fm, w2, h2);
		std::vector<uint32_t> sorted(a);
		std::sort(sorted.begin(), sorted.end());
		printf("distinct colours: %ld\n", long(std::unique(sorted.begin(), sorted.end()) - sorted.begin()));
		int diff = 0;
		if (w1 != w2 || h1 != h2) diff = -1;
		else for (size_t i = 0; i < a.size(); i++) diff += a[i] != b[i];
		printf("%s: %d differing pixels\n", c.name, diff);
		fails += diff != 0;
	}
	printf(fails ? "FAIL\n" : "PASS\n");
	return fails;
}

// Stubs for things libimagewin pulls in from the game.
#include "Configuration.h"
#include "mouse.h"
Configuration* config = new Configuration();
Mouse* Mouse::current_mouse = nullptr;
void Mouse::apply_fast_offset(int&, int&) {}
void Mouse::unapply_fast_offset(int&, int&) {}
const char* get_text_msg(unsigned int) { return ""; }
#include "perf.h"
PerformanceTimer* PerformanceTimer::all    = nullptr;
PerformanceTimer* PerformanceTimer::active = nullptr;
int               PerformanceTimer::mode   = 0;
uint64 PerformanceTimer::GetNS() { return 0; }
void PerformanceTimer::paintPerfMetrics() {}
PerformanceTimer& PerformanceTimer::GetPerfTimer(std::string_view, std::string_view, bool) {
	static PerformanceTimer t;
	return t;
}
