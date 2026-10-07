#!/usr/bin/env bash
# usage: commit_patch.sh <patchN.py> "<commit subject>"   (run inside WSL)
# Applies a patch script on top of the fxc2 branch, commits it, re-exports
# patches/ and rebuilds everything.
set -e
REPO=/mnt/c/Users/micha/Documents/FXC2
cd ~/fxc2/vkd3d
git checkout -q -f fxc2
python3 "$REPO/out/$1"
git -c user.name=fxc2 -c user.email=fxc2@localhost commit -q -am "$2"
rm -f "$REPO"/patches/*.patch
git format-patch -q -o "$REPO/patches" cfcb4833
cd "$REPO" && bash scripts/build-vkd3d.sh > /tmp/build.log 2>&1 && echo "build ok: $(ls patches | wc -l) patches"
