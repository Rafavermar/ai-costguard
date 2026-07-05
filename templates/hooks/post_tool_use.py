#!/usr/bin/env python
from __future__ import annotations

import sys

from costguard.hooks_runtime import post_tool_use_from_stdin


def main() -> None:
    sys.stdout.write(post_tool_use_from_stdin(sys.stdin.read()))


if __name__ == "__main__":
    main()
