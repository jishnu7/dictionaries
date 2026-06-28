#!/usr/bin/env python3
#
# Copyright 2026, Jishnu Mohan <jishnu7@gmail.com>
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Extract a word-frequency list for one language from its Wikipedia dump.

Streams dumps/<wiki>wiki-latest-pages-articles.xml.bz2 and writes
languages/<code>/wordfreq.candidate.txt (one "word count" line per word, frequency-sorted).

The candidate is meant to be diffed against the committed wordfreq.txt and merged by hand —
never written over it. Two filters, both driven by meta.json, fix the long-standing parser gaps:

  * script-limit: a token is kept only if every character lies inside the language's Unicode
    `ranges` (plus the joiners ZWNJ/ZWJ), so e.g. a Tamil word embedded in the ml wiki is
    dropped. Languages sharing a script (Devanagari hi/mr/sa/ne, Bengali bn/as) can't be told
    apart by script alone; that residue is left to curation.
  * min_freq / max_words: drop words seen fewer than `min_freq` times (tuned per wiki size),
    then keep at most `max_words`.
"""

import argparse
import bz2
import json
import re
import sys
import unicodedata
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
ZWNJ, ZWJ = "‌", "‍"
MIN_BASES = 2  # drop single-grapheme tokens (a chillu, a dead consonant, a consonant+matra)


def char_class(ranges):
    """Build a regex character class from meta.json `ranges` like ["0D00-0D7F"], + joiners."""
    parts = []
    for r in ranges:
        lo, hi = r.split("-")
        parts.append(f"\\u{int(lo, 16):04x}-\\u{int(hi, 16):04x}")
    parts.append("\\u200c\\u200d")  # ZWNJ, ZWJ
    return "[" + "".join(parts) + "]"


def base_count(word):
    """Number of base letters (≈ grapheme clusters): characters that aren't combining marks or
    joiners. In Indic scripts each cluster has exactly one base, so this counts orthographic
    syllables — words with fewer than MIN_BASES are single fragments, not words."""
    return sum(1 for c in word
               if unicodedata.category(c) not in ("Mn", "Mc", "Me") and c not in (ZWNJ + ZWJ))


def extract(meta, dump, out, min_freq, max_words):
    token = re.compile(char_class(meta["ranges"]) + "{2,}")
    counts = Counter()
    with bz2.open(dump, "rt", encoding="utf-8", errors="ignore") as f:
        for line in f:
            for tok in token.findall(line):
                tok = tok.strip(ZWNJ + ZWJ)
                if base_count(tok) >= MIN_BASES:
                    counts[tok] += 1

    words = [(w, c) for w, c in counts.items() if c >= min_freq]
    words.sort(key=lambda wc: (-wc[1], wc[0]))
    if max_words:
        words = words[:max_words]

    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", encoding="utf-8") as fh:
        for w, c in words:
            fh.write(f"{w} {c}\n")
    print(f"{meta['code']}: {len(counts):,} unique → {len(words):,} kept "
          f"(min_freq={min_freq}, max_words={max_words or 'all'}) → {out}")


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("code", help="language code (a languages/<code>/ dir with meta.json)")
    ap.add_argument("--dump", help="path to the .xml.bz2 dump "
                    "(default: dumps/<wiki>wiki-latest-pages-articles.xml.bz2)")
    ap.add_argument("--min-freq", type=int, help="override meta.json min_freq")
    ap.add_argument("--max-words", type=int, help="override meta.json max_words")
    args = ap.parse_args()

    lang_dir = REPO / "languages" / args.code
    meta = json.loads((lang_dir / "meta.json").read_text(encoding="utf-8"))
    dump = Path(args.dump) if args.dump else (
        REPO / "dumps" / f"{meta['wiki']}wiki-latest-pages-articles.xml.bz2")
    if not dump.exists():
        sys.exit(f"dump not found: {dump} (run tools/dwn.sh {meta['wiki']} first)")

    extract(
        meta, dump, lang_dir / "wordfreq.candidate.txt",
        args.min_freq if args.min_freq is not None else meta.get("min_freq", 2),
        args.max_words if args.max_words is not None else meta.get("max_words", 0),
    )


if __name__ == "__main__":
    main()
