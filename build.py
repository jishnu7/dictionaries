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

"""Repackage varnamproject/schemes release zips into per-language packs for Indic Keyboard.

Source of truth is the upstream govarnam scheme data published at
https://github.com/varnamproject/schemes/releases — each <lang>.zip there contains a built,
govarnam-native VST (real symbol weights) and govarnam-format .vlf learnings packs. We download
those, flatten them, and emit:

    <lang>.zip      - flat archive of <lang>.vst + every .vlf (bare filenames at root)
    index.json      - manifest the keyboard's VarnamDownloadManager fetches

The keyboard downloads one zip per language, verifies sha256 against the index, and extracts it
(flattening) into filesDir/varnam/<lang>/.
"""

import argparse
import hashlib
import json
import tempfile
import urllib.request
import zipfile
from pathlib import Path

SCHEMES_RELEASE_BASE = "https://github.com/varnamproject/schemes/releases/download"

# Display names keyed by ISO code (the languages we ship).
LANG_NAMES = {
    "ml": "Malayalam",
    "hi": "Hindi",
    "bn": "Bengali",
    "kn": "Kannada",
    "gu": "Gujarati",
    "ta": "Tamil",
    "te": "Telugu",
}


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def download_scheme_zip(lang: str, tag: str, dst: Path) -> None:
    url = f"{SCHEMES_RELEASE_BASE}/{tag}/{lang}.zip"
    print(f"  fetching {url}")
    with urllib.request.urlopen(url) as resp, open(dst, "wb") as out:
        out.write(resp.read())


def description_of(extracted: Path, lang: str) -> str:
    """Best-effort description from the upstream <lang>-basic/pack.json."""
    pack = next(extracted.rglob(f"{lang}-basic/pack.json"), None)
    if pack:
        try:
            return json.load(open(pack, encoding="utf-8")).get("description", "")
        except Exception:
            pass
    return ""


def build_language(lang: str, tag: str, out_dir: Path, version: int) -> dict:
    zip_name = f"{lang}.zip"
    zip_path = out_dir / zip_name
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        upstream = tmp / "upstream.zip"
        download_scheme_zip(lang, tag, upstream)
        extracted = tmp / "extracted"
        with zipfile.ZipFile(upstream) as zf:
            zf.extractall(extracted)

        vst = next(extracted.rglob(f"{lang}.vst"), None)
        if vst is None:
            raise FileNotFoundError(f"{lang}.vst not found in upstream {lang}.zip")
        # Only some schemes ship trained .vlf dictionary packs (e.g. ml). VST-only languages
        # still transliterate; they just have no dictionary word suggestions until learned.
        vlfs = sorted(extracted.rglob("*.vlf"))

        # Flat archive (arcname = bare filename) so the keyboard extracts straight into
        # filesDir/varnam/<lang>/ without nested directories.
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.write(vst, arcname=vst.name)
            for vlf in vlfs:
                zf.write(vlf, arcname=vlf.name)

        return {
            "id": lang,
            "lang": lang,
            "name": LANG_NAMES.get(lang, lang),
            "description": description_of(extracted, lang),
            "file": zip_name,
            "size": zip_path.stat().st_size,
            "sha256": sha256_of(zip_path),
            "version": version,
            "contents": {"vst": vst.name, "vlf": [v.name for v in vlfs]},
        }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--schemes-tag", default="v1.8.0",
        help="varnamproject/schemes release tag to source data from (default: v1.8.0)")
    parser.add_argument(
        "--out", default="dist",
        help="output directory for zips + index.json (default: dist)")
    parser.add_argument(
        "--base-url", default="",
        help="base URL prepended to each zip's `url` field "
             "(e.g. https://github.com/<org>/<repo>/releases/download/<tag>)")
    parser.add_argument(
        "--version", type=int, default=1,
        help="data version stamped on every scheme (drives update detection)")
    parser.add_argument(
        "--langs", nargs="*", default=sorted(LANG_NAMES),
        help="language codes to build (default: all shipped languages)")
    args = parser.parse_args()

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    schemes = []
    for lang in args.langs:
        scheme = build_language(lang, args.schemes_tag, out_dir, args.version)
        if args.base_url:
            scheme["url"] = f"{args.base_url.rstrip('/')}/{scheme['file']}"
        schemes.append(scheme)
        print(f"packaged {lang}: {scheme['size']:,} bytes, "
              f"{len(scheme['contents']['vlf'])} vlf pack(s)  sha256={scheme['sha256'][:12]}…")

    index = {"version": args.version, "schemes_tag": args.schemes_tag, "schemes": schemes}
    with open(out_dir / "index.json", "w") as f:
        json.dump(index, f, indent=2, ensure_ascii=False)
    print(f"wrote {out_dir / 'index.json'} ({len(schemes)} schemes from schemes {args.schemes_tag})")


if __name__ == "__main__":
    main()
