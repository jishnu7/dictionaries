Dictionaries
============

Per-language word data for Indic Keyboard. From one curated word-frequency list per language,
the pipeline produces **both** of the keyboard's dictionary formats:

* `main_<code>.dict` — the LatinIME binary dictionary used by the non-transliteration layouts.
* `<code>.vst` + `<code>-*.vlf` — the govarnam scheme + learnings packs used by the Varnam
  transliteration layouts

Both are published as a per-language `<code>.zip` plus an `index.json` manifest on GitHub
Releases, which the keyboard downloads on demand.

Layout
------
```
languages/<code>/
  meta.json         # name, wiki code, has_varnam, script ranges, min_freq, max_words, packs
  wordfreq.txt      # canonical, curated "word count" list (the single source of truth)
  scheme/<code>.vst # varnam languages only — fetched from varnamproject/schemes, not committed
build.py            # per-stage build orchestrator
Makefile            # per-language entry points (see `make help`)
tools/              # dwn.sh (dump), extract.py (parser), dicttool_aosp.jar
```

Building
--------
```
make varnamcli                 # download the govarnam CLI (once)
make schemes                   # fetch varnam .vst files from varnamproject/schemes (once)
make download LANG=ml          # fetch the Wikipedia dump
make extract  LANG=ml          # dump -> languages/ml/wordfreq.candidate.txt (review, then commit)
make lang     LANG=ml          # wordfreq.txt -> combined -> dict -> varnam -> dist/ml.zip
make all                       # build every language + dist/index.json
```
Scheme tables (`.vst`) and the govarnam CLI are upstream artifacts fetched on demand (pinned via
`SCHEMES_TAG` / `GOVARNAM_VER`).
The Wikipedia crawl: `extract.py` writes `wordfreq.candidate.txt`, to diff against the committed
`wordfreq.txt` and merge by hand.
Words are script-limited to the language's Unicode `ranges`, pruned below `min_freq`, and
single-grapheme fragments (a lone chillu, a dead consonant, a consonant+matra) are dropped — the
same cleaning is re-applied at build time to whatever feeds the `.combined`/`.vlf`.

Languages
--------
Dictionary (all): Assamese, Bengali, Gujarati, Hindi, Kannada, Konkani, Kashmiri, Maithili,
Malayalam, Marathi, Nepali, Odia, Punjabi, Sanskrit, Santali, Sindhi, Tamil, Telugu, Tulu, Urdu.

Varnam (`.vst` + `.vlf`): Assamese, Bengali, Gujarati, Hindi, Kannada, Malayalam, Marathi,
Nepali, Odia, Punjabi, Sanskrit, Tamil, Telugu.

License
--------
GPLv2
