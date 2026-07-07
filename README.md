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
  bigramfreq.txt    # optional "word1 word2 count" list -> next-word prediction bigrams
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
The Wikipedia crawl: `extract.py` writes `wordfreq.candidate.txt` and
`bigramfreq.candidate.txt`, to diff against the committed `wordfreq.txt` / `bigramfreq.txt` and
merge by hand.
Words are script-limited to the language's Unicode `ranges`, pruned below `min_freq`, and
single-grapheme fragments (a lone chillu, a dead consonant, a consonant+matra) are dropped — the
same cleaning is re-applied at build time to whatever feeds the `.combined`/`.vlf`.

Next-word prediction bigrams
--------
When `languages/<code>/bigramfreq.txt` exists, each dictionary word gets `bigram=` entries (its
most likely next words), which is what the keyboard's suggestion strip predicts after a word is
committed. The extractor counts only pairs separated by pure whitespace (markup, punctuation and
sentence boundaries break adjacency), pruned by `bigram_min_freq` (defaults to `min_freq`) and
capped at `max_bigrams` (default 200000). At build time each head word keeps its top
`bigrams_per_word` (default 5) successors whose targets survived word curation.

One selection rule needs explaining: the binary format stores a bigram's probability relative to
the *target* word's unigram weight, flooring it there — so an ultra-frequent successor listed
anywhere in a head's list would always outrank content successors in the strip. A successor with
unigram weight ≥ `bigram_unigram_cutoff` (default 240) is therefore kept only when it is the
head's #1 next word.

Languages
--------
Dictionary (all): Assamese, Bengali, Gujarati, Hindi, Kannada, Konkani, Kashmiri, Maithili,
Malayalam, Marathi, Nepali, Odia, Punjabi, Sanskrit, Santali, Sindhi, Tamil, Telugu, Tulu, Urdu.

Varnam (`.vst` + `.vlf`): Assamese, Bengali, Gujarati, Hindi, Kannada, Malayalam, Marathi,
Nepali, Odia, Punjabi, Sanskrit, Tamil, Telugu.

License
--------
GPLv2
