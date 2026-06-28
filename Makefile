# Copyright 2026, Jishnu Mohan <jishnu7@gmail.com>
#
# Licensed under the Apache License, Version 2.0 (the "License").
# See LICENSE / http://www.apache.org/licenses/LICENSE-2.0
#
# Per-language data pipeline. Most targets take LANG=<code>:
#
#   make varnamcli                 # download the govarnam CLI (once)
#   make download LANG=ml          # fetch the Wikipedia dump
#   make extract  LANG=ml          # dump -> languages/ml/wordfreq.candidate.txt (review, then commit)
#   make lang     LANG=ml          # wordfreq.txt -> combined -> dict -> varnam -> dist/ml.zip
#   make all                       # build every language + dist/index.json
#
# make dicttool rebuilds the committed tools/dicttool_aosp.jar from the keyboard repo (rare).

VERSION           ?= 1
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

.PHONY: help varnamcli dicttool scheme schemes download extract combined dict varnam pack lang index all check-lang prep-varnam

help:
	@grep -E '^[a-zA-Z_-]+:.*?#' $(MAKEFILE_LIST) | sed 's/:.*#/\t/'

check-lang:
	@test -n "$(LANG)" || { echo "set LANG=<code> (e.g. make $(MAKECMDGOALS) LANG=ml)"; exit 1; }

# ---- toolchain ----

varnamcli: ## get the govarnam CLI into tools/varnam/ (download on Linux x86_64; else build from the keyboard's govarnam submodule)
	@mkdir -p $(VARNAM_DIR)
	@if [ "$$(uname -s)" = "Linux" ] && [ "$$(uname -m)" = "x86_64" ]; then \
	  echo "Downloading govarnam $(GOVARNAM_VER) (linux x86_64)"; \
	  curl -L --fail -o /tmp/govarnam.zip https://github.com/varnamproject/govarnam/releases/download/$(GOVARNAM_VER)/govarnam-$(patsubst v%,%,$(GOVARNAM_VER))-x86_64.zip; \
	  cd $(VARNAM_DIR) && unzip -joq /tmp/govarnam.zip '*/varnamcli' '*/libgovarnam.so*' && rm -f /tmp/govarnam.zip; \
	else \
	  test -d "$(GOVARNAM_SRC)" || { echo "no govarnam source at $(GOVARNAM_SRC) (set INDIC_KEYBOARD_DIR)"; exit 1; }; \
	  command -v go >/dev/null || { echo "the go toolchain is required to build varnamcli on $$(uname -s)"; exit 1; }; \
	  echo "Building varnamcli from $(GOVARNAM_SRC) (no prebuilt binary for this platform)"; \
	  $(MAKE) -C "$(GOVARNAM_SRC)" library >/dev/null; \
	  printf '#!/bin/sh\nfor a in "$$@"; do case "$$a" in --cflags) echo "-I%s";; --libs) echo "-L%s -lgovarnam";; esac; done\n' "$(GOVARNAM_SRC)" "$(GOVARNAM_SRC)" > $(VARNAM_DIR)/pkg-config-shim; \
	  chmod +x $(VARNAM_DIR)/pkg-config-shim; \
	  ( cd "$(GOVARNAM_SRC)" && PKG_CONFIG="$(VARNAM_DIR)/pkg-config-shim" go build -o "$(VARNAM_DIR)/varnamcli" ./cli ); \
	  cp "$(GOVARNAM_SRC)"/libgovarnam.dylib "$(VARNAM_DIR)/" 2>/dev/null || cp "$(GOVARNAM_SRC)"/libgovarnam.so* "$(VARNAM_DIR)/"; \
	fi
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
	  test -x "$(VARNAM_DIR)/varnamcli" || { echo "varnamcli missing — run 'make varnamcli' first"; exit 1; }; \
	  [ -f "languages/$(LANG)/scheme/$$sid.vst" ] || $(MAKE) --no-print-directory scheme LANG=$(LANG); \
	fi

# ---- per-language stages ----

download: check-lang ## fetch the Wikipedia dump for LANG
	tools/dwn.sh $(wiki)

extract: check-lang ## dump -> languages/$(LANG)/wordfreq.candidate.txt
	$(PY) tools/extract.py $(LANG)

combined: prep-varnam ## build/$(LANG)/$(LANG).combined (varnam langs: from the sanitized .vlf)
	$(VARNAM_ENV) $(PY) build.py --version $(VERSION) combined $(LANG)

dict: prep-varnam ## .combined -> build/$(LANG)/main_$(LANG).dict
	$(VARNAM_ENV) $(PY) build.py --version $(VERSION) dict $(LANG)

varnam: prep-varnam ## learn/export govarnam packs for LANG (needs `make varnamcli`)
	$(VARNAM_ENV) $(PY) build.py varnam $(LANG)

pack: check-lang ## zip LANG's artifacts into dist/$(LANG).zip
	$(PY) build.py --version $(VERSION) --base-url "$(BASE_URL)" pack $(LANG)

lang: prep-varnam ## full chain for one LANG
	$(VARNAM_ENV) $(PY) build.py --version $(VERSION) --base-url "$(BASE_URL)" lang $(LANG)

index: ## aggregate dist/index.json from the per-language sidecars
	$(PY) build.py --version $(VERSION) index

all: ## build every language + index.json (LANGS="ml hi" for a subset; run `make varnamcli schemes` first)
	$(VARNAM_ENV) $(PY) build.py --version $(VERSION) --base-url "$(BASE_URL)" all $(if $(LANGS),--langs $(LANGS))
