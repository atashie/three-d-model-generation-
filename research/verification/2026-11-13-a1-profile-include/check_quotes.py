"""Check source-excerpts.txt against the fetched OrcaSlicer files: hashes and every quote.

    uv run python -I research/verification/2026-11-13-a1-profile-include/check_quotes.py \
        source-excerpts.txt SRC_DIR

SRC_DIR holds the files fetched from the v2.5.0 tag, by base name (PresetBundle.cpp ...).
A quote line is "src/libslic3r/<file>:<line>: <text>", optionally followed by three spaces
and a note in parentheses; the text must equal that source line, stripped.
"""
import hashlib
import pathlib
import re
import sys

src = pathlib.Path(sys.argv[2])
problems = quotes = hashes = 0
for line in pathlib.Path(sys.argv[1]).read_text(encoding="utf-8").splitlines():
    h = re.fullmatch(r"([0-9a-f]{64})  src/libslic3r/(\S+)", line.strip())
    if h:
        hashes += 1
        if hashlib.sha256((src / h[2]).read_bytes()).hexdigest() != h[1]:
            problems += 1
            print("HASH MISMATCH", h[2])
    m = re.fullmatch(r"src/libslic3r/(\S+?):(\d+): (.*?)(   \(.*\))?", line)
    if m:
        quotes += 1
        got = (src / m[1]).read_text(encoding="utf-8").splitlines()[int(m[2]) - 1].strip()
        if got != m[3].strip():
            problems += 1
            print("QUOTE MISMATCH", m[1], m[2])
print(f"{hashes} file hashes and {quotes} quotes checked, {problems} problems")
