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

"""Seed languages/<code>/lexicon.txt from open dictionary datasets.

Sources per language:
  ml  Olam (https://olam.in/p/open): Datuk corpus (ODbL 1.0) + E.K. Kurup corpus
      (CC BY-SA 4.0)
  kn  Alar (https://alar.ink, https://github.com/alar-dict/data): ODbL 1.0,
      (c) V. Krishna

Extracts every single-token word of the language's script and writes the sorted
union. The build's combined stage appends lexicon words that the ranked
wordfreq/varnam set doesn't already contain at a floor frequency: valid for
spell-check and autocorrect, completable, but never outranking corpus-frequency
words.

    tools/lexicon.py ml
    tools/lexicon.py kn
"""

import io
import json
import re
import sys
import tarfile
import unicodedata
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools"))
from extract import char_class, base_count, MIN_BASES  # noqa: E402

# The Olam dumps write the AI vowel sign as two E signs (no NFC recomposition
# exists) and use ZWJ-sequence chillus; both would enter the dictionary as
# look-alike misspellings.
ML_CHILLU = {
    "ന്‍": "ൻ", "ണ്‍": "ൺ",
    "ര്‍": "ർ", "ല്‍": "ൽ",
    "ള്‍": "ൾ", "ക്‍": "ൿ",
}
ML_FAKE_AI = "െെ"
ML_AI = "ൈ"

EKKURUP_ML = re.compile(r"^\s*ml: \[(.*)\]\s*$")
ALAR_ENTRY = re.compile(r"^\s*entry: (.+)$")


def fetch(name, url):
    dest = REPO / "dumps" / name
    if not dest.exists():
        dest.parent.mkdir(parents=True, exist_ok=True)
        print(f"downloading {url}")
        # olam.in 403s the default Python User-Agent.
        req = urllib.request.Request(url, headers={"User-Agent": "curl/8"})
        with urllib.request.urlopen(req) as resp:
            dest.write_bytes(resp.read())
    return dest


def normalize_ml(word):
    word = unicodedata.normalize("NFC", word.strip())
    word = word.replace(ML_FAKE_AI, ML_AI)
    for seq, atomic in ML_CHILLU.items():
        word = word.replace(seq, atomic)
    return word


def normalize(word):
    return unicodedata.normalize("NFC", word.strip())


def olam_words():
    words = set()
    with tarfile.open(fetch("datuk.tar.gz", "https://olam.in/files/datuk.tar.gz")) as tar:
        data = tar.extractfile("files/datuk").read().decode("utf-8")
    lines = iter(data.splitlines())
    next(lines)
    words |= {normalize_ml(line.split("\t")[0]) for line in lines if "\t" in line}
    with tarfile.open(fetch("ekkurup.tar.gz", "https://olam.in/files/ekkurup.tar.gz")) as tar:
        stream = io.TextIOWrapper(tar.extractfile("ekkurup.yml"), encoding="utf-8")
        for line in stream:
            match = EKKURUP_ML.match(line)
            if not match:
                continue
            for item in re.split(r"[\[\],]", match.group(1)):
                word = normalize_ml(item)
                if word and " " not in word:
                    words.add(word)
    return words


def alar_words():
    # Both the head-word and definition lines use "entry:"; the script filter in
    # main() drops the English definition ones.
    src = fetch("alar.yml",
                "https://raw.githubusercontent.com/alar-dict/data/master/alar.yml")
    words = set()
    with open(src, encoding="utf-8") as f:
        for line in f:
            match = ALAR_ENTRY.match(line)
            if not match:
                continue
            word = normalize(match.group(1).strip("'\""))
            if word and " " not in word:
                words.add(word)
    return words


SOURCES = {
    "ml": olam_words,
    "kn": alar_words,
}


def main():
    if len(sys.argv) != 2 or sys.argv[1] not in SOURCES:
        sys.exit(f"usage: lexicon.py {{{','.join(sorted(SOURCES))}}}")
    code = sys.argv[1]
    meta = json.loads((REPO / "languages" / code / "meta.json").read_text())
    pat = re.compile("^" + char_class(meta["ranges"]) + "+$")
    words = {w for w in SOURCES[code]()
             if len(w) <= 48 and pat.match(w) and base_count(w) >= MIN_BASES
             and unicodedata.category(w[0]) not in ("Mn", "Mc")}
    out = REPO / "languages" / code / "lexicon.txt"
    out.write_text("\n".join(sorted(words)) + "\n", encoding="utf-8")
    print(f"{code}: {len(words):,} lexicon words -> {out}")


if __name__ == "__main__":
    main()
