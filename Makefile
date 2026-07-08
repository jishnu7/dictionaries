# Copyright 2026, Jishnu Mohan <jishnu7@gmail.com>
#
# Licensed under the Apache License, Version 2.0 (the "License").
# See LICENSE / http://www.apache.org/licenses/LICENSE-2.0
#
# Per-language data pipeline. Most targets take LANG=<code>:
#
#   make varnamcli                 # build the govarnam CLI from source
#   make download LANG=ml          # fetch the Wikipedia dump
#   make extract  LANG=ml          # dump -> languages/ml/{wordfreq,bigramfreq}.candidate.txt (review, then commit)
#   make lang     LANG=ml          # wordfreq.txt -> combined -> dict -> varnam -> dist/ml.zip
#   make all                       # build every language + dist/index.json
#
# make dicttool rebuilds the committed tools/dicttool_aosp.jar from the keyboard repo (rare).

BASE_URL          ?=
GOVARNAM_VER      ?= v1.9.1
SCHEMES_TAG       ?= v1.8.0
INDIC_KEYBOARD_DIR ?= ..
VARNAM_DIR        := $(CURDIR)/tools/varnam
GOVARNAM_SRC      := $(abspath $(INDIC_KEYBOARD_DIR))/native/govarnam/govarnam
# Make varnamcli + libgovarnam discoverable on both Linux (LD) and macOS (DYLD).
VARNAM_ENV        := PATH="$(VARNAM_DIR):$$PATH" LD_LIBRARY_PATH="$(VARNAM_DIR):$$LD_LIBRARY_PATH" DYLD_LIBRARY_PATH="$(VARNAM_DIR):$$DYLD_LIBRARY_PATH"

PY  := python3
LANG ?=
wiki = $(shell $(PY) -c "import json;print(json.load(open('languages/$(LANG)/meta.json'))['wiki'])")

.PHONY: help govarnam-src varnamcli dicttool reverse-translit scheme schemes download extract combined dict xlit varnam pack lang index stats all check-lang prep-varnam prep-all

help:
	@grep -E '^[a-zA-Z_-]+:.*?#' $(MAKEFILE_LIST) | sed 's/:.*#/\t/'

check-lang:
	@test -n "$(LANG)" || { echo "set LANG=<code> (e.g. make $(MAKECMDGOALS) LANG=ml)"; exit 1; }

# ---- toolchain ----

govarnam-src:  # ensure govarnam source exists (keyboard checkout, or clone at GOVARNAM_VER)
	@test -d "$(GOVARNAM_SRC)" || { \
	  echo "no keyboard checkout at $(GOVARNAM_SRC); cloning govarnam $(GOVARNAM_VER)"; \
	  git clone --depth 1 --branch $(GOVARNAM_VER) https://github.com/varnamproject/govarnam "$(GOVARNAM_SRC)"; \
	}

$(VARNAM_DIR)/varnamcli: | govarnam-src
	@command -v go >/dev/null || { echo "the go toolchain is required to build varnamcli"; exit 1; }
	@mkdir -p $(VARNAM_DIR)
	$(MAKE) -C "$(GOVARNAM_SRC)" library >/dev/null
	@printf '#!/bin/sh\nfor a in "$$@"; do case "$$a" in --cflags) echo "-I%s";; --libs) echo "-L%s -lgovarnam";; esac; done\n' "$(GOVARNAM_SRC)" "$(GOVARNAM_SRC)" > $(VARNAM_DIR)/pkg-config-shim
	@chmod +x $(VARNAM_DIR)/pkg-config-shim
	cd "$(GOVARNAM_SRC)" && PKG_CONFIG="$(VARNAM_DIR)/pkg-config-shim" go build -o "$(VARNAM_DIR)/varnamcli" ./cli
	@cp "$(GOVARNAM_SRC)"/libgovarnam.dylib "$(VARNAM_DIR)/" 2>/dev/null || cp "$(GOVARNAM_SRC)"/libgovarnam.so* "$(VARNAM_DIR)/"

varnamcli: $(VARNAM_DIR)/varnamcli ## build the govarnam CLI + libgovarnam into tools/varnam/ (skipped if already built; delete to rebuild)
	@echo "varnamcli ready in $(VARNAM_DIR)"

