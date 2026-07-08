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

"""Build every language artifact from one canonical per-language word source.

Each languages/<code>/ holds the committed sources — a curated wordfreq.txt ("word count"
lines), meta.json, and (for varnam languages) scheme/<code>.{scheme,vst}. From those this
script derives, per language:

  <code>.combined    LatinIME word list (frequency reweighted to 15-254 + header)
  main_<code>.dict   binary dictionary for the non-transliteration layouts (via dicttool)
  <code>-*.vlf       govarnam learnings packs + pack.json (varnam languages only)
  <code>.zip         the downloadable bundle, with sha256 recorded in index.json

Intermediate artifacts live in build/<code>/; the published zips + index.json land in dist/.
Stages are separate subcommands so a single language or a single artifact can be rebuilt; see
the Makefile for the per-language entry points.
"""

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import zipfile
from pathlib import Path

REPO = Path(__file__).resolve().parent
LANGUAGES = REPO / "languages"
BUILD = REPO / "build"
DIST = REPO / "dist"
DICTTOOL_JAR = REPO / "tools" / "dicttool_aosp.jar"
EXPORT_WORDS_PER_FILE = 30000

sys.path.insert(0, str(REPO / "tools"))
from extract import char_class, base_count, MIN_BASES  # single-source the word filters  # noqa: E402


def java_bin():
    if os.environ.get("JAVA"):
        return os.environ["JAVA"]
    if os.environ.get("JAVA_HOME"):
        return str(Path(os.environ["JAVA_HOME"]) / "bin" / "java")
    return "java"


def meta_of(code):
    return json.loads((LANGUAGES / code / "meta.json").read_text(encoding="utf-8"))


def all_codes():
    return sorted(p.name for p in LANGUAGES.iterdir()
                  if p.is_dir() and (p / "meta.json").exists())


