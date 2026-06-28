#!/usr/bin/env bash
# Download the latest Wikipedia article dump for a wiki code into dumps/.
# Usage: dwn.sh <wiki-code>   e.g. dwn.sh ml
set -e

if [ $# -lt 1 ]; then
  echo "Usage: $0 <wiki-code>"
  exit 1
fi

wiki="$1"
mkdir -p dumps
url="https://dumps.wikimedia.org/${wiki}wiki/latest/${wiki}wiki-latest-pages-articles.xml.bz2"
echo "Downloading $url"
curl -L --fail -o "dumps/${wiki}wiki-latest-pages-articles.xml.bz2" "$url"