dicttool: ## rebuild tools/dicttool_aosp.jar from the Indic Keyboard repo (maintenance)
	$(MAKE) -C $(INDIC_KEYBOARD_DIR) dicttool
	cp $(INDIC_KEYBOARD_DIR)/tools/dicttool/build/dicttool.jar tools/dicttool_aosp.jar
	@echo "Refreshed tools/dicttool_aosp.jar"

scheme: check-lang ## fetch LANG's .vst from varnamproject/schemes (into the gitignored scheme/)
	@sid=$$($(PY) -c "import json;print(json.load(open('languages/$(LANG)/meta.json')).get('scheme_id',''))"); \
	test -n "$$sid" || { echo "$(LANG) is not a varnam language"; exit 1; }; \
	mkdir -p languages/$(LANG)/scheme; \
	curl -L --fail -o /tmp/$$sid-scheme.zip \
	  https://github.com/varnamproject/schemes/releases/download/$(SCHEMES_TAG)/$$sid.zip; \
	cd languages/$(LANG)/scheme && unzip -joq /tmp/$$sid-scheme.zip "*$$sid.vst" && rm -f /tmp/$$sid-scheme.zip; \
	echo "fetched $$sid.vst @ $(SCHEMES_TAG)"

schemes: ## fetch every varnam language's .vst from varnamproject/schemes
	@for l in $$($(PY) build.py langs --varnam); do $(MAKE) --no-print-directory scheme LANG=$$l; done

prep-varnam: check-lang  # for a varnam LANG: ensure varnamcli is built and the .vst is fetched
	@sid=$$($(PY) -c "import json;m=json.load(open('languages/$(LANG)/meta.json'));print(m.get('scheme_id','') if m.get('has_varnam') else '')"); \
	if [ -n "$$sid" ]; then \
	  $(MAKE) --no-print-directory varnamcli reverse-translit; \
	  [ -f "languages/$(LANG)/scheme/$$sid.vst" ] || $(MAKE) --no-print-directory scheme LANG=$(LANG); \
	fi

# ---- per-language stages ----

download: check-lang ## fetch the Wikipedia dump for LANG
	tools/dwn.sh $(wiki)

extract: check-lang ## dump -> languages/$(LANG)/{wordfreq,bigramfreq}.candidate.txt
	$(PY) tools/extract.py $(LANG)

combined: prep-varnam ## build/$(LANG)/$(LANG).combined (varnam langs: from the sanitized .vlf)
	$(VARNAM_ENV) $(PY) build.py combined $(LANG)

dict: prep-varnam ## .combined -> build/$(LANG)/main_$(LANG).dict
	$(VARNAM_ENV) $(PY) build.py dict $(LANG)

varnam: prep-varnam ## learn/export govarnam packs for LANG
	$(VARNAM_ENV) $(PY) build.py varnam $(LANG)

pack: check-lang ## zip LANG's artifacts into dist/$(LANG).zip
	$(PY) build.py --base-url "$(BASE_URL)" pack $(LANG)

lang: prep-varnam ## full chain for one LANG
	$(VARNAM_ENV) $(PY) build.py --base-url "$(BASE_URL)" lang $(LANG)

index: ## aggregate dist/index.json from the per-language sidecars
	$(PY) build.py index

stats: ## per-language word/bigram/xlit counts and sizes of the built packs (from dist/)
	$(PY) build.py stats

tools/reverse-translit/reverse-translit: | govarnam-src
	@command -v go >/dev/null || { echo "the go toolchain is required to build reverse-translit"; exit 1; }
	cd tools/reverse-translit && CGO_ENABLED=1 go build -tags "fts5" -o reverse-translit .

reverse-translit: tools/reverse-translit/reverse-translit ## build tools/reverse-translit (romanizer for the xlit gesture dictionaries; skipped if already built)
	@echo "reverse-translit ready"

prep-all:  # ensure varnamcli + reverse-translit exist and every varnam language's .vst is fetched (missing ones only)
	@$(MAKE) --no-print-directory varnamcli reverse-translit
	@for l in $$($(PY) build.py langs --varnam); do \
	  sid=$$($(PY) -c "import json;print(json.load(open('languages/$$l/meta.json')).get('scheme_id','$$l'))"); \
	  [ -f "languages/$$l/scheme/$$sid.vst" ] || $(MAKE) --no-print-directory scheme LANG=$$l; \
	done

all: prep-all ## build every language + index.json (LANGS="ml hi" for a subset)
	$(VARNAM_ENV) $(PY) build.py --base-url "$(BASE_URL)" all $(if $(LANGS),--langs $(LANGS))
