# Hi-res rendering tests

Checks that drawing with `Image_buffer8::res` > 1 gives exactly the same
picture as the normal renderer when no hi-res art is present.

Build from the top of a configured, built tree:

    g++ -std=c++17 -O1 -g -fsanitize=address,undefined -DHAVE_CONFIG_H -I. -Iheaders -Iimagewin -Ifiles \
        $(pkg-config --cflags sdl3) tools/hires_tests/ibuf_res_test.cc imagewin/ibuf8.cc imagewin/imagebuf.cc \
        -o ibuf_res_test $(pkg-config --libs sdl3)

    g++ -std=c++17 -O1 -g -DHAVE_CONFIG_H -I. -Iheaders -Iimagewin -Ifiles -Iconf -Ishapes -Iobjs \
        $(pkg-config --cflags sdl3 sdl3-image) tools/hires_tests/iwin_res_test.cc exult-istring.o \
        imagewin/.libs/libimagewin.a conf/.libs/libconf.a files/.libs/libu7file.a \
        -o iwin_res_test $(pkg-config --libs sdl3 sdl3-image) -lpng16 -lz

Both print PASS on success. `iwin_res_test` uses SDL's offscreen video driver.
