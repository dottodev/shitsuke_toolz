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
- **Self-Test** — `--selftest` exercises every subsystem against synthetic fixtures.

## Setup Guide

The toolkit is a single Python file with no mandatory third-party packages. Pick the setup for your device; every path below ends with the same self-test.

### Android — Termux (recommended)

1. Install **Termux** from [F-Droid](https://f-droid.org/packages/com.termux/) or the [GitHub releases](https://github.com/termux/termux-app/releases). Do not use the Play Store build — it is outdated.
2. Open Termux and run:

```bash
pkg update -y && pkg upgrade -y
pkg install -y python git
git clone https://github.com/dottodev/shitsuke_toolz.git
cd shitsuke_toolz
python shitsuke_toolz.py --selftest
```

Expected result: `selftest: 21 passed, 0 failed` and exit code `0`.

3. Give Termux access to shared storage, then point the tool at the game files:

```bash
termux-setup-storage
FILES=~/storage/shared/Android/data/com.mobile.legends/files
python shitsuke_toolz.py recon "$FILES"
python shitsuke_toolz.py assets --root "$FILES" --out ./out
```

4. Optional extras (the tool works without them):

```bash
pkg install -y nodejs    # enables node --check for generated JavaScript
pip install lz4          # faster LZ4; a pure-Python fallback is built in
```

**Android 11+ note:** `/sdcard/Android/data` is blocked for most apps, even with storage permission. Pull the files with ADB instead:

```bash
pkg install -y android-tools
adb devices
adb pull /sdcard/Android/data/com.mobile.legends/files ./mlbb-files
python shitsuke_toolz.py recon ./mlbb-files
```

On a rooted device you can copy the directory with `su -c` instead. File analysis needs no root; only live device paths need ADB or root.

### Android — AndCode

Open this repository in **AndCode**, then use its built-in terminal:

```bash
cd /workspace/NewZ   # or your imported repo folder
python3 shitsuke_toolz.py --selftest
```

AndCode already provides the Python runtime, so no `pkg`/`apt` step is needed. Outputs written under the workspace are visible in the app's file browser.

### Android — UserLAnd

1. Install **UserLAnd** and create an Ubuntu session.
2. Inside Ubuntu:

```bash
sudo apt update && sudo apt install -y python3 git
git clone https://github.com/dottodev/shitsuke_toolz.git
cd shitsuke_toolz
python3 shitsuke_toolz.py --selftest
```

Use `adb pull` (from a host or Termux) to copy game files into UserLAnd's home directory; UserLAnd may not see `/sdcard/Android/data` directly.

### Other apps and platforms

- **ZeroTermux / Termux forks** — identical to the Termux steps above.
- **MT Manager / ZArchiver** — use these to extract APKs/OBBs and browse `dragon2017`; run the toolkit from Termux or AndCode.
- **Linux / macOS** — `git clone`, then `python3 shitsuke_toolz.py --selftest`. Install `lz4` with your package manager for faster decompression.
- **Windows** — use WSL and follow the Linux steps, or run `py shitsuke_toolz.py --selftest` in a native Python 3.9+ install.
- **iSH (iOS)** — install `python3` and `git` with `apk add`, then run the same commands. It works but is slow on large bundles.

### Troubleshooting

| Symptom | Fix |
| --- | --- |
| `python: command not found` | Termux: `pkg install python`, then use `python`. Linux/AndCode: use `python3`. |
| `Permission denied` reading `Android/data` | Android 11+ restriction — use `adb pull`, root, or copy files to `~/storage/shared/Download`. |
| Self-test fails | Check `python3 --version` is 3.9+, and run the script from the repository root. |
| `adb not found` | `pkg install android-tools`, or pass `--adb /path/to/adb`. |
| `node unavailable, syntax check limited` | Optional: `pkg install nodejs`. Templates still validate with the built-in delimiter checks. |
| LZ4 decompression is slow | Optional: `pip install lz4`; without it the pure-Python fallback is used. |
| `No module named lz4` / `frida` | Both are optional and handled automatically. |

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
