# Shitsuke Toolz

> VIP Toolkit For Devs (beta) — a universal developer toolkit for **Mobile Legends: Bang Bang** (`com.mobile.legends`, Unity/IL2CPP, asset root `dragon2017`).

One Python file. No install, no network, no mandatory packages. Built for reverse engineers and modders who want to inspect files, debug XML, and repack MLBB config bundles.

---

## 1. Install (once)

**Termux (Android):**

```bash
pkg update -y && pkg install -y python git
```

**Linux / macOS / WSL:** install Python 3.9+. **AndCode / UserLAnd:** Python is already there; just use `python3`.

Check it works:

```bash
python shitsuke_toolz.py --selftest
```

Expected: `selftest: 23 passed, 0 failed` and exit code `0`.

---

## 2. Put the tool in Download

Copy `shitsuke_toolz.py` into your shared **Download** folder, e.g. `/sdcard/Download` (Termux calls it `~/storage/downloads`). Use any file manager, `cp`, or `adb push`.

---

## 3. Run it

```bash
cd storage/download
python shitsuke_toolz.py
```

On Linux/AndCode use `python3` instead of `python`. The menu opens full-screen. If you do not have a terminal window, run `python shitsuke_toolz.py --help` to see the CLI.

**Menu keys:** `↑/↓` or `j/k` move, `Enter` opens, number keys jump, `q`/`Esc` goes back, `q` on the main menu quits. Quitting restores your terminal exactly as it was.

---

## 4. Common workflows

### Unpack the config XML

1. Main menu → **MLBB Repack** → **Unpack XML**.
2. Container: `/storage/emulated/0/mlbb/encode/Documents.unity3d` (already filled in — press Enter).
3. Decode directory: `/storage/emulated/0/mlbb/decode` (already filled in — press Enter).
4. The two config files appear in the decode folder: `BattleSystemConfig.xml` and `SystemConfig.xml`.

Choose **Decode every XML resource?** = yes if you need all XML files instead of just those two.

### Edit and smart repack

1. Edit the XML files in `/storage/emulated/0/mlbb/decode` with any text editor.
2. Main menu → **MLBB Repack** → **Smart repack**.
3. Press Enter to accept the container, decode folder, and output (`/storage/emulated/0/mlbb/encode/Document.unity3d`).
4. Enter a ZIP name if you want a flashable package, or leave it blank.
5. The tool re-applies the original base64/gzip/zlib encoding, rebuilds the container, and writes the output. Answer yes to "Delete decoded XML afterwards?" if you want the decode folder cleaned up.

Use **Raw encode** instead when the original resource was plain XML and you do not want any encoding re-applied.

### Verify a clean round-trip

Main menu → **MLBB Repack** → **Lossless test**. It rebuilds the container without edits and tells you `BYTE-IDENTICAL` or the first differing offset.

### Debug a file

Main menu → **Debugging**:

- **Hex reader** — read-only offset/hex/ASCII dump of any file.
- **Search code** — find a snippet in well-formed XML; whitespace is ignored and malformed files are skipped.
- **Modify XML** — replace an exact snippet in all valid XML files; the replacement is validated before anything is written.
- **Search file** — find files by name glob, by text, or both.
- **Binary diff** — offset-level diff with context; can write a JSON patch map.
- **Entropy map** — find compressed or encrypted regions.
- **Carve signatures** — locate PNG/ZIP/GZIP/ELF/XML signatures inside a blob.
- **XML check** — validate and lint every XML in a folder before repacking.

Other menus cover ELF/metadata/AOB recon (`Recon & Binary`), UnityFS/assets (`Unity & Assets`), XML/JSON/templates (`Data Tools`), and ADB/Shizuku (`Device`).

---

## Debugging & MLBB repack (what was added)

**MLBB container tools** — parse and rebuild `MLBB` containers, smart encode (preserves base64/gzip/zlib), raw encode, unpack XML, lossless rebuild test, and flashable ZIP output.

**XML debugging** — read-only hex reader, whitespace-insensitive code search, validated exact-snippet modification, and file/name search.

**Four extra developer tools** — binary diff with patch map, Shannon entropy map, signature carver, and batch XML lint/validator.

The mod-menu scaffold was removed; this build focuses on debugging and repacking.

---

## CLI (optional)

Everything in the menu is also a command:

```bash
python shitsuke_toolz.py mlbb unpack --all
python shitsuke_toolz.py mlbb repack --zip Document_patched
python shitsuke_toolz.py mlbb lossless
python shitsuke_toolz.py hexdump Documents.unity3d --limit 4096
python shitsuke_toolz.py xmlsearch decode --query '<root><value>1</value></root>'
python shitsuke_toolz.py xmlmodify decode --old '>1<' --new '>2<' --apply
python shitsuke_toolz.py searchfile /sdcard/mlbb --name '*.xml' --text cooldown
python shitsuke_toolz.py debug bindiff original.bin patched.bin --patch patch.json
python shitsuke_toolz.py debug entropy Document.unity3d
python shitsuke_toolz.py debug carve blob.bin --dest carved/
python shitsuke_toolz.py debug xmlcheck decode
```

Full command list:

```text
banner tui recon elf metadata scan strings assets unityfs skin alias resmap
xml json gen adb shizuku map mlbb debug hexdump xmlsearch xmlmodify searchfile selftest
```

Global flags: `--verbose --json --out DIR --adb PATH --device SERIAL --no-color --dry-run --force --selftest`

---

## Troubleshooting

| Problem | Fix |
| --- | --- |
| `python: command not found` | Termux: `pkg install python`. Linux/AndCode: use `python3`. |
| Cannot read `Android/data` | Android 11+ blocks it — use `adb pull`, root, or copy files to `~/storage/shared/Download`. |
| Self-test fails | Use Python 3.9+ and run from the folder containing the script. |
| `output exists` | Pass `--force`, or answer yes to "Overwrite existing output?" in the menu. |
| LZ4 is slow | Optional: `pip install lz4`; a pure-Python fallback is built in. |

---

## Requirements

- Python 3.9+
- Optional: `lz4`, `frida` (both fall back cleanly)
- Device features: `adb` in PATH or `--adb PATH`

## License

MIT — do whatever, no warranty.
