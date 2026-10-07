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
git -C "$SRC" checkout -q -f "$VKD3D_REF"
for p in "$REPO"/patches/*.patch; do
    git -C "$SRC" apply --whitespace=nowarn "$p"
done

# configure insists on Vulkan + SPIR-V headers even though vkd3d-compiler only
# needs the SPIR-V ones. Stage just those so no Linux system headers leak into
# the mingw include path.
rm -rf "$XINC" && mkdir -p "$XINC"
cp -r /usr/include/vulkan /usr/include/vk_video /usr/include/spirv "$XINC/"

[ -x "$SRC/configure" ] || (cd "$SRC" && ./autogen.sh)

# d3dcompiler_47.dll wraps some of vkd3d-utils' entry points (retry with
# unrolling, call tracing). vkd3d builds as LTO objects, which objcopy cannot
# rename after the fact, so the originals are renamed at compile time instead
# and the wrappers in src/d3dcompiler_shim.c take over the public names.
RENAMES=""
for f in D3DCompile D3DCompile2 D3DReflect D3DGetBlobPart D3DStripShader D3DDisassemble D3DPreprocess; do
    RENAMES="$RENAMES -D$f=vkd3d_$f"
done

mkdir -p "$BUILD" && cd "$BUILD"
# VKD3D_NO_TRACE_MESSAGES: TRACE() evaluates its arguments even when tracing is
# off, and some of them format strings in the compiler's hottest loops.
# SONAME_LIBVULKAN skips the link check for vulkan-1; we never build libvkd3d.
[ -f Makefile ] || "$SRC/configure" --host="$HOST" \
    --disable-shared --enable-static \
    --disable-tests --disable-demos --disable-doxygen-doc \
    --without-xcb --without-ncurses --without-opengl \
    CPPFLAGS="-I$XINC $RENAMES -DVKD3D_NO_TRACE_MESSAGES" CFLAGS="-O2 -g0" LDFLAGS="-static" \
    SONAME_LIBVULKAN=vulkan-1.dll

# Plain "make" (not a single target) so BUILT_SOURCES (widl headers) get generated.
make -j"$(nproc)"
"$HOST-strip" -o "$REPO/bin/vkd3d-compiler.exe" vkd3d-compiler.exe
{ git -C "$SRC" describe --tags; ls "$REPO/patches"; } > "$REPO/bin/vkd3d-compiler.version"
ls -l "$REPO/bin/vkd3d-compiler.exe"

# fxc2.exe (fxc-compatible CLI) and a drop-in d3dcompiler_47.dll, both linked
# statically against libvkd3d-utils' implementation of the d3dcompiler API.
# libvkd3d only dlopens Vulkan for D3D12 device creation, which is never
# reached from the compiler entry points, so there is no Vulkan dependency.
LIBS="-L$BUILD/.libs -lvkd3d-utils -lvkd3d -lvkd3d-shader -lvkd3d-common"
CC="$HOST-gcc -O2 -s -static -Wall"
$CC $RENAMES -o "$REPO/bin/fxc2.exe" "$REPO/src/fxc2.c" $LIBS
$CC -shared -o "$REPO/bin/d3dcompiler_47.dll" "$REPO/src/d3dcompiler_shim.c" "$REPO/src/d3dcompiler_47.def" $LIBS

# For Unity: its shader compiler maps D3DCompiler_47.dll with a private loader,
# so it gets a dependency-free forwarding stub plus the real DLL under another
# name. See src/d3dcompiler_stub.c.
mkdir -p "$REPO/bin/unity"
$HOST-gcc -O2 -s -shared -nostdlib -nostartfiles -fno-asynchronous-unwind-tables -fno-builtin -Wall     -Wl,-e,DllMain -o "$REPO/bin/unity/D3DCompiler_47.dll"     "$REPO/src/d3dcompiler_stub.c" "$REPO/src/d3dcompiler_stub.def"
cp "$REPO/bin/d3dcompiler_47.dll" "$REPO/bin/unity/fxc2_d3dcompiler.dll"
ls -l "$REPO/bin"