def sha256_of(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


# ---- stages ----

def _words_from_wordfreq(code):
    src = LANGUAGES / code / "wordfreq.txt"
    if not src.exists():
        raise FileNotFoundError(f"{src} missing (seed it from a crawl: make extract LANG={code})")
    words = []
    for line in src.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            words.append(line.rsplit(" ", 1)[0])  # the frequency only fixed the sort order
    return words


def _words_from_vlf(code):
    """The govarnam-sanitized word set, in descending-confidence (page) order."""
    pack_dir = BUILD / code
    vlfs = sorted(pack_dir.glob("*-*.vlf"),
                  key=lambda p: (p.stem.rsplit("-", 1)[0], int(p.stem.rsplit("-", 1)[1])))
    if not vlfs:
        build_varnam(code)
        vlfs = sorted(pack_dir.glob("*-*.vlf"),
                      key=lambda p: (p.stem.rsplit("-", 1)[0], int(p.stem.rsplit("-", 1)[1])))
    words = []
    for vlf in vlfs:
        for entry in json.loads(vlf.read_text(encoding="utf-8")).get("words", []):
            words.append(entry["w"])
    return words


def _clean_words(code, words):
    """Drop out-of-script tokens and single-grapheme fragments (e.g. ൽ, ന്, സി, –)."""
    ranges = meta_of(code).get("ranges")
    pat = re.compile("^" + char_class(ranges) + "+$") if ranges else None
    return [w for w in words
            if base_count(w) >= MIN_BASES and (pat is None or pat.match(w))]


def _bigrams_for(code, words, weights):
    """Per-head next-word entries from languages/<code>/bigramfreq.txt, or {} if absent.

    Selection guards against the v2 binary format's floor: a bigram's stored probability is
    reconstructed relative to the TARGET word's unigram weight, so a very frequent successor
    listed anywhere in the list would always outrank content successors. Such a successor is
    kept only when it genuinely is the head's top next word.
    """
    src = LANGUAGES / code / "bigramfreq.txt"
    if not src.exists():
        return {}
    meta = meta_of(code)
    per_word = meta.get("bigrams_per_word", 5)
    cutoff = meta.get("bigram_unigram_cutoff", 240)

    kept = set(words)
    successors = {}
    for line in src.read_text(encoding="utf-8").splitlines():
        parts = line.split()
        if len(parts) != 3:
            continue
        w1, w2, count = parts
        if w1 not in kept or w2 not in kept or w1 == w2:
            continue
        successors.setdefault(w1, []).append((int(count), w2))

    result = {}
    for head, cands in successors.items():
        cands.sort(key=lambda t: -t[0])
        chosen = []
        for i, (_, target) in enumerate(cands):
            if len(chosen) >= per_word:
                break
            if i > 0 and weights[target] >= cutoff:
                continue
            chosen.append(target)
        if chosen:
            result[head] = chosen
    return result


def build_combined(code, version):
    """Build build/<code>/<code>.combined (rank-based reweight to 15..254).

    For varnam languages the words come from the exported .vlf — i.e. govarnam's sanitized,
    conjunct-validated set — so the LatinIME dictionary gets the same cleaning as the transliteration
    packs. Other languages use wordfreq.txt directly. Either way the words are then script-filtered
    to the language's Unicode ranges, so no out-of-script tokens reach the dictionary.

    If languages/<code>/bigramfreq.txt exists (seeded by tools/extract.py from the same dump),
    each word also gets next-word `bigram=` entries, which is what the suggestion strip's
    next-word prediction runs on.
    """
    meta = meta_of(code)
    words = _words_from_vlf(code) if meta.get("has_varnam") else _words_from_wordfreq(code)
    kept = _clean_words(code, words)
    if len(kept) != len(words):
        print(f"{code}: filter dropped {len(words) - len(kept):,} of {len(words):,} words")
    words = kept

    out_dir = BUILD / code
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"{code}.combined"

    n = len(words)
    divider = n // 240 + 1
    weights = {w: min(254, (n - rank) // divider + 15) for rank, w in enumerate(words)}
    bigrams = _bigrams_for(code, words, weights)
    header = (f"dictionary=main:{code},locale={code},"
              f"description={meta['name']} wordlist. Author: Jishnu Mohan <jishnu7@gmail.com>,"
              f"date={int(time.time())},version={version}")
    ngram_count = 0
    with open(out, "w", encoding="utf-8") as f:
        f.write(header + "\n")
        for word in words:
            f.write(f" word={word},f={weights[word]}\n")
            for i, target in enumerate(bigrams.get(word, ())):
                f.write(f"  bigram={target},f={max(1, 200 - 8 * i)}\n")
                ngram_count += 1
    print(f"{code}: {n:,} words, {ngram_count:,} bigrams -> {out}")
    return out


def build_dict(code, version):
    """<code>.combined -> build/<code>/main_<code>.dict via the committed dicttool jar."""
    combined = BUILD / code / f"{code}.combined"
    if not combined.exists():
        build_combined(code, version)
    out = BUILD / code / f"main_{code}.dict"
    subprocess.run(
        [java_bin(), "-jar", str(DICTTOOL_JAR), "makedict", "-s", str(combined), "-d", str(out)],
        check=True)
    print(f"{code}: -> {out}")
    return out


def build_xlit(code, version):
    """Romanized gesture dictionary: build/<code>/xlit_<code>.dict.

    Reverse-transliterates the curated word list (via tools/reverse-translit + the varnam
    scheme) into Latin-script words the gesture decoder can match when a transliteration
    layout is active; the keyboard then live-transliterates the decoded word back. Case is
    kept: varnam patterns are case-significant (veeT -> വീട്) and the decoder matches keys
    case-insensitively while outputting the stored form.
    """
    meta = meta_of(code)
    if not meta.get("has_varnam"):
        return None
    driver = REPO / "tools" / "reverse-translit" / "reverse-translit"
    if not driver.exists():
        raise FileNotFoundError(f"{driver} missing — run 'make reverse-translit' first")
    combined = BUILD / code / f"{code}.combined"
    if not combined.exists():
        build_combined(code, version)

    words = []
    weights = {}
    for line in combined.read_text(encoding="utf-8").splitlines():
        m = re.match(r"^ word=([^,]+),f=(\d+)", line)
        if m:
            words.append(m.group(1))
            weights[m.group(1)] = int(m.group(2))

    env = dict(os.environ)
    env["VARNAM_VST_DIR"] = str((LANGUAGES / code / "scheme").resolve())
    env.setdefault("VARNAM_LEARNINGS_DIR", str((BUILD / code).resolve()))
    proc = subprocess.run([str(driver), meta.get("scheme_id", code)],
                          input="\n".join(words), capture_output=True, text=True,
                          check=True, env=env)

    roman = {}
    for line in proc.stdout.splitlines():
        try:
            word, pattern = line.split("\t")
        except ValueError:
            continue
        if not pattern.isascii() or not pattern.replace("'", "").isalpha():
            continue
        weight = weights.get(word, 15)
        if weight > roman.get(pattern, 0):
            roman[pattern] = weight

    out = BUILD / code / f"xlit_{code}.combined"
    header = (f"dictionary=xlit:{code},locale={code},"
              f"description={meta['name']} romanized gesture wordlist,"
              f"date={int(time.time())},version={version}")
    with open(out, "w", encoding="utf-8") as f:
        f.write(header + "\n")
        for pattern, weight in sorted(roman.items(), key=lambda kv: (-kv[1], kv[0])):
            f.write(f" word={pattern},f={weight}\n")

    dict_out = BUILD / code / f"xlit_{code}.dict"
    subprocess.run(
        [java_bin(), "-jar", str(DICTTOOL_JAR), "makedict", "-s", str(out), "-d", str(dict_out)],
        check=True)
    print(f"{code}: {len(roman):,} romanized words -> {dict_out}")
    for junk in (BUILD / code).glob("*.learnings*"):
        junk.unlink()
    return dict_out


def build_varnam(code):
    """Learn wordfreq.txt into govarnam packs (<packid>-N.vlf + pack.json); copy the vst."""
    meta = meta_of(code)
    if not meta.get("has_varnam"):
        return []
    scheme_id = meta.get("scheme_id", code)
    vst = LANGUAGES / code / "scheme" / f"{scheme_id}.vst"
    wordfreq = LANGUAGES / code / "wordfreq.txt"
    if not vst.exists():
        raise FileNotFoundError(f"{vst} missing")

    pack_dir = BUILD / code
    pack_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy(vst, pack_dir / f"{code}.vst")

    env = dict(os.environ)
    env["VARNAM_VST_DIR"] = str((LANGUAGES / code / "scheme").resolve())
    env["VARNAM_LEARNINGS_DIR"] = str(pack_dir.resolve())

    produced = []
    for pack_id in meta.get("packs", []):
        for stale in pack_dir.glob(f"{pack_id}-*.vlf"):
            stale.unlink()
        subprocess.run(["varnamcli", "-s", scheme_id, "-learn-from-file", str(wordfreq)],
                       check=True, env=env)
        patterns = LANGUAGES / code / "patterns.txt"
        if patterns.exists():
            subprocess.run(["varnamcli", "-s", scheme_id, "-train-from-file", str(patterns)],
                           check=True, env=env)
        subprocess.run(["varnamcli", "-s", scheme_id, "-export", str(pack_dir / pack_id),
                        "-export-words-per-file", str(EXPORT_WORDS_PER_FILE)],
                       check=True, env=env)
        pages = sorted(pack_dir.glob(f"{pack_id}-*.vlf"),
                       key=lambda p: int(p.stem.rsplit("-", 1)[1]))
        produced += pages
        _write_pack_json(pack_dir / f"{pack_id}.json", meta, pack_id, pages)
    # govarnam leaves a learnings db behind; it isn't part of the pack.
    for junk in pack_dir.glob("*.learnings*"):
        junk.unlink()
    print(f"{code}: {len(produced)} vlf page(s)")
    return produced


def _write_pack_json(path, meta, pack_id, pages):
    page_meta, total = [], 0
    for i, vlf in enumerate(pages, 1):
        text = vlf.read_text(encoding="utf-8")
        first = re.search(r'"c":(.*?),', text)
        page_meta.append({
            "identifier": vlf.stem, "page": i,
            "description": "Words with confidence lesser than "
                           + (first.group(1) if first else "0"),
            "size": vlf.stat().st_size,
        })
        total += text.count('"c"')
    path.write_text(json.dumps({
        "identifier": pack_id, "name": f"{meta['name']} Basic",
        "description": f"Words sourced from {meta['name']} Wikipedia.",
        "lang": meta["code"], "pages_count": len(pages), "total_words": total,
        "pages": page_meta,
    }, indent=2, ensure_ascii=False), encoding="utf-8")


def build_pack(code, version, base_url):
    """Zip a language's artifacts into dist/<code>.zip and write a dist/<code>.json sidecar."""
    meta = meta_of(code)
    src = BUILD / code
    DIST.mkdir(parents=True, exist_ok=True)
    zip_path = DIST / f"{code}.zip"

    members, contents = [], {}
    dict_file = src / f"main_{code}.dict"
    if dict_file.exists():
        members.append(dict_file)
        contents["dict"] = dict_file.name
    xlit_file = src / f"xlit_{code}.dict"
    if xlit_file.exists():
        members.append(xlit_file)
        contents["xlit"] = xlit_file.name
    if meta.get("has_varnam"):
        vst = src / f"{code}.vst"
        if vst.exists():
            members.append(vst)
            contents["vst"] = vst.name
        vlfs = sorted(src.glob("*.vlf"))
        members += vlfs
        members += sorted(src.glob("*.json"))  # pack.json(s)
        contents["vlf"] = [v.name for v in vlfs]

    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for m in members:
            zf.write(m, arcname=m.name)

    entry = {
        "id": code, "lang": code, "name": meta["name"],
        "has_varnam": bool(meta.get("has_varnam")),
        "file": zip_path.name, "size": zip_path.stat().st_size,
        "sha256": sha256_of(zip_path), "version": version, "contents": contents,
    }
    if base_url:
        entry["url"] = f"{base_url.rstrip('/')}/{zip_path.name}"
    (DIST / f"{code}.json").write_text(json.dumps(entry, ensure_ascii=False), encoding="utf-8")
    print(f"{code}: {entry['size']:,} bytes  sha256={entry['sha256'][:12]}…  -> {zip_path}")
    return entry


def build_index(version=None):
    """Aggregate the dist/<code>.json sidecars into dist/index.json."""
    schemes = []
    for sidecar in sorted(DIST.glob("*.json")):
        if sidecar.name == "index.json":
            continue
        schemes.append(json.loads(sidecar.read_text(encoding="utf-8")))
    if version is None:
        version = max((s.get("version", 1) for s in schemes), default=1)
    index = {"version": version, "schemes": schemes}
    (DIST / "index.json").write_text(json.dumps(index, indent=2, ensure_ascii=False),
                                     encoding="utf-8")
    print(f"wrote {DIST / 'index.json'} ({len(schemes)} languages)")


def build_lang(code, version, base_url):
    build_varnam(code)  # varnam langs: produces the .vlf that build_combined sanitizes from
    build_combined(code, version)
    build_dict(code, version)
    build_xlit(code, version)
    return build_pack(code, version, base_url)


def _dict_info(path):
    """(words, bigrams) as reported by `dicttool info` for a .dict file."""
    out = subprocess.run([java_bin(), "-jar", str(DICTTOOL_JAR), "info", str(path)],
                         check=True, capture_output=True, text=True).stdout
    words = bigrams = 0
    for line in out.splitlines():
        if line.startswith("Words in the dictionary"):
            words = int(line.rsplit(":", 1)[1])
        elif line.startswith("Bigram count"):
            bigrams = int(line.rsplit(":", 1)[1])
    return words, bigrams


def _human(n):
    if n >= 1024 ** 2:
        return f"{n / 1024 ** 2:.1f}M"
    if n >= 1024:
        return f"{n / 1024:.0f}K"
    return f"{n}B"


def print_stats():
    """Per-language stats of the shipped packs, read from dist/<code>.zip only."""
    header = (f"{'lang':5} {'zip':>8} {'dict':>8} {'words':>8} {'bigrams':>8} "
              f"{'xlit':>8} {'xlit wds':>8} {'vlf':>9}")
    print(header)
    print("-" * len(header))
    totals = [0, 0, 0, 0, 0, 0]
    with tempfile.TemporaryDirectory() as tmp:
        for code in all_codes():
            zip_path = DIST / f"{code}.zip"
            if not zip_path.exists():
                print(f"{code:5} not built")
                continue
            with zipfile.ZipFile(zip_path) as zf:
                names = zf.namelist()
                dict_name = next((n for n in names if n == f"main_{code}.dict"), None)
                xlit_name = next((n for n in names if n == f"xlit_{code}.dict"), None)
                vlf_size = sum(i.file_size for i in zf.infolist() if i.filename.endswith(".vlf"))
                words = bigrams = xlit_words = dict_size = xlit_size = 0
                for name, is_xlit in ((dict_name, False), (xlit_name, True)):
                    if name is None:
                        continue
                    w, b = _dict_info(zf.extract(name, Path(tmp) / code))
                    if is_xlit:
                        xlit_words, xlit_size = w, zf.getinfo(name).file_size
                    else:
                        words, bigrams, dict_size = w, b, zf.getinfo(name).file_size
            zip_size = zip_path.stat().st_size
            print(f"{code:5} {_human(zip_size):>8} {_human(dict_size):>8} {words:>8,} "
                  f"{bigrams:>8,} {_human(xlit_size):>8} {xlit_words:>8,} {_human(vlf_size):>9}")
            for i, v in enumerate((zip_size, dict_size, words, bigrams, xlit_size, xlit_words)):
                totals[i] += v
    print("-" * len(header))
    print(f"{'total':5} {_human(totals[0]):>8} {_human(totals[1]):>8} {totals[2]:>8,} "
          f"{totals[3]:>8,} {_human(totals[4]):>8} {totals[5]:>8,}")


# ---- cli ----

def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--version", type=int, default=None,
                    help="override the data version stamped on packs (default: each "
                         "language's meta.json version; drives update detection)")
    ap.add_argument("--base-url", default="",
                    help="base URL prepended to each zip's url field in index.json")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("combined", "dict", "xlit", "varnam", "pack", "lang"):
        sub.add_parser(name).add_argument("code")
    sub.add_parser("index")
    sub.add_parser("stats")
    p_all = sub.add_parser("all")
    p_all.add_argument("--langs", nargs="*", help="subset of language codes (default: all)")
    p_langs = sub.add_parser("langs")
    p_langs.add_argument("--varnam", action="store_true",
                         help="list only languages with a varnam scheme")
    args = ap.parse_args()

    if args.cmd == "langs":
        codes = [c for c in all_codes()
                 if not args.varnam or meta_of(c).get("has_varnam")]
        print(" ".join(codes))
        return

    def version_for(code):
        return args.version if args.version is not None \
            else meta_of(code).get("version", 1)

    if args.cmd == "combined":
        build_combined(args.code, version_for(args.code))
    elif args.cmd == "dict":
        build_dict(args.code, version_for(args.code))
    elif args.cmd == "xlit":
        build_xlit(args.code, version_for(args.code))
    elif args.cmd == "varnam":
        build_varnam(args.code)
    elif args.cmd == "pack":
        build_pack(args.code, version_for(args.code), args.base_url)
    elif args.cmd == "lang":
        build_lang(args.code, version_for(args.code), args.base_url)
    elif args.cmd == "index":
        build_index(args.version)
    elif args.cmd == "stats":
        print_stats()
    elif args.cmd == "all":
        for code in (args.langs or all_codes()):
            if not (LANGUAGES / code / "wordfreq.txt").exists():
                print(f"{code}: no wordfreq.txt yet — skipping (run a crawl to seed it)")
                continue
            build_lang(code, version_for(code), args.base_url)
        build_index(args.version)


if __name__ == "__main__":
    main()
