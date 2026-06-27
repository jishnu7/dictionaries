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

"""Package Varnam language data into one tarball per language plus an index.json.

Reads the varnam language data (under varnam/ by default), laid out as:

    varnam/<lang>/<lang>.vst
    varnam/<lang>/<lang>-basic/pack.json
    varnam/<lang>/<lang>-basic/<lang>-basic-N.vlf

Produces, under the output dir:

    <lang>.zip      - flat archive of <lang>.vst + every <lang>-basic-N.vlf
    index.json      - manifest the keyboard's VarnamDownloadManager fetches

Zip (not tar.gz) because Android's SDK extracts zip natively via
java.util.zip.ZipInputStream — no third-party archive dependency in the keyboard.

The keyboard downloads one zip per language, verifies its sha256 against the
index, and extracts it into filesDir/varnam/<lang>/.
"""

import argparse
import hashlib
import json
import shutil
import sqlite3
import tempfile
import zipfile
from pathlib import Path

# Display names keyed by ISO code; pack.json only carries "<Name> Basic".
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


def migrate_vst(src: Path, dst: Path) -> None:
    """Copy a VST to dst, upgrading the old libvarnam schema for govarnam 1.9+.

    The libvarnam-era VSTs predate govarnam's `weight` column on the `symbols` table;
    without it govarnam errors ("no such column: weight") and returns the input
    untransliterated. Adding the column (idempotent) restores transliteration.
    """
    shutil.copy2(src, dst)
    conn = sqlite3.connect(dst)
    try:
        cols = [r[1] for r in conn.execute("PRAGMA table_info(symbols)")]
        if "weight" not in cols:
            conn.execute("ALTER TABLE symbols ADD COLUMN weight INTEGER")
            conn.commit()
    finally:
        conn.close()


def collect_files(lang_dir: Path, lang: str):
    """Return (vst_path, [vlf_paths], pack_json_dict) for a language directory."""
    vst = lang_dir / f"{lang}.vst"
    if not vst.exists():
        raise FileNotFoundError(f"missing scheme table: {vst}")

    pack_dir = lang_dir / f"{lang}-basic"
    pack_json = json.load(open(pack_dir / "pack.json"))
    vlfs = sorted(pack_dir.glob(f"{lang}-basic-*.vlf"))
    return vst, vlfs, pack_json


def build_language(lang: str, lang_dir: Path, out_dir: Path, version: int) -> dict:
    vst, vlfs, pack_json = collect_files(lang_dir, lang)

    zip_name = f"{lang}.zip"
    zip_path = out_dir / zip_name
    # Flat archive (arcname = bare filename) so the keyboard extracts straight
    # into filesDir/varnam/<lang>/ without nested directories.
    with tempfile.TemporaryDirectory() as tmp:
        migrated_vst = Path(tmp) / vst.name
        migrate_vst(vst, migrated_vst)
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.write(migrated_vst, arcname=vst.name)
            for vlf in vlfs:
                zf.write(vlf, arcname=vlf.name)

    return {
        "id": lang,
        "lang": lang,
        "name": LANG_NAMES.get(lang, lang),
        "description": pack_json.get("description", ""),
        "file": zip_name,
        "size": zip_path.stat().st_size,
        "sha256": sha256_of(zip_path),
        "version": version,
        "contents": {
            "vst": vst.name,
            "vlf": [v.name for v in vlfs],
        },
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--languages-dir", default="varnam",
        help="path to the languages submodule (default: languages)")
    parser.add_argument(
        "--out", default="dist",
        help="output directory for tarballs + index.json (default: dist)")
    parser.add_argument(
        "--base-url", default="",
        help="base URL prepended to each tarball's `url` field "
             "(e.g. https://github.com/<org>/<repo>/releases/download/<tag>)")
    parser.add_argument(
        "--version", type=int, default=1,
        help="data version stamped on every scheme (drives update detection)")
    parser.add_argument(
        "--langs", nargs="*",
        help="subset of language codes to build (default: all found)")
    args = parser.parse_args()

    languages_dir = Path(args.languages_dir)
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    langs = args.langs or sorted(
        p.name for p in languages_dir.iterdir()
        if p.is_dir() and (p / f"{p.name}.vst").exists())

    schemes = []
    for lang in langs:
        scheme = build_language(lang, languages_dir / lang, out_dir, args.version)
        if args.base_url:
            scheme["url"] = f"{args.base_url.rstrip('/')}/{scheme['file']}"
        schemes.append(scheme)
        print(f"packaged {lang}: {scheme['size']:,} bytes  sha256={scheme['sha256'][:12]}…")

    index = {"version": args.version, "schemes": schemes}
    with open(out_dir / "index.json", "w") as f:
        json.dump(index, f, indent=2, ensure_ascii=False)
    print(f"wrote {out_dir / 'index.json'} ({len(schemes)} schemes)")


if __name__ == "__main__":
    main()
