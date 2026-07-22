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

"""Seed languages/ml/lexicon.txt from the Olam open datasets (https://olam.in/p/open).

Downloads the Datuk corpus (Malayalam headwords, ODbL 1.0) and the E.K. Kurup corpus
(EN-ML synsets, CC BY-SA 4.0) into dumps/, extracts every single-token Malayalam word,
and writes the sorted union. The build's combined stage appends lexicon words that the
ranked wordfreq/varnam set doesn't already contain at a floor frequency: valid for
spell-check and autocorrect, completable, but never outranking corpus-frequency words.

    tools/olam.py ml
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

SOURCES = {
    "datuk": "https://olam.in/files/datuk.tar.gz",
    "ekkurup": "https://olam.in/files/ekkurup.tar.gz",
}

# The dumps write the AI vowel sign as two E signs (no NFC recomposition exists) and
# use ZWJ-sequence chillus; both would enter the dictionary as look-alike misspellings.
CHILLU = {
    "ന്‍": "ൻ", "ണ്‍": "ൺ",
    "ര്‍": "ർ", "ല്‍": "ൽ",
    "ള്‍": "ൾ", "ക്‍": "ൿ",
}
FAKE_AI = "െെ"
AI = "ൈ"

EKKURUP_ML = re.compile(r"^\s*ml: \[(.*)\]\s*$")


def normalize(word):
    word = unicodedata.normalize("NFC", word.strip())
    word = word.replace(FAKE_AI, AI)
    for seq, atomic in CHILLU.items():
        word = word.replace(seq, atomic)
    return word


def fetch(name):
    dest = REPO / "dumps" / f"{name}.tar.gz"
    if not dest.exists():
        dest.parent.mkdir(parents=True, exist_ok=True)
        print(f"downloading {SOURCES[name]}")
        # olam.in 403s the default Python User-Agent.
        req = urllib.request.Request(SOURCES[name], headers={"User-Agent": "curl/8"})
        with urllib.request.urlopen(req) as resp:
            dest.write_bytes(resp.read())
    return dest


def datuk_words():
    with tarfile.open(fetch("datuk")) as tar:
        data = tar.extractfile("files/datuk").read().decode("utf-8")
    lines = iter(data.splitlines())
    next(lines)
    return {normalize(line.split("\t")[0]) for line in lines if "\t" in line}


def ekkurup_words():
    words = set()
    with tarfile.open(fetch("ekkurup")) as tar:
        stream = io.TextIOWrapper(tar.extractfile("ekkurup.yml"), encoding="utf-8")
        for line in stream:
            match = EKKURUP_ML.match(line)
            if not match:
                continue
            for item in re.split(r"[\[\],]", match.group(1)):
                word = normalize(item)
                if word and " " not in word:
                    words.add(word)
    return words


def main():
    code = sys.argv[1] if len(sys.argv) > 1 else "ml"
    if code != "ml":
        sys.exit("the Olam datasets are Malayalam-only")
    meta = json.loads((REPO / "languages" / code / "meta.json").read_text())
    pat = re.compile("^" + char_class(meta["ranges"]) + "+$")
    words = {w for w in datuk_words() | ekkurup_words()
             if len(w) <= 48 and pat.match(w) and base_count(w) >= MIN_BASES
             and unicodedata.category(w[0]) not in ("Mn", "Mc")}
    out = REPO / "languages" / code / "lexicon.txt"
    out.write_text("\n".join(sorted(words)) + "\n", encoding="utf-8")
    print(f"{code}: {len(words):,} lexicon words -> {out}")


if __name__ == "__main__":
    main()
