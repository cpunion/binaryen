# LLGo Binaryen distribution

This fork provides the Binaryen build used by [LLGo](https://github.com/xgo-dev/llgo).

- `main` mirrors `WebAssembly/binaryen:main` without LLGo changes. The `Sync upstream main` workflow fast-forwards it; it never merges upstream changes into the release branch.
- `llgo` is the default and release branch. Its base is upstream `version_132` (`79dfe6b412a3c22bfdb190ed6a4d79adf734db5d`), matching Emscripten 6.0.8's expected Binaryen version.
- The LLGo patch backports [Binaryen PR #8964](https://github.com/WebAssembly/binaryen/pull/8964) to repair DWARF scope ranges after optimization and Asyncify. Backport-only test fixture changes are kept on this branch.
- Tags named `llgo-v132.N` are created at the `llgo` tip. The release workflow verifies that source commit, builds the Binaryen tool suite, runs tests, and publishes the archives and checksums after all release jobs pass.

Browser builds must set `EM_BINARYEN_ROOT` to the extracted release root so Emscripten uses this fork's `wasm-emscripten-finalize` and `wasm-opt`. LLGo's standalone WASI post-link path sets `WASMOPT` to the same release's `bin/wasm-opt`. Setting only `WASMOPT` does not replace Emscripten's Binaryen tools.

The source retains Binaryen's [Apache-2.0 license](LICENSE) and third-party notices. Every release identifies its upstream base and LLGo changes.
