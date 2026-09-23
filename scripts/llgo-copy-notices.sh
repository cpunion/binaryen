#!/usr/bin/env bash
set -euo pipefail

dest="$1"
cp LICENSE LLGO.md "$dest/"
mkdir -p "$dest/third_party/FP16" "$dest/third_party/llvm-project/include/llvm" "$dest/third_party/googletest"
cp third_party/FP16/LICENSE "$dest/third_party/FP16/"
cp third_party/llvm-project/include/llvm/LICENSE.TXT "$dest/third_party/llvm-project/include/llvm/"
cp third_party/googletest/LICENSE "$dest/third_party/googletest/"
