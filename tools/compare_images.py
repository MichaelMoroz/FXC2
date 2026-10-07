#!/usr/bin/env python3
"""Compares two folders of PNGs with the same names (renders taken with two
compilers, see tools/unity_render_shaders.cs) and prints, per picture, the
largest channel difference and how many pixels differ by more than a few
levels.

    python tools/compare_images.py out/poi_render_fxc2/all out/poi_render_fxc/all
"""
import os
import sys

from PIL import Image, ImageChops


def main():
    a_dir, b_dir = sys.argv[1], sys.argv[2]
    worst = 0
    for name in sorted(os.listdir(a_dir)):
        if not name.endswith(".png") or not os.path.exists(os.path.join(b_dir, name)):
            continue
        a = Image.open(os.path.join(a_dir, name)).convert("RGB")
        b = Image.open(os.path.join(b_dir, name)).convert("RGB")
        diff = ImageChops.difference(a, b)
        data = diff.getdata()
        maximum = max(max(p) for p in data)
        over = sum(1 for p in data if max(p) > 3)
        flat = len(set(a.getdata())) <= 2
        worst = max(worst, maximum)
        print("%-40s max diff %3d/255, %6d of %d pixels differ by more than 3%s" % (
            name, maximum, over, a.width * a.height, "  (picture is one flat colour)" if flat else ""))
    return 0 if worst <= 3 else 1


if __name__ == "__main__":
    sys.exit(main())
