#!/usr/bin/env python3
"""Shows the source lines behind the errors in a file saved by the DLL's call
tracing (fxc2_fail/*.hlsl), following #line directives the way the compiler
numbers them.

Usage: failsrc.py <saved.hlsl> [context-lines]
"""
import re
import sys


def main():
    text = open(sys.argv[1], "rb").read().decode("latin1")
    context = int(sys.argv[2]) if len(sys.argv) > 2 else 2
    end = text.index("*/")
    messages, body = text[:end], text[end + 3:]
    lines = body.split("\n")

    by_number, current = {}, 0
    for index, line in enumerate(lines):
        m = re.match(r"\s*#\s*line\s+(\d+)", line)
        if m:
            current = int(m.group(1)) - 1
            continue
        current += 1
        by_number.setdefault(current, []).append(index)

    seen = set()
    for message in messages.splitlines():
        m = re.search(r":(\d+):(\d+): (E\d+: .*)", message)
        if not m:
            continue
        key = re.sub(r"\d+|\"[^\"]*\"|'[^']*'", "N", m.group(3))
        if key in seen:
            continue
        seen.add(key)
        print("## line %s col %s: %s" % m.groups())
        for index in by_number.get(int(m.group(1)), [])[:1]:
            for i in range(max(0, index - context), min(len(lines), index + context + 1)):
                print("%s %s" % (">>" if i == index else "  ", lines[i][:220]))


if __name__ == "__main__":
    main()
