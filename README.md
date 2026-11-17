# Shitsuke Toolz

![Python](https://img.shields.io/badge/python-3.9%2B-blue?logo=python&logoColor=white)
![License](https://img.shields.io/badge/license-MIT-green)
![Platform](https://img.shields.io/badge/platform-Android%20%7C%20Linux-orange?logo=linux)
![Status](https://img.shields.io/badge/status-beta-yellow)
![Tests](https://img.shields.io/badge/selftest-passing-brightgreen)

> VIP Toolkit For Devs (beta) — a universal developer toolkit for **Mobile Legends: Bang Bang** (`com.mobile.legends`, Unity/IL2CPP, asset root `dragon2017`).

Built for modders, exploit devs, and reverse engineers. One file. No placeholders. No network. Pure stdlib with optional deps wrapped in fallbacks.

---

## Features

- **Binary Recon** — ELF parser (32/64-bit), target resolver, `global-metadata.dat` header parser with 8-rung recovery ladder, AOB scanner, strings/symbols extractor.
- **UnityFS & Assets** — UnityFS header/blocks/nodes, LZMA & LZ4 decompression (pure-Python fallback), SerializedFile parser, asset indexer, mini_patch shadowing detection.
- **Skin Engine** — skin swap planner with backup manifests + `restore.py`, alias injection, GameResAlternative rewriter, cache integrity checks.
- **Templates** — GameGuardian Lua, Frida JS, C++ stubs, Python stubs, each validated before write.
- **Device** — ADB wrapper, Shizuku probe, env/path resolver, wireless ADB helper.
- **Mod Menu Scaffold** — full LGLTeam-style Android mod menu source tree emitter with manifest.
- **Surface Map** — keyword-driven CSV/JSON mapping across strings, symbols, metadata, assets.
- **Self-Test** — `--selftest` runs every subcommand against synthetic fixtures.

## Quick Start

```bash
python shitsuke_toolz.py --selftest
python shitsuke_toolz.py banner
python shitsuke_toolz.py elf libil2cpp.so
python shitsuke_toolz.py metadata global-metadata.dat --recover
python shitsuke_toolz.py scan file.bin --pattern "48 8B ?? 90"
```

## CLI

```text
shitsuke_toolz.py {banner,recon,elf,metadata,scan,strings,assets,unityfs,skin,alias,resmap,xml,json,gen,adb,shizuku,menu,map,selftest}
```

Global flags: `--verbose --json --out DIR --adb PATH --device SERIAL --no-color --dry-run --force --selftest`

## Requirements

- Python 3.9+
- Optional: `lz4`, `frida` (wrapped in try/except with fallbacks)
- For device features: `adb` in PATH or `--adb PATH`

## License

MIT — do whatever, no warranty.
