#!/usr/bin/env bash
# Cross-compiles vkd3d-compiler.exe (Wine's vkd3d-shader HLSL -> DXBC compiler)
# for 64-bit Windows from a Linux/WSL host, as a single static executable.
#
# Host packages (Debian/Ubuntu):
#   build-essential mingw-w64 autoconf automake libtool flex bison pkg-config
#   wine64-tools libwine-dev spirv-headers libvulkan-dev libjson-perl
#
# Usage: scripts/build-vkd3d.sh [git-ref]     (default: VKD3D_REF below)
set -euo pipefail

VKD3D_REF="${1:-cfcb4833}"
VKD3D_URL="https://gitlab.winehq.org/wine/vkd3d.git"
HOST=x86_64-w64-mingw32

REPO="$(cd "$(dirname "$0")/.." && pwd)"
WORK="${VKD3D_WORK:-$HOME/fxc2}"
SRC="$WORK/vkd3d"
BUILD="$WORK/build-$HOST"
XINC="$WORK/xinc"

mkdir -p "$WORK"
[ -d "$SRC" ] || git clone -q "$VKD3D_URL" "$SRC"
git -C "$SRC" fetch -q origin
git -C "$SRC" checkout -q "$VKD3D_REF"

# configure insists on Vulkan + SPIR-V headers even though vkd3d-compiler only
# needs the SPIR-V ones. Stage just those so no Linux system headers leak into
# the mingw include path.
rm -rf "$XINC" && mkdir -p "$XINC"
cp -r /usr/include/vulkan /usr/include/vk_video /usr/include/spirv "$XINC/"

[ -x "$SRC/configure" ] || (cd "$SRC" && ./autogen.sh)

mkdir -p "$BUILD" && cd "$BUILD"
# SONAME_LIBVULKAN skips the link check for vulkan-1; we never build libvkd3d.
[ -f Makefile ] || "$SRC/configure" --host="$HOST" \
    --disable-shared --enable-static \
    --disable-tests --disable-demos --disable-doxygen-doc \
    --without-xcb --without-ncurses --without-opengl \
    CPPFLAGS="-I$XINC" CFLAGS="-O2 -g0" LDFLAGS="-static" \
    SONAME_LIBVULKAN=vulkan-1.dll

# Plain "make" (not a single target) so BUILT_SOURCES (widl headers) get generated.
make -j"$(nproc)"
"$HOST-strip" -o "$REPO/bin/vkd3d-compiler.exe" vkd3d-compiler.exe
git -C "$SRC" describe --tags > "$REPO/bin/vkd3d-compiler.version"
ls -l "$REPO/bin/vkd3d-compiler.exe"
