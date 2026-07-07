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

"""Extract word- and bigram-frequency lists for one language from its Wikipedia dump.

Streams dumps/<wiki>wiki-latest-pages-articles.xml.bz2 and writes
languages/<code>/wordfreq.candidate.txt (one "word count" line per word, frequency-sorted)
plus languages/<code>/bigramfreq.candidate.txt ("word1 word2 count" lines) feeding the
dictionary's next-word predictions.

The candidates are meant to be diffed against the committed wordfreq.txt / bigramfreq.txt and
merged by hand — never written over them. Two filters, both driven by meta.json, fix the
long-standing parser gaps:

  * script-limit: a token is kept only if every character lies inside the language's Unicode
    `ranges` (plus the joiners ZWNJ/ZWJ), so e.g. a Tamil word embedded in the ml wiki is
    dropped. Languages sharing a script (Devanagari hi/mr/sa/ne, Bengali bn/as) can't be told
    apart by script alone; that residue is left to curation.
  * min_freq / max_words: drop words seen fewer than `min_freq` times (tuned per wiki size),
    then keep at most `max_words`. Bigrams have their own `bigram_min_freq` / `max_bigrams`.

A pair is counted only when the two tokens are separated by nothing but whitespace, so
markup, punctuation and sentence boundaries all break adjacency.
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


def extract(meta, dump, out, min_freq, max_words, bigram_out=None,
            bigram_min_freq=None, max_bigrams=None):
    token = re.compile(char_class(meta["ranges"]) + "{2,}")
    counts = Counter()
    pair_counts = Counter()
    with bz2.open(dump, "rt", encoding="utf-8", errors="ignore") as f:
        for line in f:
            prev_tok = None
            prev_end = -1
            for m in token.finditer(line):
                tok = m.group().strip(ZWNJ + ZWJ)
                if base_count(tok) < MIN_BASES:
                    prev_tok = None
                    continue
                counts[tok] += 1
                if bigram_out is not None:
                    if prev_tok is not None and line[prev_end:m.start()].isspace():
                        pair_counts[(prev_tok, tok)] += 1
                    prev_tok = tok
                    prev_end = m.end()

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

    if bigram_out is None:
        return
    pairs = [(w1, w2, c) for (w1, w2), c in pair_counts.items() if c >= bigram_min_freq]
    pairs.sort(key=lambda p: (-p[2], p[0], p[1]))
    if max_bigrams:
        pairs = pairs[:max_bigrams]
    with open(bigram_out, "w", encoding="utf-8") as fh:
        for w1, w2, c in pairs:
            fh.write(f"{w1} {w2} {c}\n")
    print(f"{meta['code']}: {len(pair_counts):,} unique pairs → {len(pairs):,} kept "
          f"(bigram_min_freq={bigram_min_freq}, max_bigrams={max_bigrams or 'all'}) "
          f"→ {bigram_out}")


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("code", help="language code (a languages/<code>/ dir with meta.json)")
    ap.add_argument("--dump", help="path to the .xml.bz2 dump "
                    "(default: dumps/<wiki>wiki-latest-pages-articles.xml.bz2)")
    ap.add_argument("--min-freq", type=int, help="override meta.json min_freq")
    ap.add_argument("--max-words", type=int, help="override meta.json max_words")
    ap.add_argument("--no-bigrams", action="store_true",
                    help="skip the bigramfreq.candidate.txt output")
    args = ap.parse_args()

    lang_dir = REPO / "languages" / args.code
    meta = json.loads((lang_dir / "meta.json").read_text(encoding="utf-8"))
    dump = Path(args.dump) if args.dump else (
        REPO / "dumps" / f"{meta['wiki']}wiki-latest-pages-articles.xml.bz2")
    if not dump.exists():
        sys.exit(f"dump not found: {dump} (run tools/dwn.sh {meta['wiki']} first)")

    min_freq = args.min_freq if args.min_freq is not None else meta.get("min_freq", 2)
    extract(
        meta, dump, lang_dir / "wordfreq.candidate.txt",
        min_freq,
        args.max_words if args.max_words is not None else meta.get("max_words", 0),
        bigram_out=None if args.no_bigrams else lang_dir / "bigramfreq.candidate.txt",
        bigram_min_freq=meta.get("bigram_min_freq", min_freq),
        max_bigrams=meta.get("max_bigrams", 200000),
    )


if __name__ == "__main__":
    main()
