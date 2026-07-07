// Copyright 2026, Jishnu Mohan <jishnu7@gmail.com>
//
// Licensed under the Apache License, Version 2.0 (the "License").
// See LICENSE / http://www.apache.org/licenses/LICENSE-2.0

// Reverse-transliterate a word list: for each Indic word on stdin, print
// "word<TAB>romanization" on stdout (words with no reverse result are skipped).
// The romanizations feed the Latin gesture dictionary for transliteration layouts.
//
// Usage: VARNAM_VST_DIR=<dir with <scheme>.vst> reverse-translit <schemeID>
package main

import (
	"bufio"
	"fmt"
	"os"

	"github.com/varnamproject/govarnam/govarnam"
)

func main() {
	if len(os.Args) != 2 {
		fmt.Fprintln(os.Stderr, "usage: reverse-translit <schemeID> (reads words from stdin)")
		os.Exit(2)
	}
	v, err := govarnam.InitFromID(os.Args[1])
	if err != nil {
		fmt.Fprintln(os.Stderr, "init failed:", err)
		os.Exit(1)
	}
	in := bufio.NewScanner(os.Stdin)
	in.Buffer(make([]byte, 1<<20), 1<<20)
	out := bufio.NewWriter(os.Stdout)
	defer out.Flush()
	for in.Scan() {
		word := in.Text()
		if word == "" {
			continue
		}
		sugs, err := v.ReverseTransliterate(word)
		if err != nil || len(sugs) == 0 {
			continue
		}
		fmt.Fprintf(out, "%s\t%s\n", word, sugs[0].Word)
	}
}
