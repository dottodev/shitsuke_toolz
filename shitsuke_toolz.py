# -*- coding: utf-8 -*-
"""shitsuke_toolz — universal developer toolkit for Mobile Legends: Bang Bang.

Single-file, stdlib-first toolkit for Unity/IL2CPP binary recon, asset
inspection, skin/alias planning, device probing, template emission and
mod-menu scaffolding. No network access is performed by this tool.
"""

# 00 imports/consts
import argparse
import binascii
import csv
import hashlib
import io
import json
import lzma
import os
import re
import shutil
import signal
import struct
import subprocess
import sys
import tempfile
import time
import traceback
import xml.etree.ElementTree as ET
from pathlib import Path
from string import Template
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple, Union

TOOL_NAME = "shitsuke_toolz"
TOOL_VERSION = "2.0.0"
APP_PKG = "com.mobile.legends"
ASSET_ROOT = "dragon2017"

EXIT_OK = 0
EXIT_USAGE = 2
EXIT_IO = 3
EXIT_PARSE = 4
EXIT_SELFTEST = 5
EXIT_DEP = 6
EXIT_DEVICE = 7

BANNER_ART = r"""
███████╗ ██╗  ██╗ ██╗ ████████╗ ███████╗ ██╗   ██╗ ██╗  ██╗ ███████╗
██╔════╝ ██║  ██║ ██║ ╚══██╔══╝ ██╔════╝ ██║   ██║ ██║ ██╔╝ ██╔════╝
███████╗ ███████║ ██║    ██║    ███████╗ ██║   ██║ █████╔╝  █████╗
╚════██║ ██╔══██║ ██║    ██║    ╚════██║ ██║   ██║ ██╔═██╗  ██╔══╝
███████║ ██║  ██║ ██║    ██║    ███████║ ╚██████╔╝ ██║  ██╗ ███████╗
╚══════╝ ╚═╝  ╚═╝ ╚═╝    ╚═╝    ╚══════╝  ╚═════╝  ╚═╝  ╚═╝ ╚══════╝
"""
BANNER_LINE = "VIP Toolkit For Devs (beta)"

TARGET_LIBS = ("libil2cpp.so", "liblogic.so", "libmono.so", "libunity.so")
ABI_DIRS = ("arm64-v8a", "armeabi-v7a", "x86_64", "x86")

try:
    import lz4.block as lz4_block  # type: ignore
    HAS_LZ4 = True
except Exception:
    lz4_block = None
    HAS_LZ4 = False

try:
    import frida as frida_module  # type: ignore
    HAS_FRIDA = True
except Exception:
    frida_module = None
    HAS_FRIDA = False

COLOR = True
VERBOSE = False
JSON_MODE = False


# 01 exit codes/exceptions
class ShitsukeError(Exception):
    """Base error carrying a subsystem prefix and process exit code."""

    def __init__(self, subsystem: str, message: str, code: int = 1) -> None:
        super().__init__(message)
        self.subsystem = subsystem
        self.code = code


class UsageError(ShitsukeError):
    """Command-line usage error (exit 2)."""

    def __init__(self, subsystem: str, message: str) -> None:
        super().__init__(subsystem, message, EXIT_USAGE)


class ToolIOError(ShitsukeError):
    """Filesystem or subprocess I/O error (exit 3)."""

    def __init__(self, subsystem: str, message: str) -> None:
        super().__init__(subsystem, message, EXIT_IO)


class ParseError(ShitsukeError):
    """Malformed or unsupported input format (exit 4)."""

    def __init__(self, subsystem: str, message: str) -> None:
        super().__init__(subsystem, message, EXIT_PARSE)


class DepError(ShitsukeError):
    """Required optional dependency missing (exit 6)."""

    def __init__(self, subsystem: str, message: str) -> None:
        super().__init__(subsystem, message, EXIT_DEP)


class DeviceError(ShitsukeError):
    """ADB/device unavailable or failed (exit 7)."""

    def __init__(self, subsystem: str, message: str) -> None:
        super().__init__(subsystem, message, EXIT_DEVICE)


class CommandTimeout(TimeoutError):
    """Typed timeout raised by run(), retaining any captured process output."""

    def __init__(self, cmd: Sequence[str], timeout: int, stdout: bytes = b"", stderr: bytes = b"") -> None:
        super().__init__("command timed out after %ds: %s" % (timeout, " ".join(str(c) for c in cmd)))
        self.cmd = list(cmd)
        self.timeout = timeout
        self.stdout = stdout or b""
        self.stderr = stderr or b""


# 02 logging
def _paint(text: str, code: str) -> str:
    if not COLOR:
        return text
    return "\033[%sm%s\033[0m" % (code, text)


def err(subsystem: str, message: str) -> None:
    """Write a prefixed error line to stderr."""
    sys.stderr.write("%s [%s] %s\n" % (_paint("error", "31"), subsystem, message))
    sys.stderr.flush()


def info(subsystem: str, message: str) -> None:
    """Write a prefixed informational line to stdout."""
    sys.stdout.write("[%s] %s\n" % (subsystem, message))
    sys.stdout.flush()


def vlog(subsystem: str, message: str) -> None:
    """Emit a line only when global verbose mode is enabled."""
    if VERBOSE:
        info(subsystem, message)


def print_banner() -> None:
    """Print the product banner exactly once per CLI invocation."""
    sys.stdout.write(BANNER_ART)
    sys.stdout.write(BANNER_LINE + "\n")
    sys.stdout.flush()


def emit_json(obj: Any) -> None:
    """Serialize an object as UTF-8 JSON on stdout."""
    sys.stdout.write(json.dumps(obj, indent=2, ensure_ascii=False) + "\n")
    sys.stdout.flush()


# 03 atomic_write
def atomic_write(path: Union[str, Path], data: bytes) -> Path:
    """Atomically write bytes via a same-directory temp file, fsync and os.replace."""
    p = Path(path)
    parent = p.parent if str(p.parent) else Path(".")
    parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".shitsuke_", dir=str(parent))
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, str(p))
        try:
            dfd = os.open(str(parent), os.O_RDONLY)
            try:
                os.fsync(dfd)
            finally:
                os.close(dfd)
        except OSError:
            pass
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    return p


def write_json(path: Union[str, Path], obj: Any) -> Path:
    """Atomically write a pretty UTF-8 JSON document."""
    return atomic_write(path, (json.dumps(obj, indent=2, ensure_ascii=False) + "\n").encode("utf-8"))


# 04 subprocess run
def run(cmd: Sequence[str], timeout: int = 30, cwd: Optional[Union[str, Path]] = None,
        env: Optional[Mapping[str, str]] = None) -> subprocess.CompletedProcess:
    """Run argv without a shell, with separate stdout/stderr and a hard timeout.

    Raises CommandTimeout (a TimeoutError subclass) when the deadline expires,
    preserving partial output, and ToolIOError when the executable is absent.
    """
    argv = [str(c) for c in cmd]
    try:
        return subprocess.run(argv, timeout=timeout, capture_output=True, cwd=str(cwd) if cwd else None,
                              env=dict(env) if env is not None else None, shell=False, check=False)
    except subprocess.TimeoutExpired as exc:
        out = exc.stdout if isinstance(exc.stdout, bytes) else (exc.stdout.encode() if exc.stdout else b"")
        errb = exc.stderr if isinstance(exc.stderr, bytes) else (exc.stderr.encode() if exc.stderr else b"")
        raise CommandTimeout(argv, timeout, out, errb) from exc
    except FileNotFoundError as exc:
        raise ToolIOError("run", "executable not found: %s" % argv[0]) from exc
    except OSError as exc:
        raise ToolIOError("run", "%s: %s" % (argv[0], exc)) from exc


# 05 byte/hex helpers
def _need(data: bytes, off: int, size: int, subsystem: str = "bytes") -> None:
    if off < 0 or size < 0 or off + size > len(data):
        raise ParseError(subsystem, "truncated read at 0x%x (%d bytes)" % (off, size))


def read_u16_le(data: bytes, off: int) -> int:
    """Read a little-endian unsigned 16-bit integer with bounds checking."""
    _need(data, off, 2)
    return struct.unpack_from("<H", data, off)[0]


def read_u32_le(data: bytes, off: int) -> int:
    """Read a little-endian unsigned 32-bit integer with bounds checking."""
    _need(data, off, 4)
    return struct.unpack_from("<I", data, off)[0]


def read_u64_le(data: bytes, off: int) -> int:
    """Read a little-endian unsigned 64-bit integer with bounds checking."""
    _need(data, off, 8)
    return struct.unpack_from("<Q", data, off)[0]


def read_i32_le(data: bytes, off: int) -> int:
    """Read a little-endian signed 32-bit integer with bounds checking."""
    _need(data, off, 4)
    return struct.unpack_from("<i", data, off)[0]


def read_i64_le(data: bytes, off: int) -> int:
    """Read a little-endian signed 64-bit integer with bounds checking."""
    _need(data, off, 8)
    return struct.unpack_from("<q", data, off)[0]


def read_cstring(data: bytes, off: int, max_len: int = 4096) -> str:
    """Decode a NUL-terminated UTF-8 string, tolerating a missing terminator."""
    if off < 0 or off > len(data):
        raise ParseError("bytes", "cstring offset out of range: 0x%x" % off)
    end = data.find(b"\x00", off, min(len(data), off + max_len))
    if end < 0:
        end = min(len(data), off + max_len)
    return data[off:end].decode("utf-8", errors="replace")


def hexdump(data: bytes, off: int = 0, length: int = 256) -> str:
    """Return a classic offset/hex/ascii dump for the requested byte range."""
    start = max(0, off)
    chunk = data[start:start + max(0, length)]
    rows: List[str] = []
    for i in range(0, len(chunk), 16):
        row = chunk[i:i + 16]
        hx = " ".join("%02x" % b for b in row)
        asc = "".join(chr(b) if 32 <= b < 127 else "." for b in row)
        rows.append("%08x  %-47s  %s" % (start + i, hx, asc))
    return "\n".join(rows)


def pattern_to_bytes_mask(pattern: str) -> Tuple[bytes, bytes]:
    """Convert an AOB pattern such as '48 8B ?? 90' to (bytes, mask)."""
    compact = pattern.strip()
    if not compact:
        raise UsageError("aob", "empty pattern")
    tokens: List[str] = []
    if " " in compact or "\t" in compact:
        tokens = compact.split()
    else:
        if len(compact) % 2 != 0:
            raise UsageError("aob", "pattern nibble count must be even")
        tokens = [compact[i:i + 2] for i in range(0, len(compact), 2)]
    values = bytearray()
    masks = bytearray()
    for token in tokens:
        t = token.strip()
        if t in ("?", "??", "*"):
            values.append(0)
            masks.append(0)
            continue
        if len(t) == 1:
            t = "0" + t
        if len(t) != 2 or not re.fullmatch(r"[0-9a-fA-F]{2}", t):
            raise UsageError("aob", "invalid pattern token: %s" % token)
        values.append(int(t, 16))
        masks.append(1)
    if not any(masks):
        raise UsageError("aob", "pattern contains no fixed bytes")
    return bytes(values), bytes(masks)


def sha256_bytes(data: bytes) -> str:
    """Return the lowercase hexadecimal SHA-256 of a byte string."""
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Union[str, Path], chunk: int = 65536) -> str:
    """Return the lowercase hexadecimal SHA-256 of a file."""
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        while True:
            block = fh.read(chunk)
            if not block:
                break
            h.update(block)
    return h.hexdigest()


def align_up(value: int, alignment: int) -> int:
    """Round value up to the next multiple of alignment."""
    if alignment <= 1:
        return value
    return (value + alignment - 1) // alignment * alignment


def human_size(size: int) -> str:
    """Format a byte count as a compact human-readable value."""
    value = float(size)
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if abs(value) < 1024.0 or unit == "TiB":
            return ("%d %s" % (int(value), unit)) if unit == "B" else ("%.2f %s" % (value, unit))
        value /= 1024.0
    return "%d B" % size


def read_lp_string(data: bytes, off: int, endian: str = "<") -> Tuple[str, int]:
    """Read a Unity length-prefixed UTF-8 string and return (text, next_offset)."""
    _need(data, off, 4)
    length = struct.unpack_from(endian + "i", data, off)[0]
    if length < 0 or length > 16 * 1024 * 1024:
        raise ParseError("serialized", "implausible string length %d at 0x%x" % (length, off))
    start = off + 4
    _need(data, start, length)
    raw = data[start:start + length]
    nxt = align_up(start + length, 4)
    if nxt > len(data):
        nxt = start + length
    return raw.decode("utf-8", errors="replace"), nxt


def encode_lp_string(text: str, endian: str = "<") -> bytes:
    """Serialize a Unity length-prefixed UTF-8 string with 4-byte alignment."""
    raw = text.encode("utf-8")
    out = bytearray(struct.pack(endian + "i", len(raw)))
    out += raw
    while len(out) % 4:
        out.append(0)
    return bytes(out)

# 06 CLI
EPILOG = "Global flags must precede the subcommand. Use --help after any subcommand for details."


class ToolArgumentParser(argparse.ArgumentParser):
    """ArgumentParser that converts usage failures into UsageError."""

    def error(self, message: str) -> None:
        raise UsageError("cli", "%s (see --help)" % message)


def _global_parent() -> argparse.ArgumentParser:
    """Global flags accepted after a subcommand as well as before it."""
    parent = argparse.ArgumentParser(add_help=False)
    parent.add_argument("--verbose", action="store_true", default=argparse.SUPPRESS)
    parent.add_argument("--json", action="store_true", dest="json_out", default=argparse.SUPPRESS)
    parent.add_argument("--out", default=argparse.SUPPRESS, metavar="DIR")
    parent.add_argument("--adb", default=argparse.SUPPRESS, metavar="PATH")
    parent.add_argument("--device", default=argparse.SUPPRESS, metavar="SERIAL")
    parent.add_argument("--no-color", action="store_true", default=argparse.SUPPRESS)
    parent.add_argument("--dry-run", action="store_true", dest="dry_run", default=argparse.SUPPRESS)
    parent.add_argument("--force", action="store_true", default=argparse.SUPPRESS)
    parent.add_argument("--selftest", action="store_true", dest="selftest_flag",
                        default=argparse.SUPPRESS)
    return parent


def _sub(parser: argparse.ArgumentParser, name: str, help_text: str, description: str,
         example: str, required: str) -> argparse.ArgumentParser:
    epilog = "Example:\n  %s\nRequired:\n  %s" % (example, required)
    return parser.add_parser(name, help=help_text, description=description, epilog=epilog,
                             parents=[_global_parent()],
                             formatter_class=argparse.RawDescriptionHelpFormatter)


def make_parser() -> argparse.ArgumentParser:
    """Build the full argparse command tree."""
    p = ToolArgumentParser(prog=TOOL_NAME, description="Shitsuke Toolz — MLBB Unity/IL2CPP dev toolkit",
                           epilog=EPILOG, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--verbose", action="store_true", help="verbose diagnostics")
    p.add_argument("--json", action="store_true", dest="json_out", help="emit JSON where supported")
    p.add_argument("--out", default=None, metavar="DIR", help="output directory (or file for single-file commands)")
    p.add_argument("--adb", default=None, metavar="PATH", help="adb executable path or name")
    p.add_argument("--device", default=None, metavar="SERIAL", help="adb device serial")
    p.add_argument("--no-color", action="store_true", help="disable ANSI color")
    p.add_argument("--dry-run", action="store_true", dest="dry_run", help="plan/report without writing")
    p.add_argument("--force", action="store_true", help="overwrite existing outputs where safe")
    p.add_argument("--selftest", action="store_true", dest="selftest_flag", help="run selftest and exit")

    sub = p.add_subparsers(dest="cmd")

    _sub(sub, "banner", "print banner", "Print the banner and exit.", "shitsuke_toolz.py banner", "none")

    sp = _sub(sub, "recon", "resolve target libraries",
              "Probe libil2cpp/liblogic/libmono/libunity, report ABI directory, SHA-256 and ELF arch.",
              "shitsuke_toolz.py recon /path/to/extracted/apk", "directory containing target libraries")
    sp.add_argument("path", nargs="?", default=".", help="directory to scan (default: .)")

    sp = _sub(sub, "elf", "parse ELF headers", "Parse ELF32/ELF64 headers, sections, segments and symbols.",
              "shitsuke_toolz.py elf libil2cpp.so", "ELF file")
    sp.add_argument("path", help="ELF file")

    sp = _sub(sub, "metadata", "parse/recover global-metadata.dat",
              "Parse an IL2CPP metadata header and optionally run the 8-rung recovery ladder.",
              "shitsuke_toolz.py metadata global-metadata.dat --recover --export out/", "metadata file")
    sp.add_argument("path", help="global-metadata.dat or encrypted companion")
    sp.add_argument("--recover", action="store_true", help="run the recovery ladder when direct parse fails")
    sp.add_argument("--export", default=None, metavar="DIR", help="write dump.cs/script.json/stringliteral.json/dump-manifest.json")
    sp.add_argument("--frida-out", default=None, metavar="FILE", help="write rung-8 Frida dumper script")

    sp = _sub(sub, "scan", "scan for an AOB pattern",
              "Wildcard byte-pattern scanner with longest-fixed-run optimization and context bytes.",
              "shitsuke_toolz.py scan libil2cpp.so --pattern '48 8B ?? 90'", "file and --pattern")
    sp.add_argument("path", help="file to scan")
    sp.add_argument("--pattern", required=True, help="hex pattern, ?? wildcard: '48 8B ?? 90'")
    sp.add_argument("--context", type=int, default=16, help="context bytes on each side (default 16)")

    sp = _sub(sub, "strings", "extract strings and symbols",
              "Extract ASCII and UTF-16LE strings plus ELF dynsym/symtab entries; write CSV and JSON.",
              "shitsuke_toolz.py strings libil2cpp.so --min 4 --out out/", "file")
    sp.add_argument("path", help="binary or text file")
    sp.add_argument("--min", type=int, default=4, help="minimum string length (default 4)")

    sp = _sub(sub, "assets", "index dragon2017 assets",
              "Walk dragon2017/assets and mini_patch, hash files, sniff formats and report shadowing.",
              "shitsuke_toolz.py assets --root /path/to/files --out out/", "--root")
    sp.add_argument("--root", required=True, help="game files dir, dragon2017 dir, or assets dir")
    sp.add_argument("--mini-patch", default=None, help="override mini_patch directory")

    sp = _sub(sub, "unityfs", "inspect UnityFS bundles",
              "Parse a UnityFS header, blocks, nodes, decompress payload and optionally extract nodes.",
              "shitsuke_toolz.py unityfs bundle.unity3d --extract out/", "UnityFS bundle")
    sp.add_argument("path", help="UnityFS bundle")
    sp.add_argument("--extract", default=None, metavar="DIR", help="extract nodes to directory")
    sp.add_argument("--serialized", action="store_true", help="parse SerializedFile nodes and AssetBundle info")

    sp = _sub(sub, "skin", "plan/apply a skin swap",
              "Resolve a hero prefix, classify bundle roles, write a plan, back up targets and emit restore.py.",
              "shitsuke_toolz.py skin --hero Fanny --source skin/ --target assets/ --apply", "--source and --target")
    sp.add_argument("--source", required=True, help="source skin directory or file")
    sp.add_argument("--target", required=True, help="target asset directory")
    sp.add_argument("--prefix", default=None, help="asset prefix, e.g. hero_fanny")
    sp.add_argument("--hero", default=None, help="hero name resolved through the hero map")
    sp.add_argument("--hero-map", default=None, metavar="FILE", help="JSON hero-to-prefix overrides")
    sp.add_argument("--apply", action="store_true", help="apply the plan after writing it")
    sp.add_argument("--sync-mini-patch", action="store_true", dest="sync_mini_patch",
                    help="mirror patched paths into the sibling mini_patch tree")
    sp.add_argument("--mini-patch-root", default=None, help="explicit mini_patch directory")

    sp = _sub(sub, "alias", "inject AssetBundle container aliases",
              "Append container aliases to AssetBundle pathID 1, rebuild the bundle and preserve compression/alignment.",
              "shitsuke_toolz.py alias bundle.unity3d --aliases _skin_ _skin01_", "bundle and --aliases")
    sp.add_argument("path", help="UnityFS bundle")
    sp.add_argument("--aliases", nargs="+", required=True, help="container alias paths to append")
    sp.add_argument("--set-name", default=None, metavar="NAME", help="replace m_AssetBundleName")
    sp.add_argument("--output", default=None, metavar="FILE", help="output bundle path (default: *.patched)")
    sp.add_argument("--sync-mini-patch", action="store_true", dest="sync_mini_patch",
                    help="mirror output into the sibling mini_patch tree")
    sp.add_argument("--asset-root", default=None, help="assets root used for mini_patch rel-path mapping")
    sp.add_argument("--mini-patch-root", default=None, help="explicit mini_patch directory")

    sp = _sub(sub, "resmap", "edit GameResAlternative table",
              "Locate mulonggame_table_1, list or rewrite a 4-byte little-endian entry, with .bak backup.",
              "shitsuke_toolz.py resmap /path/to/files --index 3 --skin-id 12", "table file or directory")
    sp.add_argument("path", help="mulonggame_table_1 file or directory containing it")
    sp.add_argument("--index", type=int, default=None, help="record index to rewrite")
    sp.add_argument("--skin-id", type=int, default=None, help="new skin id")
    sp.add_argument("--restore", action="store_true", help="restore from .bak")
    sp.add_argument("--table-name", default="mulonggame_table_1", help="table filename to locate")

    sp = _sub(sub, "xml", "XML pretty/diff/merge/validate",
              "Pretty-print, diff, merge or validate XML; comments and attribute order are preserved.",
              "shitsuke_toolz.py xml diff a.xml b.xml", "mode and input file")
    sp.add_argument("mode", choices=("pretty", "diff", "merge", "validate"))
    sp.add_argument("a", help="primary XML file")
    sp.add_argument("b", nargs="?", help="secondary XML file (diff/merge)")
    sp.add_argument("--schema", default=None, help="optional XSD root-name schema stub")
    sp.add_argument("--no-comments", action="store_true", dest="no_comments", help="drop comments when pretty-printing")

    sp = _sub(sub, "json", "JSON pretty/diff/merge/validate",
              "Pretty-print, diff, merge or validate JSON documents.",
              "shitsuke_toolz.py json merge a.json b.json --out out/", "mode and input file")
    sp.add_argument("mode", choices=("pretty", "diff", "merge", "validate"))
    sp.add_argument("a", help="primary JSON file")
    sp.add_argument("b", nargs="?", help="secondary JSON file (diff/merge)")
    sp.add_argument("--schema", default=None, help="optional JSON schema stub with required/type keys")

    sp = _sub(sub, "gen", "generate validated templates",
              "Emit GameGuardian Lua, Frida JS, C++ or standalone Python templates, validated before write.",
              "shitsuke_toolz.py gen frida hook_method --out out/", "kind and template")
    sp.add_argument("kind", choices=("lua", "frida", "cpp", "python"))
    sp.add_argument("template", help="lua: gg_scan pointer_chain offset_patch aob_scan cooldown_timer config_loader; "
                                     "frida: metadata_dump module_resolve il2cpp_bridge hook_method aob_scan; "
                                     "cpp: stub; python: elf_reader metadata_header unityfs_reader aob_scan")
    sp.add_argument("--name", default=None, help="symbol/name substituted into the template")

    adb_p = _sub(sub, "adb", "ADB wrapper",
                 "Device listing, shell, verified push/pull, filtered logcat, package/window dumps, bugreport.",
                 "shitsuke_toolz.py --adb adb --device emulator-5554 adb devices", "adb in PATH or --adb")
    adb_sub = adb_p.add_subparsers(dest="adb_cmd")
    adb_sub.add_parser("devices", help="list devices")
    ap = adb_sub.add_parser("shell", help="run a shell argv")
    ap.add_argument("command", nargs=argparse.REMAINDER, help="shell command and arguments")
    ap = adb_sub.add_parser("push", help="push and verify sha256")
    ap.add_argument("src")
    ap.add_argument("dst")
    ap = adb_sub.add_parser("pull", help="pull and verify sha256")
    ap.add_argument("src")
    ap.add_argument("dst")
    ap = adb_sub.add_parser("logcat", help="filtered logcat")
    ap.add_argument("--tag", default=None)
    ap.add_argument("--pid", type=int, default=None)
    ap.add_argument("--regex", default=None)
    ap.add_argument("--tail", type=int, default=None)
    ap.add_argument("--duration", type=int, default=None)
    adb_sub.add_parser("pidof", help="pid of com.mobile.legends")
    ap = adb_sub.add_parser("dumpsys", help="package or window focus")
    ap.add_argument("what", nargs="?", default="package", choices=("package", "window"))
    ap = adb_sub.add_parser("bugreport", help="capture a bugreport zip")
    ap.add_argument("--output", default=None)
    ap = adb_sub.add_parser("wireless", help="wireless ADB helper / pair / connect")
    ap.add_argument("--pair", default=None, metavar="HOST:PORT")
    ap.add_argument("--code", default=None)
    ap.add_argument("--connect", default=None, metavar="HOST:PORT")

    sp = _sub(sub, "shizuku", "probe Shizuku and device environment",
              "Print env profile, package/path state and Shizuku availability/version/start mode.",
              "shitsuke_toolz.py --device emulator-5554 shizuku", "adb device")
    sp.add_argument("--pair", default=None, metavar="HOST:PORT")
    sp.add_argument("--code", default=None)
    sp.add_argument("--connect", default=None, metavar="HOST:PORT")

    sp = _sub(sub, "menu", "emit mod menu scaffold",
              "Emit the LGLTeam-style Android mod menu source tree and per-file manifest.",
              "shitsuke_toolz.py menu --out ./modmenu", "none (output dir recommended)")
    sp.add_argument("--pkg", default="com.android.support", help="package root (default com.android.support)")

    sp = _sub(sub, "map", "build an analyst surface map",
              "Match keyword file entries against strings, symbols, metadata literals and XML/JSON assets.",
              "shitsuke_toolz.py map --binary libil2cpp.so --keywords keys.txt --out out/", "--binary and --keywords")
    sp.add_argument("--binary", required=True, help="binary file or asset/binary directory")
    sp.add_argument("--keywords", required=True, help="keyword file (# comments, one per line)")
    sp.add_argument("--exact", action="store_true", help="exact case-insensitive match")
    sp.add_argument("--regex", action="store_true", help="regular-expression match")
    sp.add_argument("--frida-emit", action="store_true", dest="frida_emit", help="write a runtime resolver script")

    _sub(sub, "selftest", "run built-in selftest",
         "Run every subsystem against synthetic fixtures.", "shitsuke_toolz.py selftest", "none")
    return p


def out_dir(args: argparse.Namespace) -> Path:
    """Return and create the requested output directory."""
    base = Path(args.out) if getattr(args, "out", None) else Path(".")
    base.mkdir(parents=True, exist_ok=True)
    return base


def output_path(args: argparse.Namespace, filename: str, as_file: bool = False) -> Path:
    """Resolve --out to either a file path or a directory/filename path."""
    if getattr(args, "out", None):
        p = Path(args.out)
        if as_file and (p.suffix or (p.exists() and p.is_file())):
            return p
        p.mkdir(parents=True, exist_ok=True)
        return p / filename
    return Path(filename)


def require_file(path: Union[str, Path], subsystem: str) -> Path:
    """Validate that a path exists and is a regular file."""
    p = Path(path)
    if not p.exists():
        raise ToolIOError(subsystem, "not found: %s" % p)
    if not p.is_file():
        raise ToolIOError(subsystem, "not a regular file: %s" % p)
    return p


def require_dir(path: Union[str, Path], subsystem: str) -> Path:
    """Validate that a path exists and is a directory."""
    p = Path(path)
    if not p.exists():
        raise ToolIOError(subsystem, "not found: %s" % p)
    if not p.is_dir():
        raise ToolIOError(subsystem, "not a directory: %s" % p)
    return p

# 10 ELF
ELF_MAGIC = b"\x7fELF"
EI_CLASS_32 = 1
EI_CLASS_64 = 2
EI_DATA_LE = 1
EI_DATA_BE = 2
EM_386 = 3
EM_ARM = 40
EM_X86_64 = 62
EM_AARCH64 = 183
ET_NAMES = {0: "NONE", 1: "REL", 2: "EXEC", 3: "DYN", 4: "CORE"}
ARCH_NAMES = {EM_386: "x86", EM_ARM: "ARM", EM_X86_64: "x86_64", EM_AARCH64: "AArch64"}
PT_NAMES = {0: "NULL", 1: "LOAD", 2: "DYNAMIC", 3: "INTERP", 4: "NOTE", 6: "PHDR", 7: "TLS"}
SHT_NAMES = {
    0: "NULL", 1: "PROGBITS", 2: "SYMTAB", 3: "STRTAB", 4: "RELA", 5: "HASH",
    6: "DYNAMIC", 7: "NOTE", 8: "NOBITS", 9: "REL", 10: "SHLIB", 11: "DYNSYM",
    14: "INIT_ARRAY", 15: "FINI_ARRAY", 16: "PREINIT_ARRAY", 17: "GROUP", 18: "SYMTAB_SHNDX",
}
SHF_EXECINSTR = 0x4
SHF_WRITE = 0x1
SHF_ALLOC = 0x2
SHN_UNDEF = 0
SHN_ABS = 0xFFF1
STB_NAMES = {0: "LOCAL", 1: "GLOBAL", 2: "WEAK", 10: "LOOS", 12: "HIOS", 13: "LOPROC", 15: "HIPROC"}
STT_NAMES = {0: "NOTYPE", 1: "OBJECT", 2: "FUNC", 3: "SECTION", 4: "FILE", 5: "COMMON", 6: "TLS",
             10: "GNU_IFUNC"}


def _elf_shdr(data: bytes, endian: str, is64: bool, off: int) -> Dict[str, Any]:
    if is64:
        vals = struct.unpack_from(endian + "IIQQQQIIQQ", data, off)
        keys = ("name_idx", "type", "flags", "addr", "offset", "size", "link", "info", "align", "entsize")
    else:
        vals = struct.unpack_from(endian + "IIIIIIIIII", data, off)
        keys = ("name_idx", "type", "flags", "addr", "offset", "size", "link", "info", "align", "entsize")
    return dict(zip(keys, vals))


def _elf_phdr(data: bytes, endian: str, is64: bool, off: int) -> Dict[str, Any]:
    if is64:
        p_type, p_flags, p_offset, p_vaddr, p_paddr, p_filesz, p_memsz, p_align = struct.unpack_from(
            endian + "IIQQQQQQ", data, off)
    else:
        p_type, p_offset, p_vaddr, p_paddr, p_filesz, p_memsz, p_flags, p_align = struct.unpack_from(
            endian + "IIIIIIII", data, off)
    return {"type": p_type, "flags": p_flags, "offset": p_offset, "vaddr": p_vaddr,
            "paddr": p_paddr, "filesz": p_filesz, "memsz": p_memsz, "align": p_align}


def parse_elf(path: Union[str, Path]) -> Dict[str, Any]:
    """Parse an ELF32/ELF64 image including sections, segments and symbol tables."""
    p = require_file(path, "elf")
    data = p.read_bytes()
    if len(data) < 52 or data[:4] != ELF_MAGIC:
        raise ParseError("elf", "not an ELF image: %s" % p)
    ei_class = data[4]
    ei_data = data[5]
    if ei_class not in (EI_CLASS_32, EI_CLASS_64):
        raise ParseError("elf", "unsupported EI_CLASS %d" % ei_class)
    if ei_data not in (EI_DATA_LE, EI_DATA_BE):
        raise ParseError("elf", "unsupported EI_DATA %d" % ei_data)
    is64 = ei_class == EI_CLASS_64
    endian = "<" if ei_data == EI_DATA_LE else ">"
    need = 64 if is64 else 52
    _need(data, 0, need, "elf")
    if is64:
        e_type, e_machine, e_version, e_entry, e_phoff, e_shoff, e_flags = struct.unpack_from(
            endian + "HHIQQQI", data, 16)
        e_ehsize, e_phentsize, e_phnum, e_shentsize, e_shnum, e_shstrndx = struct.unpack_from(
            endian + "HHHHHH", data, 52)
    else:
        e_type, e_machine, e_version, e_entry, e_phoff, e_shoff, e_flags = struct.unpack_from(
            endian + "HHIIIII", data, 16)
        e_ehsize, e_phentsize, e_phnum, e_shentsize, e_shnum, e_shstrndx = struct.unpack_from(
            endian + "HHHHHH", data, 40)

    sections: List[Dict[str, Any]] = []
    raw_sections: List[Dict[str, Any]] = []
    if e_shoff and e_shentsize:
        if e_shoff + e_shentsize > len(data):
            raise ParseError("elf", "section header table out of range")
        sh0 = _elf_shdr(data, endian, is64, e_shoff)
        real_shnum = e_shnum if e_shnum else int(sh0["size"])
        real_shstrndx = e_shstrndx
        if e_shstrndx == 0xFFFF:
            real_shstrndx = int(sh0["link"])
        if e_shoff + real_shnum * e_shentsize > len(data):
            raise ParseError("elf", "section header table truncated")
        for i in range(real_shnum):
            raw_sections.append(_elf_shdr(data, endian, is64, e_shoff + i * e_shentsize))
        shstr = b""
        if 0 <= real_shstrndx < len(raw_sections):
            sh = raw_sections[real_shstrndx]
            if sh["offset"] + sh["size"] <= len(data):
                shstr = data[sh["offset"]:sh["offset"] + sh["size"]]
        for i, sh in enumerate(raw_sections):
            name = ""
            if shstr and sh["name_idx"] < len(shstr):
                raw = shstr[sh["name_idx"]:]
                cut = raw.find(b"\x00")
                name = (raw[:cut] if cut >= 0 else raw).decode("utf-8", errors="replace")
            flags = int(sh["flags"])
            sections.append({
                "index": i, "name": name, "type": int(sh["type"]),
                "type_name": SHT_NAMES.get(int(sh["type"]), "0x%x" % int(sh["type"])),
                "addr": int(sh["addr"]), "offset": int(sh["offset"]), "size": int(sh["size"]),
                "flags": flags,
                "flags_list": [n for bit, n in ((SHF_WRITE, "W"), (SHF_ALLOC, "A"), (SHF_EXECINSTR, "X")) if flags & bit],
                "executable": bool(flags & SHF_EXECINSTR),
                "link": int(sh["link"]), "info": int(sh["info"]), "align": int(sh["align"]),
                "entsize": int(sh["entsize"]),
            })

    segments: List[Dict[str, Any]] = []
    if e_phoff and e_phentsize:
        if e_phoff + e_phnum * e_phentsize > len(data):
            raise ParseError("elf", "program header table truncated")
        for i in range(e_phnum):
            ph = _elf_phdr(data, endian, is64, e_phoff + i * e_phentsize)
            ph["index"] = i
            ph["type_name"] = PT_NAMES.get(ph["type"], "0x%x" % ph["type"])
            segments.append(ph)

    symbols: List[Dict[str, Any]] = []
    for sec in sections:
        if sec["type"] not in (2, 11):
            continue
        entsize = sec["entsize"] or (24 if is64 else 16)
        if entsize <= 0 or sec["offset"] + sec["size"] > len(data):
            continue
        strtab = b""
        if 0 <= sec["link"] < len(sections):
            st = sections[sec["link"]]
            if st["offset"] + st["size"] <= len(data):
                strtab = data[st["offset"]:st["offset"] + st["size"]]
        count = sec["size"] // entsize
        for j in range(count):
            o = sec["offset"] + j * entsize
            if is64:
                st_name, st_info, st_other, st_shndx, st_value, st_size = struct.unpack_from(
                    endian + "IBBHQQ", data, o)
            else:
                st_name, st_value, st_size, st_info, st_other, st_shndx = struct.unpack_from(
                    endian + "IIIBBH", data, o)
            name = ""
            if strtab and st_name < len(strtab):
                raw = strtab[st_name:]
                cut = raw.find(b"\x00")
                name = (raw[:cut] if cut >= 0 else raw).decode("utf-8", errors="replace")
            if not name and st_name == 0:
                continue
            symbols.append({
                "name": name, "value": int(st_value), "size": int(st_size),
                "bind": int(st_info) >> 4, "type": int(st_info) & 0xF,
                "bind_name": STB_NAMES.get(int(st_info) >> 4, str(int(st_info) >> 4)),
                "type_name": STT_NAMES.get(int(st_info) & 0xF, str(int(st_info) & 0xF)),
                "visibility": int(st_other) & 0x3, "section_index": int(st_shndx),
                "table": ".dynsym" if sec["type"] == 11 else ".symtab",
            })

    exec_count = sum(1 for s in sections if s["executable"])
    arch = ARCH_NAMES.get(e_machine, "unknown")
    return {
        "path": str(p), "sha256": sha256_file(p), "size": len(data),
        "class": "ELF64" if is64 else "ELF32", "bits": 64 if is64 else 32,
        "endian": "little" if endian == "<" else "big",
        "type": int(e_type), "type_name": ET_NAMES.get(int(e_type), "0x%x" % int(e_type)),
        "machine": int(e_machine), "arch": arch, "version": int(e_version),
        "entry": int(e_entry), "flags": int(e_flags),
        "program_header_count": int(e_phnum), "section_header_count": len(sections),
        "exec_section_count": exec_count, "sections": sections, "segments": segments,
        "symbols": symbols,
    }


def elf_offset_to_vaddr(info: Dict[str, Any], offset: int) -> Optional[int]:
    """Map a file offset to a virtual address using PT_LOAD segments."""
    for seg in info.get("segments", []):
        if seg.get("type") == 1 and seg["offset"] <= offset < seg["offset"] + seg["filesz"]:
            return int(seg["vaddr"] + (offset - seg["offset"]))
    return None


def elf_offset_section(info: Dict[str, Any], offset: int) -> Optional[str]:
    """Return the section name containing a file offset, if any."""
    for sec in info.get("sections", []):
        if sec["offset"] <= offset < sec["offset"] + sec["size"]:
            return sec["name"]
    return None


def elf_offset_is_exec(info: Dict[str, Any], offset: int) -> bool:
    """Return True when a file offset lies in an SHF_EXECINSTR section."""
    for sec in info.get("sections", []):
        if sec["executable"] and sec["offset"] <= offset < sec["offset"] + sec["size"]:
            return True
    return False


def resolve_targets(root: Union[str, Path]) -> Dict[str, Any]:
    """Locate target libraries below a directory and report ABI, hashes and ELF arch."""
    base = Path(root)
    if not base.exists():
        raise ToolIOError("recon", "not found: %s" % base)
    search_roots = [base]
    if base.is_file():
        search_roots = [base.parent]
    found: List[Dict[str, Any]] = []
    root_resolved = base.resolve() if base.is_dir() else base.parent.resolve()
    for lib in TARGET_LIBS:
        for candidate in (base.rglob(lib) if base.is_dir() else []):
            if not candidate.is_file():
                continue
            entry: Dict[str, Any] = {"name": lib, "path": str(candidate), "size": candidate.stat().st_size,
                                     "sha256": sha256_file(candidate)}
            abi = next((part for part in candidate.parts if part in ABI_DIRS), None)
            entry["abi"] = abi
            try:
                elf = parse_elf(candidate)
                entry["arch"] = elf["arch"]
                entry["bits"] = elf["bits"]
                entry["endian"] = elf["endian"]
            except ShitsukeError as exc:
                entry["arch"] = None
                entry["elf_error"] = str(exc)
            found.append(entry)
    abis = sorted({e["abi"] for e in found if e.get("abi")})
    missing = [lib for lib in TARGET_LIBS if not any(e["name"] == lib for e in found)]
    return {"root": str(root_resolved), "abi_dirs": abis, "found": found, "missing": missing}

# 11 metadata
METADATA_MAGIC = 0xFAB11BAF
METADATA_FIELDS = [
    "stringLiteral", "stringLiteralData", "string", "events", "properties", "methods",
    "parameters", "fields", "genericParameters", "genericParameterConstraints",
    "genericContainers", "nestedTypes", "interfaces", "vtableMethods", "interfaceOffsets",
    "typeDefinitions", "images", "assemblies", "fieldRefs", "referencedAssemblies",
    "attributeData", "attributeDataRange", "exportedTypeDefinitions",
]
METADATA_HEADER_STRIDE = {24: 8, 27: 8, 29: 8, 31: 8, 39: 12}
METADATA_COUNT_STRIDES = {
    24: {"stringLiteral": 8, "typeDefinitions": 92, "images": 40, "assemblies": 68},
    27: {"stringLiteral": 8, "typeDefinitions": 92, "images": 40, "assemblies": 68},
    29: {"stringLiteral": 8, "typeDefinitions": 96, "images": 40, "assemblies": 68},
    31: {"stringLiteral": 8, "typeDefinitions": 96, "images": 40, "assemblies": 68},
    39: {"stringLiteral": 12, "typeDefinitions": 96, "images": 40, "assemblies": 68},
}
METADATA_RUNG_CONFIDENCE = {
    1: "high", 2: "high", 3: "medium-high", 4: "medium", 5: "medium",
    6: "medium", 7: "medium-low", 8: "low",
}


def _metadata_sections(data: bytes, version: int, stride: int) -> Tuple[Dict[str, Dict[str, Any]], int]:
    header_size = 8 + len(METADATA_FIELDS) * stride
    if len(data) < header_size:
        raise ParseError("metadata", "truncated header: need %d bytes for stride %d" % (header_size, stride))
    sections: Dict[str, Dict[str, Any]] = {}
    off = 8
    for name in METADATA_FIELDS:
        if stride == 12:
            o, sz, count = struct.unpack_from("<III", data, off)
            sections[name] = {"offset": o, "size": sz, "declared_count": count}
        else:
            o, sz = struct.unpack_from("<ii", data, off)
            sections[name] = {"offset": o, "size": sz, "declared_count": None}
        off += stride
    return sections, header_size


def _metadata_plausible(data: bytes, sections: Dict[str, Dict[str, Any]], header_size: int,
                        strict_version: bool = False) -> Tuple[bool, str]:
    version = read_i32_le(data, 4)
    if strict_version and not (20 <= version <= 45):
        return False, "version %d outside 20..45" % version
    if not (15 <= version <= 60):
        return False, "implausible version %d" % version
    total = len(data)
    nonempty = 0
    for name, sec in sections.items():
        off = int(sec["offset"])
        size = int(sec["size"])
        if off < 0 or size < 0:
            return False, "%s has negative offset/size" % name
        if size == 0:
            if off not in (0, total, header_size):
                return False, "%s zero-size with odd offset 0x%x" % (name, off)
            continue
        nonempty += 1
        if off < header_size:
            return False, "%s offset 0x%x before header" % (name, off)
        if off + size > total:
            return False, "%s range 0x%x..0x%x exceeds file %d" % (name, off, off + size, total)
    if nonempty == 0:
        return False, "no non-empty metadata sections"
    return True, "ok"


def parse_metadata_header(data: bytes) -> Dict[str, Any]:
    """Parse a global-metadata.dat header and report table sizes and count estimates."""
    if len(data) < 8:
        raise ParseError("metadata", "too short for header")
    magic = read_u32_le(data, 0)
    if magic != METADATA_MAGIC:
        raise ParseError("metadata", "bad magic 0x%08X" % magic)
    version = read_i32_le(data, 4)
    preferred = METADATA_HEADER_STRIDE.get(version, 8)
    candidates = [preferred]
    if version == 39 and preferred != 8:
        candidates.append(8)
    last_error = ""
    for stride in candidates:
        try:
            sections, header_size = _metadata_sections(data, version, stride)
        except ParseError as exc:
            last_error = str(exc)
            continue
        ok, reason = _metadata_plausible(data, sections, header_size, strict_version=False)
        if not ok:
            last_error = reason
            continue
        count_strides = METADATA_COUNT_STRIDES.get(version, METADATA_COUNT_STRIDES[31])
        counts: Dict[str, Optional[int]] = {}
        for name, entry_stride in count_strides.items():
            size = int(sections.get(name, {}).get("size", 0))
            counts[name + "_count"] = (size // entry_stride) if entry_stride else None
        counts["stringLiteral_count"] = int(sections["stringLiteral"]["size"]) // count_strides["stringLiteral"]
        counts["typeDefinition_count"] = int(sections["typeDefinitions"]["size"]) // count_strides["typeDefinitions"]
        counts["image_count"] = int(sections["images"]["size"]) // count_strides["images"]
        counts["assembly_count"] = int(sections["assemblies"]["size"]) // count_strides["assemblies"]
        for name, sec in sections.items():
            sec["pct"] = round((int(sec["size"]) / len(data) * 100.0), 3) if data else 0.0
            sec["end"] = int(sec["offset"]) + int(sec["size"])
        return {
            "magic": magic, "magic_ok": True, "version": version,
            "header_stride": stride, "header_size": header_size, "file_size": len(data),
            "sections": sections, "counts": counts,
            "stringLiteral_count": counts["stringLiteral_count"],
            "typeDefinition_count": counts["typeDefinition_count"],
            "count_estimates": True,
            "sha256": sha256_bytes(data),
        }
    raise ParseError("metadata", "header rejected: %s" % (last_error or "unknown layout"))


def metadata_string_literals(data: bytes, header: Dict[str, Any], limit: int = 500000) -> List[Dict[str, Any]]:
    """Decode string-literal entries using the version-specific entry stride."""
    sections = header["sections"]
    lit = sections["stringLiteral"]
    dat = sections["stringLiteralData"]
    stride = METADATA_COUNT_STRIDES.get(header["version"], METADATA_COUNT_STRIDES[31])["stringLiteral"]
    out: List[Dict[str, Any]] = []
    if lit["size"] <= 0 or dat["size"] <= 0:
        return out
    count = min(int(lit["size"]) // stride, limit)
    base = int(lit["offset"])
    data_base = int(dat["offset"])
    data_size = int(dat["size"])
    for i in range(count):
        rec = base + i * stride
        try:
            length = read_u32_le(data, rec)
            data_index = read_i32_le(data, rec + 4)
        except ParseError:
            break
        item: Dict[str, Any] = {"index": i, "length": int(length), "data_index": int(data_index), "value": None}
        if 0 <= length <= data_size and 0 <= data_index and data_index + length <= data_size:
            raw = data[data_base + data_index:data_base + data_index + length]
            item["value"] = raw.decode("utf-8", errors="replace")
        else:
            item["value"] = None
        out.append(item)
    return out


def metadata_type_names(data: bytes, header: Dict[str, Any], limit: int = 200000) -> List[Dict[str, Any]]:
    """Decode type-definition name/namespace indices when the layout is recognized."""
    sections = header["sections"]
    td = sections["typeDefinitions"]
    st = sections["string"]
    if td["size"] <= 0:
        return []
    stride = METADATA_COUNT_STRIDES.get(header["version"], METADATA_COUNT_STRIDES[31])["typeDefinitions"]
    if stride < 8 or st["size"] <= 0:
        return []
    count = min(int(td["size"]) // stride, limit)
    out: List[Dict[str, Any]] = []
    str_base = int(st["offset"])
    str_size = int(st["size"])

    def read_index(idx: int) -> Optional[str]:
        if idx <= 0 or idx >= str_size:
            return None
        raw = data[str_base + idx:str_base + str_size]
        cut = raw.find(b"\x00")
        if cut < 0:
            cut = min(len(raw), 256)
        return raw[:cut].decode("utf-8", errors="replace")

    for i in range(count):
        rec = int(td["offset"]) + i * stride
        try:
            name_idx = read_u32_le(data, rec)
            ns_idx = read_u32_le(data, rec + 4)
        except ParseError:
            break
        name = read_index(name_idx)
        namespace = read_index(ns_idx)
        out.append({"index": i, "name": name, "namespace": namespace})
    return out


def metadata_dump_frida_script() -> str:
    """Return the rung-8 memory-only Frida metadata dumper."""
    return r'''// shitsuke_toolz metadata_dump (rung 8)
// Run:
//   frida -U -f com.mobile.legends -l metadata_dump.js --no-pause
var MAGIC = 'af 1b b1 fa';
var MAX_SPAN = 64 * 1024 * 1024;
Process.enumerateRanges('r--').forEach(function (range) {
  try {
    Memory.scan(range.base, range.size, MAGIC, {
      onMatch: function (addr) {
        try {
          var ver = addr.add(4).readS32();
          if (ver < 20 || ver > 45) return;
          var stride = (ver === 39) ? 12 : 8;
          var headerSize = 8 + 23 * stride;
          var span = headerSize;
          for (var i = 0; i < 23; i++) {
            var p = addr.add(8 + i * stride);
            var off = p.readU32();
            var sz = p.readU32();
            if (off > MAX_SPAN || sz > MAX_SPAN) return;
            if (sz > 0) {
              if (off < headerSize) return;
              span = Math.max(span, off + sz);
            }
          }
          if (span < headerSize || span > MAX_SPAN) return;
          var out = '/data/local/tmp/metadata_' + Process.id + '_' + addr + '.bin';
          var f = new File(out, 'wb');
          f.write(addr.readByteArray(span));
          f.close();
          console.log('[metadata] version=' + ver + ' addr=' + addr + ' span=' + span + ' -> ' + out);
        } catch (e) {
          console.log('[metadata] candidate failed: ' + e);
        }
      },
      onComplete: function () {}
    });
  } catch (e) {}
});
console.log('[metadata] scan complete; pull with: adb pull /data/local/tmp/metadata_<pid>_<addr>.bin');
'''


def metadata_partition_reassemble(search_dir: Path) -> Optional[Dict[str, Any]]:
    """Reassemble companion metadata partitions (10-60 MB) and recover their header."""
    if not search_dir.is_dir():
        return None
    files = [p for p in search_dir.iterdir() if p.is_file()]
    groups: List[Tuple[str, List[Path]]] = []
    gm = [p for p in files if p.name.startswith("global-metadata.dat.")]
    if gm:
        groups.append(("global-metadata.dat.*", sorted(gm, key=lambda p: _natural_key(p.name))))
    parts = [p for p in files if "metadata.part" in p.name]
    if parts:
        groups.append(("metadata.part*", sorted(parts, key=lambda p: _natural_key(p.name))))
    bins = [p for p in files if p.name.endswith(".bin")]
    if bins:
        groups.append(("sequential .bin", sorted(bins, key=lambda p: _natural_key(p.name))))
    for label, group in groups:
        total = sum(p.stat().st_size for p in group)
        if not (10 * 1024 * 1024 <= total <= 60 * 1024 * 1024):
            continue
        blob = b"".join(p.read_bytes() for p in group)
        recovered = _metadata_recover_core(blob, allow_partition=False)
        if recovered is not None:
            recovered["files"] = [str(p) for p in group]
            recovered["description"] = "%s via %s" % (recovered["description"], label)
            return recovered
    return None


def _natural_key(name: str) -> List[Any]:
    return [int(part) if part.isdigit() else part.lower() for part in re.split(r"(\d+)", name)]


def _metadata_recover_core(data: bytes, allow_partition: bool = True) -> Optional[Dict[str, Any]]:
    try:
        header = parse_metadata_header(data)
        return {"rung": 1, "description": "direct parse", "offset": 0, "data": data, "header": header}
    except ParseError:
        pass
    limit = min(len(data), 0x10000)
    magic_bytes = struct.pack("<I", METADATA_MAGIC)
    start = data.find(magic_bytes)
    while 0 <= start < limit:
        if start % 4 == 0 and start > 0:
            try:
                header = parse_metadata_header(data[start:])
                return {"rung": 2, "description": "aligned magic scan", "offset": start,
                        "data": data[start:], "header": header}
            except ParseError:
                pass
        start = data.find(magic_bytes, start + 1)
    if len(data) >= 4 and (read_u32_le(data, 0) ^ 0xFFFFFFFF) == METADATA_MAGIC:
        inv = bytes((~b) & 0xFF for b in data)
        try:
            header = parse_metadata_header(inv)
            return {"rung": 3, "description": "bitwise NOT, full-file inversion", "offset": 0,
                    "data": inv, "header": header}
        except ParseError:
            pass
        patched = bytearray(data)
        patched[:4] = magic_bytes
        try:
            header = parse_metadata_header(bytes(patched))
            return {"rung": 3, "description": "bitwise NOT, magic-only inversion", "offset": 0,
                    "data": bytes(patched), "header": header}
        except ParseError:
            pass
    if len(data) >= 8:
        for key in range(1, 256):
            if (read_u32_le(data, 0) ^ (key * 0x01010101)) == METADATA_MAGIC:
                dec = bytes(b ^ key for b in data)
                try:
                    header = parse_metadata_header(dec)
                    ok, _ = _metadata_plausible(dec, header["sections"], header["header_size"], strict_version=True)
                    if ok:
                        return {"rung": 4, "description": "single-byte XOR key 0x%02x" % key, "offset": 0,
                                "data": dec, "header": header}
                except ParseError:
                    pass
    if len(data) >= 8:
        key = bytes(data[i] ^ magic_bytes[i] for i in range(4))
        dec = bytes(data[i] ^ key[i % 4] for i in range(len(data)))
        try:
            header = parse_metadata_header(dec)
            ok, _ = _metadata_plausible(dec, header["sections"], header["header_size"], strict_version=True)
            if ok:
                return {"rung": 5, "description": "4-byte repeating XOR key %s" % key.hex(), "offset": 0,
                        "data": dec, "header": header}
        except ParseError:
            pass
    return None


def _metadata_companion_library(search_dir: Path) -> Optional[Dict[str, Any]]:
    if not search_dir.is_dir():
        return None
    magic_bytes = struct.pack("<I", METADATA_MAGIC)
    for name in ("liblogic.so", "libil2cpp.so"):
        for lib in search_dir.rglob(name):
            if not lib.is_file():
                continue
            data = lib.read_bytes()
            start = data.find(magic_bytes)
            while start >= 0:
                if start % 4 == 0:
                    try:
                        header = parse_metadata_header(data[start:])
                        vaddr = None
                        try:
                            elf = parse_elf(lib)
                            vaddr = elf_offset_to_vaddr(elf, start)
                        except ShitsukeError:
                            vaddr = None
                        return {"rung": 7, "description": "companion library embedded metadata",
                                "offset": start, "data": data[start:], "header": header,
                                "library": str(lib), "library_offset": start, "vaddr": vaddr}
                    except ParseError:
                        pass
                start = data.find(magic_bytes, start + 1)
    return None


def metadata_recover(data: bytes, base_dir: Optional[Path] = None) -> Dict[str, Any]:
    """Run the 8-rung recovery ladder and return the first credible result."""
    found = _metadata_recover_core(data, allow_partition=True)
    if found is not None:
        found["confidence"] = METADATA_RUNG_CONFIDENCE[found["rung"]]
        found["files"] = []
        return found
    if base_dir is not None:
        part = metadata_partition_reassemble(base_dir)
        if part is not None:
            part["confidence"] = METADATA_RUNG_CONFIDENCE[6]
            return part
        lib = _metadata_companion_library(base_dir)
        if lib is not None:
            lib["confidence"] = METADATA_RUNG_CONFIDENCE[7]
            lib["files"] = []
            return lib
    return {
        "rung": 8, "description": "memory-only", "offset": None, "data": None, "header": None,
        "confidence": METADATA_RUNG_CONFIDENCE[8], "files": [],
        "script": metadata_dump_frida_script(),
        "frida_command": "frida -U -f %s -l metadata_dump.js --no-pause" % APP_PKG,
    }


def metadata_report(data: bytes, recover: bool = False, base_dir: Optional[Path] = None) -> Dict[str, Any]:
    """Build a JSON-safe metadata report, optionally through the recovery ladder."""
    result: Dict[str, Any] = {"input_size": len(data), "input_sha256": sha256_bytes(data)}
    if recover:
        found = metadata_recover(data, base_dir)
        result["recovery"] = {k: v for k, v in found.items() if k != "data"}
        if found.get("header") is not None:
            result["header"] = found["header"]
        else:
            result["header"] = None
        return result
    result["header"] = parse_metadata_header(data)
    result["recovery"] = {"rung": 1, "description": "direct parse", "confidence": "high", "offset": 0}
    return result


def export_metadata_reference(data: bytes, header: Dict[str, Any], out_dir: Path,
                              input_path: Optional[Path] = None, recovery: Optional[Dict[str, Any]] = None) -> List[Path]:
    """Write dump.cs, script.json, stringliteral.json and dump-manifest.json."""
    out_dir.mkdir(parents=True, exist_ok=True)
    literals = metadata_string_literals(data, header)
    type_names = metadata_type_names(data, header)
    written: List[Path] = []
    literals_obj = {
        "version": header["version"], "count": len(literals),
        "truncated": len(literals) >= 500000, "literals": literals,
    }
    written.append(write_json(out_dir / "stringliteral.json", literals_obj))
    dump_lines = [
        "// shitsuke_toolz IL2CPP reference",
        "// metadata version: %s" % header["version"],
        "// header sha256: %s" % header["sha256"],
        "// NOTE: method RVAs are not present in global-metadata.dat; null fields are intentional.",
        "",
    ]
    if type_names:
        for item in type_names:
            name = item["name"]
            ns = item["namespace"]
            if name is None:
                dump_lines.append("// type[%d] name=null namespace=%r" % (item["index"], ns))
            else:
                dump_lines.append("// %s%s" % ((ns + ".") if ns else "", name))
    else:
        dump_lines.append("// type definitions: null (section empty or unsupported type layout)")
    written.append(atomic_write(out_dir / "dump.cs", ("\n".join(dump_lines) + "\n").encode("utf-8")))
    script = {
        "version": header["version"],
        "metadata_sha256": header["sha256"],
        "sections": header["sections"],
        "string_literal_count": header["stringLiteral_count"],
        "type_definition_count": header["typeDefinition_count"],
        "type_names": type_names if type_names else None,
        "methods": None,
        "method_addresses": None,
        "note": "RVA table unavailable in metadata; resolve via libil2cpp exports or code registration.",
    }
    written.append(write_json(out_dir / "script.json", script))
    manifest = {
        "tool": TOOL_NAME, "tool_version": TOOL_VERSION, "kind": "il2cpp-metadata",
        "input": str(input_path) if input_path else None,
        "input_sha256": sha256_bytes(data), "input_size": len(data),
        "metadata_sha256": header["sha256"], "version": header["version"],
        "recovery": {k: v for k, v in (recovery or {}).items() if k not in ("data", "script")},
        "section_table": header["sections"], "section_table_pct": True,
        "counts": header["counts"], "outputs": ["dump.cs", "script.json", "stringliteral.json"],
        "absent_data": {"methods": None, "method_addresses": None},
    }
    written.append(write_json(out_dir / "dump-manifest.json", manifest))
    return written

# 12 AOB
def aob_scan(data: bytes, pattern: str) -> List[int]:
    """Return every file offset where the wildcard byte pattern matches."""
    values, masks = pattern_to_bytes_mask(pattern)
    plen = len(values)
    n = len(data)
    if plen == 0 or n < plen:
        return []
    runs: List[Tuple[int, int, bytes]] = []
    i = 0
    while i < plen:
        if masks[i]:
            j = i
            while j < plen and masks[j]:
                j += 1
            runs.append((i, j - i, values[i:j]))
            i = j
        else:
            i += 1
    if not runs:
        return []
    rel, run_len, needle = max(runs, key=lambda item: item[1])
    hits: List[int] = []
    start = 0
    while True:
        idx = data.find(needle, start)
        if idx < 0:
            break
        cand = idx - rel
        if 0 <= cand <= n - plen:
            ok = True
            for k in range(plen):
                if masks[k] and data[cand + k] != values[k]:
                    ok = False
                    break
            if ok:
                hits.append(cand)
        start = idx + 1
    return hits


def aob_hits(data: bytes, pattern: str, context: int = 16,
             elf_info: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    """Return enriched AOB hits with vaddr, section and two-sided context."""
    out: List[Dict[str, Any]] = []
    for off in aob_scan(data, pattern):
        before = data[max(0, off - context):off]
        after = data[off:min(len(data), off + context)]
        item: Dict[str, Any] = {
            "offset": off,
            "vaddr": elf_offset_to_vaddr(elf_info, off) if elf_info else None,
            "section": elf_offset_section(elf_info, off) if elf_info else None,
            "context_before": before.hex(),
            "context_after": after.hex(),
            "match": data[off:off + len(pattern_to_bytes_mask(pattern)[0])].hex(),
        }
        out.append(item)
    return out


# 13 strings/symbols
def extract_strings(data: bytes, min_len: int = 4) -> List[Dict[str, Any]]:
    """Extract ASCII and UTF-16LE printable runs at least min_len characters long."""
    if min_len < 1:
        raise UsageError("strings", "min length must be >= 1")
    out: List[Dict[str, Any]] = []
    n = len(data)
    i = 0
    while i < n:
        b = data[i]
        if 32 <= b < 127:
            j = i
            while j < n and 32 <= data[j] < 127:
                j += 1
            if j - i >= min_len:
                out.append({"offset": i, "encoding": "ascii", "value": data[i:j].decode("ascii"),
                            "char_length": j - i})
            i = j
        else:
            i += 1
    i = 0
    while i + 1 < n:
        j = i
        chars: List[str] = []
        while j + 1 < n:
            code = data[j] | (data[j + 1] << 8)
            if 32 <= code < 127 or code in (9, 10, 13):
                chars.append(chr(code))
                j += 2
            else:
                break
        if len(chars) >= min_len:
            out.append({"offset": i, "encoding": "utf16le", "value": "".join(chars),
                        "char_length": len(chars)})
            i = j if j > i else i + 2
        else:
            i += 1
    out.sort(key=lambda item: (item["offset"], item["encoding"]))
    return out


def extract_symbols(path: Union[str, Path]) -> List[Dict[str, Any]]:
    """Return dynsym/symtab symbols with bind/type metadata; empty for non-ELF files."""
    try:
        info = parse_elf(path)
    except ShitsukeError:
        return []
    return list(info.get("symbols", []))


def strings_csv(rows: Iterable[Dict[str, Any]]) -> str:
    """Serialize string rows as CSV text."""
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=["offset", "encoding", "char_length", "value"])
    writer.writeheader()
    for row in rows:
        writer.writerow(row)
    return buf.getvalue()


def strings_report(path: Union[str, Path], min_len: int = 4) -> Dict[str, Any]:
    """Build a combined strings+symbols report for a file."""
    p = require_file(path, "strings")
    data = p.read_bytes()
    strings = extract_strings(data, min_len)
    symbols = extract_symbols(p)
    return {
        "path": str(p), "size": len(data), "sha256": sha256_bytes(data),
        "min_length": min_len, "string_count": len(strings), "symbol_count": len(symbols),
        "strings": strings, "symbols": symbols,
    }

# 20 UnityFS
UNITYFS_MAGIC = b"UnityFS\x00"
UNITYFS_SUPPORTED = (6, 7, 8)
UNITYFS_COMP_NONE = 0
UNITYFS_COMP_LZMA = 1
UNITYFS_COMP_LZ4 = 2
UNITYFS_COMP_LZ4HC = 3
UNITYFS_MAX_OUTPUT = 512 * 1024 * 1024


def _read_be_u32(data: bytes, off: int) -> int:
    _need(data, off, 4, "unityfs")
    return struct.unpack_from(">I", data, off)[0]


def _read_be_i32(data: bytes, off: int) -> int:
    _need(data, off, 4, "unityfs")
    return struct.unpack_from(">i", data, off)[0]


def _read_be_i64(data: bytes, off: int) -> int:
    _need(data, off, 8, "unityfs")
    return struct.unpack_from(">q", data, off)[0]


def parse_unityfs_header(data: bytes) -> Dict[str, Any]:
    """Parse a UnityFS header, rejecting format 9 and unsupported versions."""
    if len(data) < 32 or not data.startswith(UNITYFS_MAGIC):
        raise ParseError("unityfs", "bad UnityFS magic or truncated header")
    off = 8
    format_version = _read_be_u32(data, off)
    off += 4
    if format_version == 9:
        raise ParseError("unityfs", "format_version 9 is not supported")
    if format_version not in UNITYFS_SUPPORTED:
        raise ParseError("unityfs", "unsupported format_version %d" % format_version)
    end = data.find(b"\x00", off, min(len(data), off + 1024))
    if end < 0:
        raise ParseError("unityfs", "unterminated player_version")
    player_version = data[off:end].decode("utf-8", errors="replace")
    off = end + 1
    end = data.find(b"\x00", off, min(len(data), off + 1024))
    if end < 0:
        raise ParseError("unityfs", "unterminated engine_version")
    engine_version = data[off:end].decode("utf-8", errors="replace")
    off = end + 1
    _need(data, off, 20, "unityfs")
    bundle_size = _read_be_i64(data, off); off += 8
    compressed_info_size = _read_be_u32(data, off); off += 4
    uncompressed_info_size = _read_be_u32(data, off); off += 4
    flags = _read_be_u32(data, off); off += 4
    if format_version >= 7:
        off = align_up(off, 16)
    if off > len(data):
        raise ParseError("unityfs", "header alignment exceeds file size")
    blocks_info_at_end = bool(flags & 0x80)
    if blocks_info_at_end:
        info_off = len(data) - compressed_info_size
    else:
        info_off = off
    if info_off < off or info_off + compressed_info_size > len(data):
        raise ParseError("unityfs", "blocksInfo range invalid")
    data_start = off if blocks_info_at_end else info_off + compressed_info_size
    compression = flags & 0x3F
    if compression not in (0, 1, 2, 3):
        raise ParseError("unityfs", "unknown compression flag %d" % compression)
    return {
        "format_version": format_version,
        "player_version": player_version,
        "engine_version": engine_version,
        "bundle_size": bundle_size,
        "compressed_blocks_info_size": compressed_info_size,
        "uncompressed_blocks_info_size": uncompressed_info_size,
        "flags": flags,
        "compression": compression,
        "blocks_info_at_end": blocks_info_at_end,
        "blocks_info_compressed": bool(flags & 0x40),
        "padding": bool(flags & 0x200),
        "header_size": off,
        "blocks_info_offset": info_off,
        "data_start": data_start,
    }


def lzma_decompress_unity(src: bytes, dst_size: int) -> bytes:
    """Decode Unity's LZMA block by reconstructing a FORMAT_ALONE stream."""
    if len(src) < 13:
        raise ParseError("unityfs", "LZMA block shorter than 13 bytes")
    props = src[:5]
    size_bytes = src[5:13]
    stream = props + size_bytes + src[13:]
    try:
        out = lzma.decompress(stream, format=lzma.FORMAT_ALONE)
    except lzma.LZMAError as exc:
        raise ParseError("unityfs", "LZMA decompression failed: %s" % exc) from exc
    if dst_size > 0 and len(out) != dst_size:
        raise ParseError("unityfs", "LZMA size mismatch: got %d want %d" % (len(out), dst_size))
    return out


def lz4_block_decompress_pure(src: bytes, dst_size: int) -> bytes:
    """Pure-Python LZ4 block decoder with strict bounds and overlap handling."""
    cap = dst_size if dst_size > 0 else UNITYFS_MAX_OUTPUT
    if cap > UNITYFS_MAX_OUTPUT:
        raise ParseError("unityfs", "LZ4 output cap too large: %d" % cap)
    out = bytearray()
    i = 0
    n = len(src)
    while i < n:
        token = src[i]
        i += 1
        lit_len = token >> 4
        if lit_len == 15:
            while True:
                if i >= n:
                    raise ParseError("unityfs", "LZ4 truncated literal extension")
                b = src[i]
                i += 1
                lit_len += b
                if lit_len > cap + 1:
                    raise ParseError("unityfs", "LZ4 literal overflow")
                if b != 0xFF:
                    break
        if i + lit_len > n:
            raise ParseError("unityfs", "LZ4 truncated literals")
        out.extend(src[i:i + lit_len])
        i += lit_len
        if len(out) > cap:
            raise ParseError("unityfs", "LZ4 output overflow")
        if i >= n:
            break
        if i + 2 > n:
            raise ParseError("unityfs", "LZ4 truncated match offset")
        offset = src[i] | (src[i + 1] << 8)
        i += 2
        if offset == 0 or offset > len(out):
            raise ParseError("unityfs", "LZ4 invalid match offset %d" % offset)
        match_len = (token & 0x0F) + 4
        if (token & 0x0F) == 15:
            while True:
                if i >= n:
                    raise ParseError("unityfs", "LZ4 truncated match extension")
                b = src[i]
                i += 1
                match_len += b
                if match_len > cap + 1:
                    raise ParseError("unityfs", "LZ4 match overflow")
                if b != 0xFF:
                    break
        if len(out) + match_len > cap:
            raise ParseError("unityfs", "LZ4 match exceeds output size")
        start = len(out) - offset
        for _ in range(match_len):
            out.append(out[start])
            start += 1
    if dst_size > 0 and len(out) != dst_size:
        raise ParseError("unityfs", "LZ4 size mismatch: got %d want %d" % (len(out), dst_size))
    return bytes(out)


def lz4_block_decompress(src: bytes, dst_size: int) -> Tuple[bytes, str]:
    """Decode an LZ4 block, preferring the optional lz4 module and falling back to pure Python."""
    if HAS_LZ4 and lz4_block is not None:
        try:
            return lz4_block.decompress(src, uncompressed_size=dst_size), "lz4-module"
        except Exception:
            pass
    return lz4_block_decompress_pure(src, dst_size), "pure-python"


def lz4_block_compress_pure(src: bytes) -> bytes:
    """Emit a valid literal-only LZ4 block (real LZ4 framing, no back-references)."""
    n = len(src)
    out = bytearray()
    literal = n
    token = (min(literal, 15) << 4)
    out.append(token)
    if literal >= 15:
        remaining = literal - 15
        while remaining >= 255:
            out.append(255)
            remaining -= 255
        out.append(remaining)
    out.extend(src)
    return bytes(out)


def compress_block(data: bytes, compression: int) -> bytes:
    """Compress one block using the requested UnityFS compression id."""
    if compression == 0:
        return data
    if compression == 1:
        return lzma.compress(data, format=lzma.FORMAT_ALONE)
    if compression in (2, 3):
        if HAS_LZ4 and lz4_block is not None:
            try:
                return lz4_block.compress(data, store_size=False)
            except Exception:
                pass
        return lz4_block_compress_pure(data)
    raise ParseError("unityfs", "unsupported compression id %d" % compression)


def decompress_block(payload: bytes, compression: int, dst_size: int) -> Tuple[bytes, str]:
    """Decompress one block and return (bytes, method-used)."""
    if compression == 0:
        if dst_size > 0 and len(payload) != dst_size:
            raise ParseError("unityfs", "raw block size mismatch")
        return payload, "raw"
    if compression == 1:
        return lzma_decompress_unity(payload, dst_size), "lzma"
    if compression in (2, 3):
        data, path = lz4_block_decompress(payload, dst_size)
        return data, path
    raise ParseError("unityfs", "unsupported compression id %d" % compression)


def _parse_blocks_payload(payload: bytes, max_total: int) -> Optional[Dict[str, Any]]:
    for hash_len in (16, 0):
        try:
            io = hash_len
            _need(payload, io, 4, "unityfs")
            block_count = _read_be_i32(payload, io)
            io += 4
            if block_count < 0 or block_count > 1000000:
                continue
            if io + block_count * 10 + 4 > len(payload):
                continue
            blocks: List[Dict[str, Any]] = []
            total_unc = 0
            for _ in range(block_count):
                unc = _read_be_u32(payload, io); io += 4
                cpr = _read_be_u32(payload, io); io += 4
                _need(payload, io, 2, "unityfs")
                fl = struct.unpack_from(">H", payload, io)[0]; io += 2
                if unc > max_total or cpr > max_total:
                    raise ParseError("unityfs", "implausible block size")
                total_unc += unc
                blocks.append({"uncompressed_size": unc, "compressed_size": cpr, "flags": fl,
                               "compression": fl & 0x3F})
            _need(payload, io, 4, "unityfs")
            node_count = _read_be_i32(payload, io)
            io += 4
            if node_count < 0 or node_count > 1000000:
                continue
            nodes: List[Dict[str, Any]] = []
            for _ in range(node_count):
                _need(payload, io, 20, "unityfs")
                offset = _read_be_i64(payload, io); io += 8
                size = _read_be_i64(payload, io); io += 8
                flags = _read_be_u32(payload, io); io += 4
                if offset < 0 or size < 0:
                    raise ParseError("unityfs", "negative node offset/size")
                if offset + size > max_total:
                    raise ParseError("unityfs", "node range exceeds block output")
                end = payload.find(b"\x00", io, min(len(payload), io + 4096))
                if end < 0:
                    raise ParseError("unityfs", "unterminated node path")
                path = payload[io:end].decode("utf-8", errors="replace")
                io = end + 1
                nodes.append({"offset": offset, "size": size, "flags": flags, "path": path})
            return {"hash": payload[:16].hex() if hash_len else None, "hash_present": bool(hash_len),
                    "blocks": blocks, "nodes": nodes, "total_uncompressed": total_unc,
                    "payload_consumed": io}
        except ParseError:
            continue
    return None


def parse_blocks_info(data: bytes, hdr: Dict[str, Any]) -> Dict[str, Any]:
    """Decompress and parse a UnityFS BlocksInfo table and node list."""
    off = int(hdr["blocks_info_offset"])
    comp_size = int(hdr["compressed_blocks_info_size"])
    unc_size = int(hdr["uncompressed_blocks_info_size"])
    _need(data, off, comp_size, "unityfs")
    raw = data[off:off + comp_size]
    compression = int(hdr["compression"])
    path = "raw"
    if hdr["blocks_info_compressed"]:
        if compression == 0:
            info_data = raw
            path = "raw"
        else:
            info_data, path = decompress_block(raw, compression, unc_size)
    else:
        info_data = raw
        if unc_size > 0 and len(info_data) > unc_size:
            raise ParseError("unityfs", "blocksInfo larger than declared size")
    if unc_size > 0 and len(info_data) != unc_size:
        raise ParseError("unityfs", "blocksInfo size mismatch: got %d want %d" % (len(info_data), unc_size))
    parsed = _parse_blocks_payload(info_data, UNITYFS_MAX_OUTPUT)
    if parsed is None:
        raise ParseError("unityfs", "BlocksInfo table invalid")
    parsed["compression_path"] = path
    parsed["info_size"] = len(info_data)
    parsed["data_start"] = int(hdr["data_start"])
    return parsed


def read_unityfs_bytes(data: bytes, source: str = "<memory>") -> Dict[str, Any]:
    """Decode a UnityFS image held in memory, including all decompressed blocks."""
    hdr = parse_unityfs_header(data)
    info = parse_blocks_info(data, hdr)
    block_data_start = int(info["data_start"])
    cursor = block_data_start
    chunks: List[bytes] = []
    paths: List[str] = []
    total = 0
    for block in info["blocks"]:
        csize = int(block["compressed_size"])
        _need(data, cursor, csize, "unityfs")
        chunk, used = decompress_block(data[cursor:cursor + csize], int(block["compression"]),
                                       int(block["uncompressed_size"]))
        cursor += csize
        total += len(chunk)
        if total > UNITYFS_MAX_OUTPUT:
            raise ParseError("unityfs", "decompressed payload exceeds cap")
        chunks.append(chunk)
        paths.append(used)
    payload = b"".join(chunks)
    if int(info["total_uncompressed"]) != len(payload):
        raise ParseError("unityfs", "block output does not match declared total")
    for node in info["nodes"]:
        if node["offset"] + node["size"] > len(payload):
            raise ParseError("unityfs", "node %s exceeds payload" % node["path"])
    return {
        "path": source, "file_size": len(data), "sha256": sha256_bytes(data),
        "header": hdr, "blocks": info["blocks"], "nodes": info["nodes"],
        "blocks_info_hash": info["hash"], "blocks_info_hash_present": info["hash_present"],
        "compression_paths": paths, "payload": payload,
        "data_start": block_data_start,
    }


def read_unityfs(path: Union[str, Path]) -> Dict[str, Any]:
    """Load a UnityFS bundle from disk, decompress all blocks and expose node payloads."""
    p = require_file(path, "unityfs")
    data = p.read_bytes()
    result = read_unityfs_bytes(data, str(p))
    result["sha256"] = sha256_file(p)
    return result


def node_bytes(bundle: Dict[str, Any], node: Dict[str, Any]) -> bytes:
    """Return the decompressed bytes belonging to one UnityFS node."""
    start = int(node["offset"])
    end = start + int(node["size"])
    return bundle["payload"][start:end]


def build_unityfs(hdr: Dict[str, Any], nodes: List[Dict[str, Any]], node_data: List[bytes],
                  flags: Optional[int] = None) -> bytes:
    """Rebuild a UnityFS bundle from node payloads, preserving version and strings."""
    if len(nodes) != len(node_data):
        raise UsageError("unityfs", "nodes/node_data length mismatch")
    out_flags = int(hdr["flags"]) if flags is None else int(flags)
    compression = out_flags & 0x3F
    if compression not in (0, 1, 2, 3):
        compression = 3
        out_flags = (out_flags & ~0x3F) | 3
    at_end = bool(out_flags & 0x80)
    info_compressed = bool(out_flags & 0x40)
    payload = bytearray()
    new_nodes: List[Dict[str, Any]] = []
    for node, blob in zip(nodes, node_data):
        while len(payload) % 16:
            payload.append(0)
        offset = len(payload)
        payload.extend(blob)
        new_nodes.append({"offset": offset, "size": len(blob), "flags": int(node.get("flags", 0)),
                          "path": str(node.get("path", ""))})
    info = bytearray()
    info.extend(b"\x00" * 16)
    info.extend(struct.pack(">i", 1 if payload else 0))
    if payload:
        compressed_payload = compress_block(bytes(payload), compression)
        info.extend(struct.pack(">IIH", len(payload), len(compressed_payload), compression))
    else:
        compressed_payload = b""
    info.extend(struct.pack(">i", len(new_nodes)))
    for node in new_nodes:
        info.extend(struct.pack(">qqI", node["offset"], node["size"], node["flags"]))
        info.extend(node["path"].encode("utf-8") + b"\x00")
    info_raw = bytes(info)
    info_payload = compress_block(info_raw, compression) if info_compressed else info_raw
    player = hdr["player_version"].encode("utf-8") + b"\x00"
    engine = hdr["engine_version"].encode("utf-8") + b"\x00"
    prefix = bytearray()
    prefix.extend(UNITYFS_MAGIC)
    prefix.extend(struct.pack(">I", int(hdr["format_version"])))
    prefix.extend(player)
    prefix.extend(engine)
    prefix.extend(struct.pack(">qIII", 0, len(info_payload), len(info_raw), out_flags))
    if int(hdr["format_version"]) >= 7:
        while len(prefix) % 16:
            prefix.append(0)
    header_size = len(prefix)
    if at_end:
        body = bytearray(compressed_payload)
        info_offset = header_size + len(body)
        body.extend(info_payload)
    else:
        info_offset = header_size
        body = bytearray(info_payload)
        body.extend(compressed_payload)
    total = header_size + len(body)
    struct.pack_into(">q", prefix, len(prefix) - 20, total)
    result = bytes(prefix) + bytes(body)
    if len(result) != total:
        raise ParseError("unityfs", "internal rebuild size mismatch")
    hdr_out = dict(hdr)
    hdr_out.update({"flags": out_flags, "compression": compression, "blocks_info_at_end": at_end,
                    "blocks_info_compressed": info_compressed, "compressed_blocks_info_size": len(info_payload),
                    "uncompressed_blocks_info_size": len(info_raw), "bundle_size": total,
                    "header_size": header_size, "blocks_info_offset": info_offset})
    return result

# 21 SerializedFile/alias
SERIALIZED_MAX_METADATA = 128 * 1024 * 1024
ASSET_BUNDLE_CLASS_ID = 142


class _SReader:
    def __init__(self, data: bytes, pos: int, endian: str, end: int) -> None:
        self.data = data
        self.pos = pos
        self.endian = endian
        self.end = min(end, len(data))

    def take(self, size: int) -> bytes:
        if size < 0 or self.pos + size > self.end:
            raise ParseError("serialized", "truncated at 0x%x (%d bytes)" % (self.pos, size))
        out = self.data[self.pos:self.pos + size]
        self.pos += size
        return out

    def u8(self) -> int:
        return self.take(1)[0]

    def i16(self) -> int:
        return struct.unpack(self.endian + "h", self.take(2))[0]

    def i32(self) -> int:
        return struct.unpack(self.endian + "i", self.take(4))[0]

    def u32(self) -> int:
        return struct.unpack(self.endian + "I", self.take(4))[0]

    def i64(self) -> int:
        return struct.unpack(self.endian + "q", self.take(8))[0]

    def cstring(self, max_len: int = 4096) -> str:
        out = bytearray()
        for _ in range(max_len):
            b = self.take(1)[0]
            if b == 0:
                return out.decode("utf-8", errors="replace")
            out.append(b)
        raise ParseError("serialized", "unterminated string")


def _read_type_tree(r: _SReader, version: int) -> List[Dict[str, Any]]:
    node_count = r.i32()
    string_buffer_size = r.i32()
    if node_count < 0 or node_count > 1000000:
        raise ParseError("serialized", "implausible type-tree node count %d" % node_count)
    if string_buffer_size < 0 or string_buffer_size > 64 * 1024 * 1024:
        raise ParseError("serialized", "implausible type-tree string buffer %d" % string_buffer_size)
    nodes: List[Dict[str, Any]] = []
    for _ in range(node_count):
        node_type = r.cstring()
        node_name = r.cstring()
        byte_size = r.i32()
        index = r.i32() if version >= 16 else 0
        is_array = r.i32()
        tree_version = r.i32()
        meta_flag = r.i32() if version >= 12 else 0
        type_str_offset = r.u32() if version >= 19 else 0
        ref_type_hash = r.u32() if version >= 21 else 0
        nodes.append({"type": node_type, "name": node_name, "byte_size": byte_size, "index": index,
                      "is_array": is_array, "version": tree_version, "meta_flag": meta_flag,
                      "type_str_offset": type_str_offset, "ref_type_hash": ref_type_hash})
    if string_buffer_size:
        r.take(string_buffer_size)
    return nodes


def parse_serialized_file(data: bytes) -> Dict[str, Any]:
    """Parse a Unity SerializedFile header, type table and object table."""
    if len(data) < 20:
        raise ParseError("serialized", "truncated SerializedFile header")
    metadata_size32 = read_u32_le(data, 0)
    file_size32 = read_u32_le(data, 4)
    version = read_u32_le(data, 8)
    data_offset32 = read_u32_le(data, 12)
    endian_byte = data[16] if len(data) > 16 else 0
    endian = ">" if endian_byte == 1 else "<"
    metadata_size = metadata_size32
    file_size = file_size32
    data_offset = data_offset32
    if version >= 22:
        _need(data, 20, 32, "serialized")
        metadata_size = struct.unpack_from("<Q", data, 20)[0]
        file_size = struct.unpack_from("<Q", data, 28)[0]
        data_offset = struct.unpack_from("<Q", data, 36)[0]
    if metadata_size <= 0 or metadata_size > SERIALIZED_MAX_METADATA:
        raise ParseError("serialized", "implausible metadata_size %d" % metadata_size)
    if data_offset <= 0 or data_offset > len(data):
        raise ParseError("serialized", "data_offset 0x%x outside file" % data_offset)
    meta_start = data_offset - metadata_size
    if meta_start < 0:
        raise ParseError("serialized", "metadata/data overlap")
    r = _SReader(data, meta_start, endian, data_offset)
    unity_version = r.cstring(128)
    if not re.match(r"^\d{4}\.\d+\.\d+", unity_version):
        raise ParseError("serialized", "unrecognized unity_version %r" % unity_version)
    target_platform = r.i32()
    enable_type_tree = (r.u8() != 0) if version >= 13 else True
    type_count = r.i32()
    if type_count < 0 or type_count > 1000000:
        raise ParseError("serialized", "implausible type count %d" % type_count)
    types: List[Dict[str, Any]] = []
    for _ in range(type_count):
        class_id = r.i32()
        is_stripped = bool(r.u8()) if version >= 16 else False
        script_type_index = r.i16() if version >= 17 else -1
        if script_type_index >= 0:
            r.take(16)
        nodes = _read_type_tree(r, version) if enable_type_tree else []
        types.append({"class_id": class_id, "is_stripped": is_stripped,
                      "script_type_index": script_type_index, "nodes": nodes})
    object_count = r.i32()
    if object_count < 0 or object_count > 2000000:
        raise ParseError("serialized", "implausible object count %d" % object_count)
    objects: List[Dict[str, Any]] = []
    for idx in range(object_count):
        rec_start = r.pos
        path_id = r.i64()
        if version >= 22:
            byte_start = r.i64()
            byte_start_pos = rec_start + 8
            byte_start_width = 8
        else:
            byte_start = r.u32()
            byte_start_pos = rec_start + 8
            byte_start_width = 4
        byte_size_pos = r.pos
        byte_size = r.u32()
        type_id = r.i32()
        if version < 16:
            r.take(2)
        if version < 17:
            r.take(1)
        objects.append({
            "index": idx, "path_id": path_id, "byte_start": byte_start, "byte_size": byte_size,
            "type_id": type_id, "record_start": rec_start, "byte_start_pos": byte_start_pos,
            "byte_start_width": byte_start_width, "byte_size_pos": byte_size_pos,
        })
    for obj in objects:
        obj["absolute_offset"] = int(data_offset) + int(obj["byte_start"])
        if obj["absolute_offset"] + obj["byte_size"] > len(data):
            raise ParseError("serialized", "object %d exceeds file" % obj["index"])
        if 0 <= obj["type_id"] < len(types):
            obj["class_id"] = types[obj["type_id"]]["class_id"]
        else:
            obj["class_id"] = None
    return {
        "version": version, "endian": endian, "metadata_size": metadata_size,
        "file_size": file_size, "data_offset": data_offset, "metadata_start": meta_start,
        "unity_version": unity_version, "target_platform": target_platform,
        "enable_type_tree": enable_type_tree, "types": types, "objects": objects,
        "metadata_end": data_offset,
    }


def parse_asset_bundle_object(blob: bytes, endian: str = "<") -> Dict[str, Any]:
    """Parse an AssetBundle object payload from m_Name through m_Dependencies."""
    pos = 0
    name, pos = read_lp_string(blob, pos, endian)
    if pos + 4 > len(blob):
        raise ParseError("alias", "AssetBundle preload table truncated")
    preload_count = struct.unpack_from(endian + "i", blob, pos)[0]
    pos += 4
    if preload_count < 0 or preload_count > 1000000:
        raise ParseError("alias", "implausible preload count %d" % preload_count)
    preload_pos = pos
    pos += preload_count * 12
    if pos + 4 > len(blob):
        raise ParseError("alias", "AssetBundle container count truncated")
    container_count_pos = pos
    container_count = struct.unpack_from(endian + "i", blob, pos)[0]
    pos += 4
    if container_count < 0 or container_count > 1000000:
        raise ParseError("alias", "implausible container count %d" % container_count)
    entries_start = pos
    containers: List[Dict[str, Any]] = []
    for _ in range(container_count):
        asset_path, pos = read_lp_string(blob, pos, endian)
        if pos + 20 > len(blob):
            raise ParseError("alias", "container AssetInfo truncated")
        preload_index, preload_size, file_id, path_id = struct.unpack_from(endian + "iiIq", blob, pos)
        pos += 20
        containers.append({"asset_path": asset_path, "preload_index": preload_index,
                           "preload_size": preload_size, "file_id": file_id, "path_id": path_id})
    entries_end = pos
    if pos + 20 + 4 > len(blob):
        raise ParseError("alias", "AssetBundle main asset/runtime fields truncated")
    pos += 20
    runtime_compatibility = struct.unpack_from(endian + "i", blob, pos)[0]
    pos += 4
    name_field_pos = pos
    bundle_name, pos = read_lp_string(blob, pos, endian)
    name_field_len = pos - name_field_pos
    variant_pos = pos
    bundle_variant, pos = read_lp_string(blob, pos, endian)
    variant_field_len = pos - variant_pos
    if pos + 4 > len(blob):
        raise ParseError("alias", "AssetBundle dependency vector truncated")
    dep_count = struct.unpack_from(endian + "i", blob, pos)[0]
    pos += 4
    if dep_count < 0 or dep_count > 1000000:
        raise ParseError("alias", "implausible dependency count %d" % dep_count)
    deps: List[str] = []
    for _ in range(dep_count):
        dep, pos = read_lp_string(blob, pos, endian)
        deps.append(dep)
    return {
        "name": name, "preload_count": preload_count, "preload_pos": preload_pos,
        "container_count": container_count, "container_count_pos": container_count_pos,
        "containers": containers, "entries_start": entries_start, "entries_end": entries_end,
        "runtime_compatibility": runtime_compatibility,
        "assetbundle_name": bundle_name, "assetbundle_name_pos": name_field_pos,
        "assetbundle_name_len": name_field_len, "assetbundle_variant": bundle_variant,
        "variant_pos": variant_pos, "variant_len": variant_field_len,
        "dependencies": deps, "parsed_size": pos,
    }


def find_asset_bundle(serialized: Dict[str, Any], data: bytes) -> Optional[Dict[str, Any]]:
    """Locate the AssetBundle pathID 1 object and parse its payload."""
    for obj in serialized["objects"]:
        if obj.get("class_id") != ASSET_BUNDLE_CLASS_ID or int(obj["path_id"]) != 1:
            continue
        start = int(obj["absolute_offset"])
        blob = data[start:start + int(obj["byte_size"])]
        try:
            parsed = parse_asset_bundle_object(blob, serialized["endian"])
        except ParseError:
            continue
        parsed["object"] = obj
        parsed["blob_offset"] = start
        return parsed
    return None


def serialized_bundle_info(data: bytes) -> Dict[str, Any]:
    """Return a JSON-safe SerializedFile summary with AssetBundle details when present."""
    sf = parse_serialized_file(data)
    ab = find_asset_bundle(sf, data)
    report: Dict[str, Any] = {
        "version": sf["version"], "unity_version": sf["unity_version"],
        "endian": "big" if sf["endian"] == ">" else "little",
        "metadata_size": sf["metadata_size"], "data_offset": sf["data_offset"],
        "type_count": len(sf["types"]), "object_count": len(sf["objects"]),
        "enable_type_tree": sf["enable_type_tree"],
        "objects": [{"path_id": o["path_id"], "class_id": o.get("class_id"),
                     "byte_start": o["byte_start"], "byte_size": o["byte_size"]}
                    for o in sf["objects"]],
        "asset_bundle": None,
    }
    if ab is not None:
        report["asset_bundle"] = {
            "name": ab["name"], "assetbundle_name": ab["assetbundle_name"],
            "assetbundle_variant": ab["assetbundle_variant"],
            "container_count": ab["container_count"],
            "containers": ab["containers"], "dependencies": ab["dependencies"],
        }
    return report


def _patch_object_table(buf: bytearray, serialized: Dict[str, Any], target_index: int, delta: int) -> None:
    endian = serialized["endian"]
    target = next(o for o in serialized["objects"] if o["index"] == target_index)
    target_start = int(target["byte_start"])
    for obj in serialized["objects"]:
        if obj["index"] == target_index:
            struct.pack_into(endian + "I", buf, obj["byte_size_pos"], int(obj["byte_size"]) + delta)
        elif int(obj["byte_start"]) > target_start:
            width = "Q" if obj["byte_start_width"] == 8 else "I"
            struct.pack_into(endian + width, buf, obj["byte_start_pos"], int(obj["byte_start"]) + delta)


def _patch_file_size(buf: bytearray, serialized: Dict[str, Any], delta: int) -> None:
    if serialized["version"] >= 22:
        struct.pack_into("<Q", buf, 28, int(serialized["file_size"]) + delta)
        if len(buf) >= 8 and read_u32_le(bytes(buf), 4) <= 0xFFFFFFFF:
            try:
                struct.pack_into("<I", buf, 4, read_u32_le(bytes(buf), 4) + delta)
            except struct.error:
                pass
    else:
        struct.pack_into("<I", buf, 4, int(serialized["file_size"]) + delta)


def _serialized_edit(data: bytes, serialized: Dict[str, Any], obj_index: int,
                     rel_offset: int, remove_len: int, insert: bytes) -> bytes:
    obj = serialized["objects"][obj_index]
    abs_off = int(obj["absolute_offset"]) + rel_offset
    if abs_off < int(obj["absolute_offset"]) or abs_off + remove_len > int(obj["absolute_offset"]) + int(obj["byte_size"]):
        raise ParseError("alias", "object edit outside asset bounds")
    delta = len(insert) - remove_len
    buf = bytearray(data[:abs_off] + insert + data[abs_off + remove_len:])
    _patch_object_table(buf, serialized, obj_index, delta)
    _patch_file_size(buf, serialized, delta)
    if delta < 0:
        new_len = int(serialized["file_size"]) + delta
        if new_len <= 0 or len(buf) < new_len:
            raise ParseError("alias", "edit produced invalid file size")
    return bytes(buf)


def _find_container_object(serialized: Dict[str, Any], data: bytes) -> Tuple[int, Dict[str, Any]]:
    for obj in serialized["objects"]:
        if obj.get("class_id") != ASSET_BUNDLE_CLASS_ID or int(obj["path_id"]) != 1:
            continue
        start = int(obj["absolute_offset"])
        blob = data[start:start + int(obj["byte_size"])]
        parsed = parse_asset_bundle_object(blob, serialized["endian"])
        return int(obj["index"]), parsed
    raise ParseError("alias", "AssetBundle object (class 142, pathID 1) not found")


def alias_inject_bundle(data: bytes, aliases: Sequence[str], new_name: Optional[str] = None) -> Tuple[bytes, Dict[str, Any]]:
    """Append aliases to AssetBundle m_Container and rebuild the surrounding UnityFS bundle."""
    bundle = read_unityfs_bytes(data)
    nodes: List[Dict[str, Any]] = list(bundle["nodes"])
    blobs: List[bytes] = [node_bytes(bundle, n) for n in nodes]
    serialized_index = None
    serialized = None
    container_info = None
    object_index = None
    for i, blob in enumerate(blobs):
        try:
            sf = parse_serialized_file(blob)
            oi, ci = _find_container_object(sf, blob)
        except ParseError:
            continue
        serialized_index = i
        serialized = sf
        container_info = ci
        object_index = oi
        break
    if serialized is None or container_info is None or object_index is None:
        raise ParseError("alias", "no SerializedFile with AssetBundle pathID 1 found")
    original_container_count = int(container_info["container_count"])
    changed: List[Dict[str, Any]] = []
    name_before = container_info["assetbundle_name"]
    if new_name is not None:
        replacement = encode_lp_string(new_name, serialized["endian"])
        rel = int(container_info["assetbundle_name_pos"])
        span = int(container_info["assetbundle_name_len"])
        old_blob = blobs[serialized_index]
        if len(replacement) == span:
            abs_off = int(serialized["data_offset"]) + int(serialized["objects"][object_index]["byte_start"]) + rel
            buf = bytearray(old_blob)
            buf[abs_off:abs_off + span] = replacement
            blobs[serialized_index] = bytes(buf)
            changed.append({"serialized_offset": abs_off, "removed": span, "inserted": len(replacement)})
        else:
            abs_off = int(serialized["data_offset"]) + int(serialized["objects"][object_index]["byte_start"]) + rel
            blobs[serialized_index] = _serialized_edit(old_blob, serialized, object_index, rel, span, replacement)
            changed.append({"serialized_offset": abs_off, "removed": span, "inserted": len(replacement)})
        serialized = parse_serialized_file(blobs[serialized_index])
        object_index, container_info = _find_container_object(serialized, blobs[serialized_index])
    existing = {item["asset_path"] for item in container_info["containers"]}
    additions: List[str] = []
    skipped: List[str] = []
    for alias in aliases:
        if not alias:
            continue
        if alias in existing:
            skipped.append(alias)
            continue
        additions.append(alias)
        existing.add(alias)
    if additions:
        entry_bytes = bytearray()
        for alias in additions:
            entry_bytes.extend(encode_lp_string(alias, serialized["endian"]))
            entry_bytes.extend(struct.pack(serialized["endian"] + "iiIq", 0, 1, 0, 1))
        obj = serialized["objects"][object_index]
        old_blob = blobs[serialized_index]
        abs_count = int(obj["absolute_offset"]) + int(container_info["container_count_pos"])
        buf = bytearray(old_blob)
        struct.pack_into(serialized["endian"] + "i", buf, abs_count,
                         original_container_count + len(additions))
        old_blob = bytes(buf)
        insert_at = int(container_info["entries_end"])
        abs_off = int(serialized["data_offset"]) + int(obj["byte_start"]) + insert_at
        blobs[serialized_index] = _serialized_edit(old_blob, serialized, object_index, insert_at, 0, bytes(entry_bytes))
        changed.append({"serialized_offset": abs_off, "removed": 0, "inserted": len(entry_bytes)})
        serialized = parse_serialized_file(blobs[serialized_index])
        object_index, container_info = _find_container_object(serialized, blobs[serialized_index])
    if int(container_info["container_count"]) != original_container_count + len(additions):
        raise ParseError("alias", "container count verification failed")
    out = build_unityfs(bundle["header"], nodes, blobs, flags=int(bundle["header"]["flags"]))
    report = {
        "original_size": len(data), "new_size": len(out),
        "format_version": bundle["header"]["format_version"],
        "compression": bundle["header"]["compression"], "repack_flags": bundle["header"]["flags"],
        "container_count_before": original_container_count,
        "container_count_after": int(container_info["container_count"]),
        "container_count_delta": len(additions),
        "aliases_added": additions, "aliases_skipped": skipped,
        "assetbundle_name_before": name_before,
        "assetbundle_name_after": container_info["assetbundle_name"],
        "changed_ranges": changed,
        "node_count": len(nodes), "serialized_node": serialized_index,
    }
    return out, report

# 22 XML/JSON
def _xml_parse(text: str, keep_comments: bool = True) -> ET.Element:
    parser = ET.XMLParser(target=ET.TreeBuilder(insert_comments=keep_comments))
    try:
        return ET.fromstring(text, parser=parser)
    except ET.ParseError as exc:
        raise ParseError("xml", str(exc)) from exc


def _strip_xml_comments(root: ET.Element) -> None:
    for parent in list(root.iter()):
        for child in list(parent):
            if child.tag is ET.Comment:
                parent.remove(child)


def xml_pretty(text: str, keep_comments: bool = True) -> str:
    """Pretty-print XML with two-space indentation, preserving comments and attribute order."""
    root = _xml_parse(text, keep_comments=keep_comments)
    if not keep_comments:
        _strip_xml_comments(root)
    try:
        ET.indent(root, space="  ")
    except AttributeError:
        pass
    body = ET.tostring(root, encoding="unicode")
    return '<?xml version="1.0" encoding="utf-8"?>\n' + body + "\n"


def _xml_path(parent: str, element: ET.Element, index: int, total: int) -> str:
    suffix = ("[%d]" % index) if total > 1 else ""
    return "%s/%s%s" % (parent.rstrip("/"), element.tag, suffix)


def xml_diff(a: str, b: str) -> List[Dict[str, Any]]:
    """Return element-path differences for attributes, text, tags and children."""
    ra = _xml_parse(a, keep_comments=False)
    rb = _xml_parse(b, keep_comments=False)
    out: List[Dict[str, Any]] = []

    def walk(ea: Optional[ET.Element], eb: Optional[ET.Element], path: str) -> None:
        if ea is None and eb is not None:
            out.append({"path": path, "change": "added", "tag": eb.tag,
                        "text": (eb.text or "").strip()})
            for child in list(eb):
                walk(None, child, path + "/" + child.tag)
            return
        if eb is None and ea is not None:
            out.append({"path": path, "change": "removed", "tag": ea.tag,
                        "text": (ea.text or "").strip()})
            for child in list(ea):
                walk(child, None, path + "/" + child.tag)
            return
        if ea is None or eb is None:
            return
        if ea.tag != eb.tag:
            out.append({"path": path, "change": "tag", "from": ea.tag, "to": eb.tag})
        ta = (ea.text or "").strip()
        tb = (eb.text or "").strip()
        if ta != tb:
            out.append({"path": path, "change": "text", "from": ta, "to": tb})
        keys = set(ea.attrib) | set(eb.attrib)
        for key in sorted(keys):
            if ea.attrib.get(key) != eb.attrib.get(key):
                out.append({"path": path, "change": "attr", "attr": key,
                            "from": ea.attrib.get(key), "to": eb.attrib.get(key)})
        ca = list(ea)
        cb = list(eb)
        key_attr = "name" if (any("name" in c.attrib for c in ca + cb)) else (
            "id" if any("id" in c.attrib for c in ca + cb) else None)
        map_a: Dict[Any, ET.Element] = {}
        map_b: Dict[Any, ET.Element] = {}
        for i, child in enumerate(ca):
            map_a[(child.tag, child.attrib.get(key_attr) if key_attr else i)] = child
        for i, child in enumerate(cb):
            map_b[(child.tag, child.attrib.get(key_attr) if key_attr else i)] = child
        for key in list(map_a.keys()) + [k for k in map_b.keys() if k not in map_a]:
            child_a = map_a.get(key)
            child_b = map_b.get(key)
            tag_for_path = key[0] if isinstance(key, tuple) else "child"
            total_a = sum(1 for c in ca if c.tag == tag_for_path)
            total_b = sum(1 for c in cb if c.tag == tag_for_path)
            child_path = "%s/%s" % (path.rstrip("/"), tag_for_path)
            if total_a > 1 or total_b > 1:
                child_path += "[%s]" % (key[1] if isinstance(key, tuple) and key_attr else "?")
            walk(child_a, child_b, child_path)

    walk(ra, rb, "/" + ra.tag)
    return out


def _xml_children_key(element: ET.Element) -> List[Tuple[str, str]]:
    return [(c.tag, c.attrib.get("name") or c.attrib.get("id") or "") for c in list(element)]


def xml_merge(a: str, b: str) -> str:
    """Merge two XML documents; right-hand attrs/text win, children union by tag+key."""
    ra = _xml_parse(a, keep_comments=False)
    rb = _xml_parse(b, keep_comments=False)
    if ra.tag != rb.tag:
        raise ParseError("xml", "root tag mismatch: %s vs %s" % (ra.tag, rb.tag))

    def merge(ea: ET.Element, eb: ET.Element) -> None:
        for key, value in eb.attrib.items():
            ea.set(key, value)
        if eb.text and eb.text.strip():
            ea.text = eb.text
        children = list(ea)
        for cb in list(eb):
            key_val = cb.attrib.get("name") or cb.attrib.get("id")
            match = None
            for ca in children:
                if ca.tag == cb.tag:
                    if key_val is None or (ca.attrib.get("name") or ca.attrib.get("id")) == key_val:
                        match = ca
                        break
            if match is None:
                ea.append(cb)
                children.append(cb)
            else:
                merge(match, cb)

    merge(ra, rb)
    try:
        ET.indent(ra, space="  ")
    except AttributeError:
        pass
    return '<?xml version="1.0" encoding="utf-8"?>\n' + ET.tostring(ra, encoding="unicode") + "\n"


def xml_validate(text: str, schema: Optional[str] = None) -> Tuple[bool, str]:
    """Validate XML well-formedness and optionally a root-name XSD stub."""
    try:
        root = ET.fromstring(text)
    except ET.ParseError as exc:
        return False, "not well-formed: %s" % exc
    if schema is None:
        return True, "well-formed"
    try:
        sroot = ET.fromstring(schema)
    except ET.ParseError as exc:
        return False, "schema is not well-formed: %s" % exc
    candidates = []
    for el in sroot.iter():
        if el.tag.endswith("element") and "name" in el.attrib:
            candidates.append(el.attrib["name"])
            break
    if not candidates:
        return False, "schema stub has no root xs:element name"
    expected = candidates[0]
    if root.tag != expected:
        return False, "root tag %s != schema root %s" % (root.tag, expected)
    return True, "well-formed; schema stub root matched"


def json_pretty(text: str) -> str:
    """Pretty-print JSON with two-space indentation."""
    try:
        obj = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ParseError("json", str(exc)) from exc
    return json.dumps(obj, indent=2, ensure_ascii=False) + "\n"


def json_diff(a: str, b: str) -> List[Dict[str, Any]]:
    """Return path-based differences between two JSON documents."""
    try:
        oa = json.loads(a)
        ob = json.loads(b)
    except json.JSONDecodeError as exc:
        raise ParseError("json", str(exc)) from exc
    diffs: List[Dict[str, Any]] = []

    def walk(va: Any, vb: Any, path: str) -> None:
        if type(va) is not type(vb):
            diffs.append({"path": path, "change": "type", "from": type(va).__name__,
                          "to": type(vb).__name__, "from_value": va, "to_value": vb})
            return
        if isinstance(va, dict):
            for key in sorted(set(va) | set(vb)):
                child = "%s.%s" % (path, key)
                if key not in va:
                    diffs.append({"path": child, "change": "added", "value": vb[key]})
                elif key not in vb:
                    diffs.append({"path": child, "change": "removed", "value": va[key]})
                else:
                    walk(va[key], vb[key], child)
        elif isinstance(va, list):
            if va != vb:
                diffs.append({"path": path, "change": "list", "from": va, "to": vb})
        elif va != vb:
            diffs.append({"path": path, "change": "value", "from": va, "to": vb})

    walk(oa, ob, "$")
    return diffs


def json_merge(a: str, b: str) -> str:
    """Merge JSON documents; right wins scalars, objects recurse and arrays union."""
    try:
        oa = json.loads(a)
        ob = json.loads(b)
    except json.JSONDecodeError as exc:
        raise ParseError("json", str(exc)) from exc

    def merge(x: Any, y: Any) -> Any:
        if isinstance(x, dict) and isinstance(y, dict):
            result = dict(x)
            for key, value in y.items():
                result[key] = merge(result[key], value) if key in result else value
            return result
        if isinstance(x, list) and isinstance(y, list):
            result = list(x)
            for value in y:
                if value not in result:
                    result.append(value)
            return result
        return y

    return json.dumps(merge(oa, ob), indent=2, ensure_ascii=False) + "\n"


def json_validate(text: str, schema: Optional[str] = None) -> Tuple[bool, str]:
    """Validate JSON syntax and an optional required/type schema stub."""
    try:
        obj = json.loads(text)
    except json.JSONDecodeError as exc:
        return False, "invalid JSON: %s" % exc
    if schema is None:
        return True, "valid JSON"
    try:
        spec = json.loads(schema)
    except json.JSONDecodeError as exc:
        return False, "schema stub is invalid JSON: %s" % exc
    if not isinstance(spec, dict):
        return False, "schema stub must be an object"
    required = spec.get("required", [])
    if isinstance(required, list):
        if not isinstance(obj, dict):
            return False, "schema requires object but root is %s" % type(obj).__name__
        missing = [key for key in required if key not in obj]
        if missing:
            return False, "missing required keys: %s" % ", ".join(str(k) for k in missing)
    expected = spec.get("type")
    if isinstance(expected, str):
        mapping = {"object": dict, "array": list, "string": str, "number": (int, float),
                   "integer": int, "boolean": bool, "null": type(None)}
        py_type = mapping.get(expected)
        if py_type is not None and not isinstance(obj, py_type):
            return False, "root type %s != schema type %s" % (type(obj).__name__, expected)
    return True, "valid JSON; schema stub matched"

# 23 asset index
ASSET_EXTENSIONS = {
    ".unity3d": "unityfs", ".bundle": "unityfs", ".assets": "unityfs", ".ab": "unityfs",
    ".png": "png", ".jpg": "jpeg", ".jpeg": "jpeg", ".webp": "webp", ".ogg": "ogg",
    ".wav": "wav", ".mp3": "mp3", ".xml": "xml", ".json": "json", ".txt": "text",
    ".csv": "text", ".dat": "binary", ".bin": "binary", ".so": "elf",
}


def sniff_asset_format(name: str, head: bytes) -> str:
    """Identify a game asset by magic bytes, falling back to its extension."""
    if head.startswith(UNITYFS_MAGIC):
        return "unityfs"
    if head.startswith(b"UnityWeb"):
        return "unityweb"
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if head.startswith(b"\xff\xd8\xff"):
        return "jpeg"
    if head.startswith(b"OggS"):
        return "ogg"
    if head.startswith(b"RIFF") and head[8:12] == b"WAVE":
        return "wav"
    if head.startswith(b"PK\x03\x04"):
        return "zip"
    if head.startswith(b"%PDF"):
        return "pdf"
    if head.startswith(ELF_MAGIC):
        return "elf"
    text_head = head.lstrip(b"\xef\xbb\xbf \t\r\n")
    if text_head.startswith(b"<?xml") or (text_head.startswith(b"<") and b">" in text_head):
        return "xml"
    if text_head.startswith(b"{") or text_head.startswith(b"["):
        return "json"
    return ASSET_EXTENSIONS.get(Path(name).suffix.lower(), "binary")


def _resolve_asset_roots(root: Union[str, Path]) -> Tuple[Path, Path]:
    """Return (files_root, assets_root) for a files dir, dragon2017 dir or assets dir."""
    base = Path(root)
    if not base.exists():
        raise ToolIOError("assets", "not found: %s" % base)
    if not base.is_dir():
        raise ToolIOError("assets", "expected a directory: %s" % base)
    if (base / "dragon2017" / "assets").is_dir():
        return base, base / "dragon2017" / "assets"
    if base.name == "dragon2017" and (base / "assets").is_dir():
        return base.parent, base / "assets"
    if base.name == "assets":
        files_root = base.parent.parent if base.parent.name == "dragon2017" else base.parent
        return files_root, base
    if (base / "assets").is_dir():
        return base, base / "assets"
    return base.parent if base.name == "dragon2017" else base, base


def _resolve_mini_patch(files_root: Path, assets_root: Path,
                        override: Optional[Union[str, Path]]) -> Optional[Path]:
    """Find the mini_patch tree that can shadow the assets tree."""
    if override:
        p = Path(override)
        if not p.exists():
            raise ToolIOError("assets", "mini_patch not found: %s" % p)
        if not p.is_dir():
            raise ToolIOError("assets", "mini_patch is not a directory: %s" % p)
        return p
    seen: List[Path] = []
    for candidate in (files_root / "mini_patch", assets_root.parent / "mini_patch",
                      files_root.parent / "mini_patch", assets_root / "mini_patch"):
        resolved = candidate
        if resolved in seen:
            continue
        seen.append(resolved)
        if resolved.is_dir():
            return resolved
    return None


def _mini_patch_lookup(mini_patch: Optional[Path], rel: str) -> Optional[Path]:
    """Return the mini_patch file shadowing a relative asset path, if any."""
    if mini_patch is None:
        return None
    candidates = [mini_patch / "assets" / rel, mini_patch / rel]
    if rel.startswith("assets/"):
        candidates.append(mini_patch / rel[len("assets/"):])
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return None


def build_asset_index(root: Union[str, Path], mini_patch: Optional[Union[str, Path]] = None) -> Dict[str, Any]:
    """Walk dragon2017/assets, hash every file, sniff formats and detect mini_patch shadowing."""
    files_root, assets_root = _resolve_asset_roots(root)
    patch_root = _resolve_mini_patch(files_root, assets_root, mini_patch)
    entries: List[Dict[str, Any]] = []
    format_counts: Dict[str, int] = {}
    extension_counts: Dict[str, int] = {}
    total_size = 0
    for path in sorted(assets_root.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(assets_root).as_posix()
        size = path.stat().st_size
        head = b""
        try:
            with open(path, "rb") as fh:
                head = fh.read(64)
        except OSError as exc:
            raise ToolIOError("assets", "cannot read %s: %s" % (path, exc))
        fmt = sniff_asset_format(path.name, head)
        digest = sha256_file(path)
        shadow = _mini_patch_lookup(patch_root, rel)
        shadow_info = None
        if shadow is not None:
            shadow_digest = sha256_file(shadow)
            shadow_info = {
                "path": str(shadow), "sha256": shadow_digest,
                "size": shadow.stat().st_size, "identical": shadow_digest == digest,
            }
        entry = {
            "relative_path": rel, "path": str(path), "size": size, "sha256": digest,
            "format": fmt, "extension": path.suffix.lower() or "(none)",
            "shadowed_by_mini_patch": shadow_info is not None, "mini_patch": shadow_info,
        }
        entries.append(entry)
        total_size += size
        format_counts[fmt] = format_counts.get(fmt, 0) + 1
        extension_counts[entry["extension"]] = extension_counts.get(entry["extension"], 0) + 1

    by_hash: Dict[str, List[str]] = {}
    for entry in entries:
        by_hash.setdefault(entry["sha256"], []).append(entry["relative_path"])
    duplicates = [{"sha256": digest, "files": paths} for digest, paths in by_hash.items() if len(paths) > 1]
    shadowed = [entry for entry in entries if entry["shadowed_by_mini_patch"]]
    largest = sorted(entries, key=lambda item: item["size"], reverse=True)[:15]
    return {
        "files_root": str(files_root), "assets_root": str(assets_root),
        "mini_patch_root": str(patch_root) if patch_root else None,
        "generated_by": "%s %s" % (TOOL_NAME, TOOL_VERSION),
        "file_count": len(entries), "total_size": total_size,
        "format_counts": dict(sorted(format_counts.items())),
        "extension_counts": dict(sorted(extension_counts.items())),
        "shadowed_count": len(shadowed),
        "shadowed": [{k: v for k, v in entry.items() if k in ("relative_path", "path", "sha256", "mini_patch")}
                     for entry in shadowed],
        "duplicate_group_count": len(duplicates), "duplicates": duplicates,
        "largest": [{"relative_path": entry["relative_path"], "size": entry["size"]} for entry in largest],
        "entries": entries,
    }


def asset_index_csv(index: Dict[str, Any]) -> str:
    """Render an asset index as CSV."""
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["relative_path", "size", "sha256", "format", "extension", "shadowed_by_mini_patch"])
    for entry in index["entries"]:
        writer.writerow([entry["relative_path"], entry["size"], entry["sha256"], entry["format"],
                         entry["extension"], "yes" if entry["shadowed_by_mini_patch"] else "no"])
    return buf.getvalue()


def format_asset_summary(index: Dict[str, Any]) -> str:
    """Render the console summary for an asset index."""
    lines = ["=== ASSET INDEX ===",
             "assets_root=%s" % index["assets_root"],
             "mini_patch=%s" % (index["mini_patch_root"] or "(none)"),
             "files=%d total=%s" % (index["file_count"], human_size(index["total_size"])),
             "formats: " + ", ".join("%s=%d" % item for item in index["format_counts"].items()),
             "shadowed_by_mini_patch=%d" % index["shadowed_count"],
             "duplicate_groups=%d" % index["duplicate_group_count"]]
    for entry in index["largest"][:5]:
        lines.append("  largest %s (%s)" % (entry["relative_path"], human_size(entry["size"])))
    return "\n".join(lines)


# 24 skin engine
HERO_MAP_DEFAULT = {
    "Fanny": "hero_fanny", "Ling": "hero_pofa", "Gusion": "hero_Gusin", "Hayabusa": "hero_ninja",
    "Lancelot": "hero_lancelot", "Nolan": "hero_NolanOsborne", "Aamon": "hero_Aamon", "Saber": "hero_assassin",
    "Julian": "hero_julian", "Kagura": "hero_kagura", "Lunox": "hero_balancemagic", "Harith": "hero_moshushi",
    "Cecilion": "hero_couplemage", "Xavier": "hero_xavier", "Nana": "hero_nana", "Chang'e": "hero_change",
    "Vexana": "hero_Vexana", "Tigreal": "hero_warrior", "Franco": "hero_franco", "Khufra": "hero_munaiyi",
    "Atlas": "hero_atelasi", "Johnson": "hero_johnson", "Gatotkaca": "hero_gatot", "Akai": "hero_xiongmao",
    "Granger": "hero_mike", "Layla": "hero_shooter", "Moskov": "hero_Moskov", "Claude": "hero_claude",
    "Miya": "hero_gongjianshou", "Karrie": "hero_feilun", "Beatrix": "hero_chargingshooter", "Brody": "hero_feiden",
}

SKIN_ROLES = ("base mesh", "skin mesh", "_add", "_high_add", "_shadow_add", "_shadow_high_add",
              "ui", "audio", "document")
SHADOW_ROLES = ("_shadow_add", "_shadow_high_add")


def load_hero_map(override_path: Optional[Union[str, Path]] = None) -> Dict[str, str]:
    """Load the default hero map and apply an optional JSON override file."""
    mapping = dict(HERO_MAP_DEFAULT)
    if override_path:
        path = require_file(override_path, "skin")
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise ParseError("skin", "invalid hero map %s: %s" % (path, exc))
        if not isinstance(raw, dict):
            raise ParseError("skin", "hero map must be a JSON object")
        for key, value in raw.items():
            if not isinstance(key, str) or not isinstance(value, str):
                raise ParseError("skin", "hero map keys and values must be strings")
            mapping[key] = value
    return mapping


def resolve_hero_prefix(hero: Optional[str], override_path: Optional[Union[str, Path]] = None) -> str:
    """Resolve a hero name to its asset prefix, accepting an explicit hero_* prefix."""
    if not hero or not hero.strip():
        raise UsageError("skin", "provide --hero NAME or --prefix PREFIX")
    candidate = hero.strip()
    if candidate.startswith("hero_") and re.fullmatch(r"[A-Za-z0-9_]+", candidate):
        return candidate
    mapping = load_hero_map(override_path)
    lookup = {name.lower(): prefix for name, prefix in mapping.items()}
    prefix = lookup.get(candidate.lower())
    if prefix is None:
        examples = ", ".join(sorted(mapping)[:6])
        raise UsageError("skin", "unknown hero %r (try: %s; override with --hero-map)" % (candidate, examples))
    if not re.fullmatch(r"[A-Za-z0-9_]+", prefix):
        raise ParseError("skin", "hero map produced invalid prefix %r" % prefix)
    return prefix


def classify_skin_role(name: str) -> str:
    """Classify an asset filename into a skin role using suffix precedence."""
    low = name.lower()
    if "_shadow_high_add" in low:
        return "_shadow_high_add"
    if "_shadow_add" in low:
        return "_shadow_add"
    if "_high_add" in low:
        return "_high_add"
    if "_add" in low:
        return "_add"
    if low.endswith(".ogg") or low.endswith(".wav") or low.endswith(".mp3"):
        return "audio"
    if low.endswith(".xml") or low.endswith(".json") or low.endswith(".txt"):
        return "document"
    if "ui" in low:
        return "ui"
    return "skin mesh" if "skin" in low else "base mesh"


def _skin_cache_integrity(target: Path) -> Optional[Dict[str, Any]]:
    """Hash a nearby cache tree and flag empty, stale and duplicate files."""
    candidates = [target / "cache", target.parent / "cache", target.parent.parent / "cache"]
    cache_root = next((path for path in candidates if path.is_dir()), None)
    if cache_root is None:
        return None
    files: List[Dict[str, Any]] = []
    zero: List[str] = []
    by_hash: Dict[str, List[str]] = {}
    for path in sorted(cache_root.rglob("*")):
        if not path.is_file():
            continue
        size = path.stat().st_size
        entry = {"path": str(path), "size": size}
        if size == 0:
            zero.append(str(path))
        files.append(entry)
        by_hash.setdefault(sha256_file(path), []).append(str(path))
    duplicates = [paths for paths in by_hash.values() if len(paths) > 1]
    return {
        "cache_root": str(cache_root), "file_count": len(files),
        "total_size": sum(item["size"] for item in files),
        "zero_byte_count": len(zero), "zero_byte": zero[:20],
        "duplicate_group_count": len(duplicates), "duplicate_groups": duplicates[:20],
        "healthy": not zero and not duplicates,
    }


def _skin_mini_patch_root(target: Path, override: Optional[Union[str, Path]]) -> Optional[Path]:
    """Choose where mini_patch mirrors should live when sync is requested."""
    if override:
        root = Path(override)
        root.mkdir(parents=True, exist_ok=True)
        return root
    for candidate in (target / "mini_patch", target.parent / "mini_patch",
                      target.parent.parent / "mini_patch"):
        if candidate.is_dir():
            return candidate
    if target.name == "assets":
        root = (target.parent.parent if target.parent.name == "dragon2017" else target.parent) / "mini_patch"
        return root
    return target.parent / "mini_patch"


def _skin_mirror_path(mini_root: Path, rel: str) -> Path:
    """Map an asset-relative path onto the mini_patch layout (assets/... preferred)."""
    existing = mini_root / rel
    if existing.exists():
        return existing
    return mini_root / "assets" / rel


def skin_plan(source: Union[str, Path], target: Union[str, Path], prefix: str,
              hero_map: Optional[Union[str, Path]] = None,
              sync_mini_patch: bool = False,
              mini_patch_root: Optional[Union[str, Path]] = None) -> Dict[str, Any]:
    """Build a deterministic skin swap plan with roles, risks and mini_patch mirrors."""
    src = Path(source)
    dst_root = Path(target)
    if not src.exists():
        raise ToolIOError("skin", "source not found: %s" % src)
    if not dst_root.is_dir():
        raise ToolIOError("skin", "target is not a directory: %s" % dst_root)
    if not prefix or not re.fullmatch(r"[A-Za-z0-9_]+", prefix):
        raise UsageError("skin", "invalid prefix %r (expected [A-Za-z0-9_]+)" % prefix)
    src_root = src if src.is_dir() else src.parent
    source_files = [path for path in sorted(src.rglob("*")) if path.is_file()] if src.is_dir() else [src]
    if not source_files:
        raise ToolIOError("skin", "source contains no files: %s" % src)
    resolved_target = dst_root.resolve()
    mini_root = _skin_mini_patch_root(dst_root, mini_patch_root) if sync_mini_patch else None
    actions: List[Dict[str, Any]] = []
    risks: List[Dict[str, str]] = []
    unmatched: List[str] = []
    base_mesh_present = False
    shadow_present = False
    for path in source_files:
        rel_path = path.relative_to(src_root) if src.is_dir() else Path(path.name)
        rel = rel_path.as_posix()
        destination = dst_root / rel_path
        try:
            destination.resolve().relative_to(resolved_target)
        except ValueError:
            raise UsageError("skin", "source path escapes target: %s" % rel)
        role = classify_skin_role(path.name)
        if role == "base mesh":
            base_mesh_present = True
        if role in SHADOW_ROLES:
            shadow_present = True
        if not path.name.lower().startswith(prefix.lower()):
            unmatched.append(rel)
        if path.stat().st_size == 0:
            risks.append({"kind": "empty-source", "path": rel, "detail": "source file is zero bytes"})
        existing = destination if destination.exists() else None
        action = "create"
        target_sha = None
        source_sha = sha256_file(path)
        if existing is not None:
            target_sha = sha256_file(existing)
            action = "identical" if target_sha == source_sha else "replace"
            if classify_skin_role(existing.name) == "base mesh" and role in SHADOW_ROLES:
                risks.append({"kind": "shadow-over-base", "path": rel,
                              "detail": "shadow bundle would overwrite a base mesh at the destination"})
        mirrors: List[str] = []
        if mini_root is not None:
            mirrors.append(str(_skin_mirror_path(mini_root, rel)))
        actions.append({
            "source": str(path), "destination": str(destination), "relative_path": rel,
            "role": role, "size": path.stat().st_size, "source_sha256": source_sha,
            "target_sha256": target_sha, "action": action, "mirrors": mirrors,
        })
    if unmatched:
        risks.append({"kind": "prefix-mismatch", "path": "%d file(s)" % len(unmatched),
                      "detail": "names not prefixed with %s: %s" % (prefix, ", ".join(unmatched[:8]))})
    if not base_mesh_present:
        risks.append({"kind": "fallback-sphere",
                      "detail": "source has no base mesh; the game may render a fallback sphere"})
    if shadow_present and not any(action["role"] == "_add" for action in actions):
        risks.append({"kind": "shadow-without-add",
                      "detail": "shadow bundles were supplied without matching _add meshes"})
    return {
        "generated_by": "%s %s" % (TOOL_NAME, TOOL_VERSION),
        "prefix": prefix, "source": str(src), "target": str(dst_root),
        "source_file_count": len(actions), "base_mesh_present": base_mesh_present,
        "mini_patch_root": str(mini_root) if mini_root else None,
        "actions": actions, "risks": risks,
        "cache": _skin_cache_integrity(dst_root),
        "hero_map_override": str(hero_map) if hero_map else None,
    }


def _emit_restore_script(manifest: Dict[str, Any], path: Path) -> Path:
    """Write a standalone restore.py that reverses a skin manifest."""
    source = '''#!/usr/bin/env python3
"""Restore files changed by shitsuke_toolz skin --apply."""
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
MANIFEST = HERE / "skinswap-manifest.json"


def atomic_write_bytes(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".restore.tmp")
    tmp.write_bytes(data)
    tmp.replace(path)


def main():
    try:
        manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        print("cannot read %s: %s" % (MANIFEST, exc), file=sys.stderr)
        return 2
    errors = []
    restored = 0
    removed = 0
    for entry in manifest.get("entries", []):
        target = Path(entry["path"])
        action = entry.get("action")
        try:
            if action == "create":
                if target.is_file():
                    target.unlink()
                    removed += 1
                continue
            backup = HERE / entry["backup"]
            atomic_write_bytes(target, backup.read_bytes())
            restored += 1
        except OSError as exc:
            errors.append("%s: %s" % (target, exc))
    print("restore complete: %d restored, %d removed, %d error(s)" % (restored, removed, len(errors)))
    for message in errors:
        print("  error: " + message, file=sys.stderr)
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
'''
    if manifest.get("entries") is None:
        raise UsageError("skin", "manifest has no entries")
    atomic_write(path, source.encode("utf-8"))
    ok, message = validate_python(source)
    if not ok:
        raise ParseError("skin", "generated restore.py failed validation: %s" % message)
    return path


def skin_apply(plan: Dict[str, Any], out_dir: Union[str, Path], force: bool = False,
               dry_run: bool = False) -> Dict[str, Any]:
    """Back up every existing target, apply the plan, verify hashes and emit restore.py."""
    out = Path(out_dir)
    entries: List[Dict[str, Any]] = []
    changed: List[str] = []
    created: List[str] = []
    backups_root = out / "skinswap-backup-files"
    if backups_root.exists() and any(backups_root.iterdir()) and not force:
        raise ToolIOError("skin", "backup files already exist in %s; pass --force or use a new --out" % backups_root)
    reserved: set = set()
    for action in plan["actions"]:
        if action["action"] == "identical":
            continue
        for destination in [action["destination"]] + list(action.get("mirrors", [])):
            destination_path = Path(destination)
            if str(destination_path) in reserved:
                continue
            reserved.add(str(destination_path))
            if destination_path.exists():
                data = destination_path.read_bytes()
                index = len([item for item in entries if item["action"] == "replace"])
                backup_rel = "skinswap-backup-files/%04d.bin" % index
                if not dry_run:
                    atomic_write(out / backup_rel, data)
                entries.append({
                    "path": str(destination_path), "action": "replace", "backup": backup_rel,
                    "sha256": sha256_bytes(data), "size": len(data),
                })
            else:
                entries.append({"path": str(destination_path), "action": "create",
                                "backup": None, "sha256": None, "size": 0})
    verification: List[Dict[str, Any]] = []
    for action in plan["actions"]:
        if action["action"] == "identical":
            continue
        source = Path(action["source"])
        data = source.read_bytes()
        source_hash = sha256_bytes(data)
        targets = [action["destination"]] + list(action.get("mirrors", []))
        for destination in targets:
            destination_path = Path(destination)
            if not dry_run:
                atomic_write(destination_path, data)
            verification.append({"path": str(destination_path), "sha256": source_hash,
                                 "written": not dry_run})
            if destination_path.exists() or dry_run:
                if action["destination"] == destination:
                    (created if action["action"] == "create" else changed).append(destination)
        if not dry_run:
            for destination in targets:
                actual = sha256_file(Path(destination))
                if actual != source_hash:
                    raise ToolIOError("skin", "verification failed for %s" % destination)
    manifest = {
        "tool": TOOL_NAME, "tool_version": TOOL_VERSION, "kind": "skin-swap",
        "prefix": plan["prefix"], "target": plan["target"],
        "applied": not dry_run, "entries": entries,
        "changed": changed, "created": created, "verification": verification,
    }
    written: List[str] = []
    if not dry_run:
        out.mkdir(parents=True, exist_ok=True)
        written.append(str(write_json(out / "skinswap-manifest.json", manifest)))
        written.append(str(write_json(out / "skinswap-plan.json", plan)))
        written.append(str(_emit_restore_script(manifest, out / "restore.py")))
    return {
        "applied": not dry_run, "backup_dir": str(out),
        "changed_count": len(changed), "created_count": len(created),
        "backup_count": len([entry for entry in entries if entry["action"] == "replace"]),
        "risk_count": len(plan["risks"]), "written": written,
    }


# 25 GameResAlternative resmap
RESMAP_STRIDE = 4


def find_resmap_table(path: Union[str, Path], table_name: str = "mulonggame_table_1") -> Path:
    """Find a GameResAlternative table file by exact name, including .bin/.bytes variants."""
    base = Path(path)
    if not base.exists():
        raise ToolIOError("resmap", "not found: %s" % base)
    if base.is_file():
        return base
    if not table_name or "/" in table_name or "\\" in table_name:
        raise UsageError("resmap", "invalid table name: %r" % table_name)
    names = (table_name, table_name + ".bin", table_name + ".bytes", table_name + ".dat")
    matches: List[Path] = []
    for candidate in base.rglob("*"):
        if candidate.is_file() and candidate.name in names:
            matches.append(candidate)
    if not matches:
        raise ToolIOError("resmap", "no %s under %s" % (table_name, base))
    matches.sort(key=lambda item: (len(item.parts), str(item)))
    return matches[0]


def resmap_entries(data: bytes) -> List[Dict[str, int]]:
    """Decode a GameResAlternative table as 4-byte little-endian entries."""
    if len(data) % RESMAP_STRIDE:
        raise ParseError("resmap", "table size %d is not a multiple of %d" % (len(data), RESMAP_STRIDE))
    entries: List[Dict[str, int]] = []
    for index in range(len(data) // RESMAP_STRIDE):
        entries.append({"index": index, "offset": index * RESMAP_STRIDE,
                        "value": read_u32_le(data, index * RESMAP_STRIDE)})
    return entries


def resmap_rewrite(data: bytes, index: int, skin_id: int) -> bytes:
    """Rewrite one 4-byte little-endian table entry."""
    entries = resmap_entries(data)
    if index < 0 or index >= len(entries):
        raise UsageError("resmap", "index %d outside 0..%d" % (index, len(entries) - 1))
    if skin_id < 0 or skin_id > 0xFFFFFFFF:
        raise UsageError("resmap", "skin id must fit in uint32")
    out = bytearray(data)
    struct.pack_into("<I", out, index * RESMAP_STRIDE, skin_id)
    return bytes(out)


def resmap_edit(table: Path, index: int, skin_id: int, force: bool = False,
                dry_run: bool = False) -> Dict[str, Any]:
    """Back up a table once, rewrite one entry and report before/after values."""
    data = table.read_bytes()
    entries = resmap_entries(data)
    if index < 0 or index >= len(entries):
        raise UsageError("resmap", "index %d outside 0..%d" % (index, len(entries) - 1))
    backup = table.with_name(table.name + ".bak")
    backup_created = False
    backup_reused = False
    if backup.exists():
        backup_reused = not force
    elif not dry_run:
        atomic_write(backup, data)
        backup_created = True
    new_data = resmap_rewrite(data, index, skin_id)
    if not dry_run:
        if force and backup.exists():
            atomic_write(backup, data)
            backup_created = True
            backup_reused = False
        atomic_write(table, new_data)
    return {
        "table": str(table), "index": index, "old_value": entries[index]["value"],
        "new_value": skin_id, "entry_count": len(entries),
        "backup": str(backup), "backup_created": backup_created,
        "backup_reused": backup_reused, "dry_run": dry_run,
        "changed_bytes": None if entries[index]["value"] == skin_id else RESMAP_STRIDE,
        "sha256_before": sha256_bytes(data), "sha256_after": sha256_bytes(new_data),
    }


def resmap_restore(table: Path) -> Dict[str, Any]:
    """Restore a table from its sidecar .bak file."""
    backup = table.with_name(table.name + ".bak")
    if not backup.is_file():
        raise ToolIOError("resmap", "backup not found: %s" % backup)
    data = backup.read_bytes()
    atomic_write(table, data)
    return {"path": str(table), "backup": str(backup), "restored": True,
            "size": len(data), "sha256": sha256_bytes(data)}


def resmap_report(table: Path, entries: List[Dict[str, int]]) -> Dict[str, Any]:
    """Build a compact, JSON-safe resmap report."""
    return {
        "table": str(table), "size": table.stat().st_size,
        "sha256": sha256_file(table), "entry_stride": RESMAP_STRIDE,
        "entry_count": len(entries),
        "preview": entries[:64],
        "nonzero_count": sum(1 for entry in entries if entry["value"] != 0),
        "backup_exists": table.with_name(table.name + ".bak").is_file(),
    }

# 30 templates
def _line_of(src: str, pos: int) -> int:
    return src.count("\n", 0, max(0, pos)) + 1


def _strip_c_like(src: str) -> str:
    out: List[str] = []
    i = 0
    n = len(src)
    state = "normal"
    quote = ""
    while i < n:
        ch = src[i]
        nxt = src[i + 1] if i + 1 < n else ""
        if state == "normal":
            if ch == "/" and nxt == "/":
                state = "line"
                out.extend("  ")
                i += 2
                continue
            if ch == "/" and nxt == "*":
                state = "block"
                out.extend("  ")
                i += 2
                continue
            if ch in ("'", '"', "`"):
                state = "string"
                quote = ch
                out.append(" ")
                i += 1
                continue
            out.append(ch)
            i += 1
        elif state == "line":
            out.append("\n" if ch == "\n" else " ")
            if ch == "\n":
                state = "normal"
            i += 1
        elif state == "block":
            if ch == "*" and nxt == "/":
                out.extend("  ")
                i += 2
                state = "normal"
                continue
            out.append("\n" if ch == "\n" else " ")
            i += 1
        else:
            if ch == "\\" and i + 1 < n:
                out.extend("  ")
                i += 2
                continue
            out.append("\n" if ch == "\n" else " ")
            if ch == quote:
                state = "normal"
            i += 1
    return "".join(out)


def _bracket_check(stripped: str, subsystem: str) -> Tuple[bool, str]:
    stack: List[str] = []
    pairs = {")": "(", "]": "[", "}": "{"}
    for idx, ch in enumerate(stripped):
        if ch in "([{":
            stack.append(ch)
        elif ch in ")]}":
            if not stack or stack[-1] != pairs[ch]:
                return False, "unbalanced '%s' at line %d" % (ch, _line_of(stripped, idx))
            stack.pop()
    if stack:
        return False, "unclosed '%s' at line %d" % (stack[-1], _line_of(stripped, len(stripped)))
    return True, "ok"


def validate_python(src: str) -> Tuple[bool, str]:
    """Compile Python with py_compile inside a temp directory; report file:line on failure."""
    try:
        import py_compile
        with tempfile.TemporaryDirectory(prefix="shitsuke_py_") as td:
            path = Path(td) / "generated.py"
            path.write_text(src, encoding="utf-8")
            py_compile.compile(str(path), cfile=str(Path(td) / "generated.pyc"), doraise=True)
        return True, "ok"
    except py_compile.PyCompileError as exc:
        text = str(exc)
        match = re.search(r"line (\d+)", text)
        return False, "python syntax error at line %s: %s" % (match.group(1) if match else "?", text.splitlines()[-1])
    except (SyntaxError, ValueError) as exc:
        line = getattr(exc, "lineno", None)
        return False, "python syntax error at line %s: %s" % (line or "?", exc)


def _lua_tokens(src: str) -> Tuple[str, List[str]]:
    out: List[str] = []
    identifiers: List[str] = []
    i = 0
    n = len(src)
    while i < n:
        ch = src[i]
        if ch == "-" and i + 1 < n and src[i + 1] == "-":
            if i + 3 < n and src[i + 2] == "[" and src[i + 3] == "[":
                end = src.find("]]", i + 4)
                i = n if end < 0 else end + 2
            else:
                end = src.find("\n", i + 2)
                i = n if end < 0 else end
            out.append(" ")
            continue
        if ch in ("'", '"'):
            quote = ch
            i += 1
            while i < n:
                if src[i] == "\\":
                    i += 2
                    continue
                if src[i] == quote:
                    i += 1
                    break
                i += 1
            out.append(" ")
            continue
        if ch in ("([{"):
            out.append(ch)
            i += 1
            continue
        if ch in (")]}"):
            out.append(ch)
            i += 1
            continue
        if ch.isalpha() or ch == "_":
            j = i
            while j < n and (src[j].isalnum() or src[j] == "_"):
                j += 1
            identifiers.append(src[i:j])
            out.append(" ")
            i = j
            continue
        out.append(" " if ch != "\n" else "\n")
        i += 1
    return "".join(out), identifiers


def validate_lua(src: str) -> Tuple[bool, str]:
    """Check Lua delimiter balance and if/for/while/function/repeat block balance."""
    stripped, identifiers = _lua_tokens(src)
    ok, msg = _bracket_check(stripped, "lua")
    if not ok:
        return False, msg
    openers = sum(1 for ident in identifiers if ident in ("function", "if", "for", "while", "repeat"))
    closers = sum(1 for ident in identifiers if ident in ("end", "until"))
    if openers != closers:
        return False, "Lua block keyword mismatch: %d openers vs %d closers" % (openers, closers)
    return True, "ok"


def validate_js(src: str) -> Tuple[bool, str]:
    """Check JS delimiter balance and optionally run node --check."""
    stripped = _strip_c_like(src)
    ok, msg = _bracket_check(stripped, "js")
    if not ok:
        return False, msg
    node = shutil.which("node")
    if not node:
        return True, "ok (node unavailable, syntax check limited)"
    try:
        with tempfile.TemporaryDirectory(prefix="shitsuke_js_") as td:
            path = Path(td) / "generated.js"
            path.write_text(src, encoding="utf-8")
            cp = run([node, "--check", str(path)], timeout=30)
            if cp.returncode != 0:
                detail = cp.stderr.decode("utf-8", errors="replace").strip().splitlines()
                return False, "node --check: %s" % (detail[-1] if detail else "syntax error")
        return True, "ok"
    except (ShitsukeError, OSError) as exc:
        return False, "node --check failed: %s" % exc


def _cpp_function_bodies(stripped: str) -> List[Tuple[str, int, str]]:
    results: List[Tuple[str, int, str]] = []
    pattern = re.compile(r"\b(?!if\b|for\b|while\b|switch\b|catch\b)([A-Za-z_][\w:<>,\s\*&]*?)\s+([A-Za-z_]\w*)\s*\([^;{}]*\)\s*(?:const\s*)?\{")
    for match in pattern.finditer(stripped):
        ret = match.group(1).strip()
        name = match.group(2)
        brace = stripped.find("{", match.end() - 1)
        if brace < 0:
            continue
        depth = 0
        end = brace
        for j in range(brace, len(stripped)):
            if stripped[j] == "{":
                depth += 1
            elif stripped[j] == "}":
                depth -= 1
                if depth == 0:
                    end = j
                    break
        results.append((ret, _line_of(stripped, match.start()), stripped[brace + 1:end]))
    return results


def validate_cpp(src: str) -> Tuple[bool, str]:
    """Check C/C++ delimiter balance and return coverage for non-void functions."""
    stripped = _strip_c_like(src)
    ok, msg = _bracket_check(stripped, "cpp")
    if not ok:
        return False, msg
    for ret, line, body in _cpp_function_bodies(stripped):
        if ret in ("void", "static", "inline", "virtual", "extern") or "void" in ret.split():
            continue
        if not re.search(r"\breturn\b", body):
            return False, "non-void function at line %d has no return" % line
    return True, "ok"


TEMPLATE_VALIDATORS: Dict[str, Callable[[str], Tuple[bool, str]]] = {
    "py": validate_python, "lua": validate_lua, "js": validate_js, "cpp": validate_cpp,
}


def _tpl(text: str, **values: str) -> str:
    return Template(text).substitute(**values)


GG_VALUE_SCAN = _tpl(r'''-- GameGuardian: value scan
-- Run inside GameGuardian. Edit CONFIG before executing.
local CONFIG = {
    value = "$value",
    value_type = gg.TYPE_DWORD,
    range = gg.REGION_ALL,
    max_results = 100
}
gg.setRanges(CONFIG.range)
gg.clearResults()
gg.searchNumber(CONFIG.value, CONFIG.value_type)
local results = gg.getResults(CONFIG.max_results)
if results == nil or #results == 0 then
    print("shitsuke: no hits")
    return
end
for i, item in ipairs(results) do
    print(string.format("shitsuke: %d address=0x%X value=%s", i, item.address, tostring(item.value)))
end
gg.clearResults()
''', value="123", **{})


GG_POINTER_CHAIN = _tpl(r'''-- GameGuardian: pointer chain walker
local CONFIG = {
    module = "$module",
    base_offset = 0x$base_offset,
    offsets = {$offsets},
    max_depth = 32
}
local function module_base(name)
    local ranges = gg.getRangesList(name)
    if ranges == nil or #ranges == 0 then
        error("module not found: " .. name)
    end
    for _, range in ipairs(ranges) do
        if range.state == "Xa" or range.state == "A" then
            return range.start
        end
    end
    return ranges[1].start
end
local function read_qword(address)
    local values = gg.getValues({{address = address, flags = gg.TYPE_QWORD}})
    if values == nil or #values == 0 then
        return nil
    end
    return values[1].value
end
local function walk_chain()
    local address = module_base(CONFIG.module) + CONFIG.base_offset
    for depth = 1, math.min(#CONFIG.offsets, CONFIG.max_depth) do
        local pointer = read_qword(address)
        if pointer == nil or pointer == 0 then
            print("shitsuke: chain stopped at depth " .. depth)
            return nil
        end
        address = pointer + CONFIG.offsets[depth]
        print(string.format("shitsuke: depth=%d address=0x%X", depth, address))
    end
    return address
end
local final = walk_chain()
if final ~= nil then
    print(string.format("shitsuke: final=0x%X", final))
end
''', module="libil2cpp.so", base_offset="0", offsets="0x10, 0x20, 0x30", **{})


GG_OFFSET_PATCH = _tpl(r'''-- GameGuardian: offset patch with restore
local CONFIG = {
    module = "$module",
    offset = 0x$offset,
    payload = "$payload",
    restore_payload = "$restore_payload"
}
local function module_base(name)
    local ranges = gg.getRangesList(name)
    if ranges == nil or #ranges == 0 then
        error("module not found: " .. name)
    end
    return ranges[1].start
end
local function parse_hex(text)
    local bytes = {}
    for token in string.gmatch(text, "%S+") do
        local value = tonumber(token, 16)
        if value == nil then
            error("bad hex byte: " .. token)
        end
        bytes[#bytes + 1] = value
    end
    return bytes
end
local function write_bytes(address, text)
    local bytes = parse_hex(text)
    local values = {}
    for i, byte in ipairs(bytes) do
        values[i] = {address = address + i - 1, flags = gg.TYPE_BYTE, value = byte}
    end
    gg.setValues(values)
    return #bytes
end
local base = module_base(CONFIG.module)
local address = base + CONFIG.offset
print(string.format("shitsuke: patching 0x%X", address))
local written = write_bytes(address, CONFIG.payload)
gg.toast("shitsuke: patched " .. written .. " bytes")
-- Restore:
-- write_bytes(address, CONFIG.restore_payload)
''', module="libil2cpp.so", offset="0", payload="00 00 80 D2 C0 03 5F D6", restore_payload="1F 20 03 D5 1F 20 03 D5", **{})


GG_AOB_SCAN = _tpl(r'''-- GameGuardian: AOB scan with ?? wildcards
local CONFIG = {
    module = "$module",
    pattern = "$pattern",
    first_only = $first_only
}
local function module_range(name)
    local ranges = gg.getRangesList(name)
    if ranges == nil or #ranges == 0 then
        error("module not found: " .. name)
    end
    return ranges[1].start, ranges[1]["end"]
end
local function aob_scan()
    gg.clearResults()
    gg.setRanges(gg.REGION_C_BSS | gg.REGION_C_DATA | gg.REGION_CODE_APP)
    gg.searchNumber("h " .. CONFIG.pattern, gg.TYPE_BYTE)
    local count = CONFIG.first_only and 1 or 100
    local results = gg.getResults(count)
    if results == nil or #results == 0 then
        print("shitsuke: no matches")
        return {}
    end
    for i, item in ipairs(results) do
        print(string.format("shitsuke: hit=%d address=0x%X", i, item.address))
    end
    return results
end
local hits = aob_scan()
gg.clearResults()
''', module="libil2cpp.so", pattern="48 8B ?? 90", first_only="true", **{})


GG_COOLDOWN = _tpl(r'''-- GameGuardian: clamped cooldown timer toggle
local CONFIG = {
    address = $address,
    minimum = 0.0,
    maximum = 1.0,
    enabled = false
}
local function clamp(value)
    if value < CONFIG.minimum then
        return CONFIG.minimum
    end
    if value > CONFIG.maximum then
        return CONFIG.maximum
    end
    return value
end
local function apply()
    if not CONFIG.enabled or CONFIG.address == 0 then
        return false
    end
    local values = gg.getValues({{address = CONFIG.address, flags = gg.TYPE_FLOAT}})
    if values == nil or #values == 0 then
        return false
    end
    local clamped = clamp(values[1].value)
    gg.setValues({{address = CONFIG.address, flags = gg.TYPE_FLOAT, value = clamped}})
    print(string.format("shitsuke: cooldown %.3f -> %.3f", values[1].value, clamped))
    return true
end
local function toggle()
    CONFIG.enabled = not CONFIG.enabled
    gg.toast("shitsuke: cooldown " .. (CONFIG.enabled and "on" or "off"))
    return CONFIG.enabled
end
local function tick()
    while true do
        apply()
        gg.sleep(100)
    end
end
-- Start: toggle(); tick()
''', address="0", **{})


GG_CONFIG_LOADER = _tpl(r'''-- GameGuardian: config loader (key=value, no eval)
local CONFIG = {
    path = "$path",
    values = {}
}
local function trim(text)
    return (text:gsub("^%s+", ""):gsub("%s+$$", ""))
end
local function parse_line(line)
    line = trim(line)
    if line == "" or string.sub(line, 1, 1) == "#" then
        return nil, nil
    end
    local key, value = string.match(line, "^([%w_%-%.]+)%s*=%s*(.+)$$")
    if key == nil then
        return nil, nil
    end
    return key, value
end
local function load()
    local file = io.open(CONFIG.path, "r")
    if file == nil then
        print("shitsuke: config not found: " .. CONFIG.path)
        return CONFIG.values
    end
    for line in file:lines() do
        local key, value = parse_line(line)
        if key ~= nil then
            CONFIG.values[key] = value
        end
    end
    file:close()
    return CONFIG.values
end
local values = load()
for key, value in pairs(values) do
    print("shitsuke: " .. key .. "=" .. value)
end
''', path="/sdcard/shitsuke.cfg", **{})


def gen_lua_gg_scan(name: str = "scan") -> str:
    """Generate a GameGuardian value-scan template."""
    return GG_VALUE_SCAN


def gen_lua_pointer_chain() -> str:
    """Generate a GameGuardian module-relative pointer-chain template."""
    return GG_POINTER_CHAIN


def gen_lua_offset_patch() -> str:
    """Generate a GameGuardian byte-patch template with restore payload."""
    return GG_OFFSET_PATCH


def gen_lua_aob_scan() -> str:
    """Generate a GameGuardian AOB scan template."""
    return GG_AOB_SCAN


def gen_lua_cooldown() -> str:
    """Generate a GameGuardian clamped cooldown toggle template."""
    return GG_COOLDOWN


def gen_lua_config_loader() -> str:
    """Generate a GameGuardian key=value config loader template."""
    return GG_CONFIG_LOADER


FRIDA_MODULE_RESOLVE = _tpl(r'''// Frida: resolve a module and list exported symbols
// frida -U -f com.mobile.legends -l module_resolve.js --no-pause
var moduleName = "$module";
var m = Process.findModuleByName(moduleName);
if (m === null) {
    console.log("[module] not loaded: " + moduleName);
} else {
    console.log("[module] name=" + m.name + " base=" + m.base + " size=" + m.size);
    var exports = m.enumerateExports();
    for (var i = 0; i < exports.length && i < 200; i++) {
        console.log("[export] " + exports[i].name + " " + exports[i].address);
    }
}
''', module="libil2cpp.so", **{})


FRIDA_IL2CPP_BRIDGE = _tpl(r'''// Frida: IL2CPP export bridge with AOB fallback
// frida -U -f com.mobile.legends -l il2cpp_bridge.js --no-pause
var moduleName = "$module";
var fallbackPattern = "$pattern";
var m = Process.findModuleByName(moduleName);
if (m === null) {
    throw new Error("module not loaded: " + moduleName);
}
function resolveExport(names) {
    for (var i = 0; i < names.length; i++) {
        var p = m.findExportByName(names[i]);
        if (p !== null) {
            return {name: names[i], address: p};
        }
    }
    return null;
}
var domain = resolveExport(["il2cpp_domain_get", "il2cpp_init"]);
if (domain === null) {
    console.log("[il2cpp] exports missing, scanning AOB");
    Memory.scan(m.base, m.size, fallbackPattern, {
        onMatch: function (address) {
            console.log("[il2cpp] fallback hit " + address);
        },
        onComplete: function () {
            console.log("[il2cpp] scan complete");
        }
    });
} else {
    console.log("[il2cpp] resolved " + domain.name + " " + domain.address);
    console.log("[il2cpp] module base " + m.base);
}
''', module="libil2cpp.so", pattern="48 8B ?? 90", **{})


FRIDA_HOOK_METHOD = _tpl(r'''// Frida: hook a module-relative method
// frida -U -f com.mobile.legends -l hook_method.js --no-pause
var moduleName = "$module";
var methodOffset = $offset;
var m = Process.findModuleByName(moduleName);
if (m === null) {
    throw new Error("module not loaded: " + moduleName);
}
var target = m.base.add(methodOffset);
console.log("[hook] target=" + target);
Interceptor.attach(target, {
    onEnter: function (args) {
        console.log("[hook] enter this=" + args[0] + " a1=" + args[1] + " a2=" + args[2]);
    },
    onLeave: function (retval) {
        console.log("[hook] leave ret=" + retval);
    }
});
''', module="libil2cpp.so", offset="0x0", **{})


FRIDA_AOB_SCAN = _tpl(r'''// Frida: AOB scan in a module
// frida -U -f com.mobile.legends -l aob_scan.js --no-pause
var moduleName = "$module";
var pattern = "$pattern";
var m = Process.findModuleByName(moduleName);
if (m === null) {
    throw new Error("module not loaded: " + moduleName);
}
var hits = 0;
Memory.scan(m.base, m.size, pattern, {
    onMatch: function (address, size) {
        hits += 1;
        console.log("[aob] hit=" + hits + " address=" + address + " size=" + size);
        if (hits >= $max_hits) {
            return "stop";
        }
    },
    onComplete: function () {
        console.log("[aob] complete hits=" + hits);
    }
});
''', module="libil2cpp.so", pattern="48 8B ?? 90", max_hits="100", **{})


def gen_frida_metadata_dump() -> str:
    """Generate the rung-8 metadata dumper as a validated Frida template."""
    return _tpl(metadata_dump_frida_script(), **{})


def gen_frida_module_resolve() -> str:
    """Generate a Frida module/export resolver."""
    return FRIDA_MODULE_RESOLVE


def gen_frida_il2cpp_bridge() -> str:
    """Generate a Frida IL2CPP export bridge with AOB fallback."""
    return FRIDA_IL2CPP_BRIDGE


def gen_frida_hook_method() -> str:
    """Generate a Frida Interceptor method hook."""
    return FRIDA_HOOK_METHOD


def gen_frida_aob_scan() -> str:
    """Generate a Frida Memory.scan AOB template."""
    return FRIDA_AOB_SCAN


CPP_STUB = _tpl(r'''// shitsuke_toolz C++ hook stub
// Reference APIs: DobbyHook/DobbyDestroy, KittyMemory::patchMemory,
// KittyMemory::restoreMemory, KittyMemory::getProtection,
// xdl_open/xdl_sym/xdl_close, Keystone via KittyMemory.
#include <jni.h>
#include <cstdint>
#include <cstddef>
#include <cstdio>
#include <cstring>
#include <string>
#include "Includes/Utils.h"
#include "KittyMemory/KittyMemory.hpp"

extern "C" {
void* xdl_open(const char* name, int flags);
void* xdl_sym(void* handle, const char* symbol, void* caller);
int xdl_close(void* handle);
int DobbyHook(void* address, void* replace, void** origin);
int DobbyDestroy(void* address);
}

static void* g_handle = nullptr;
static void* g_target = nullptr;
static void* g_original = nullptr;

static void shitsuke_hook(void* self) {
    // TODO: business logic
    reinterpret_cast<void (*)(void*)>(g_original)(self);
}

bool install_hook() {
    g_handle = xdl_open("$target", 0);
    if (g_handle == nullptr) {
        return false;
    }
    g_target = xdl_sym(g_handle, "$symbol", nullptr);
    if (g_target == nullptr) {
        return false;
    }
    return DobbyHook(g_target, reinterpret_cast<void*>(shitsuke_hook), &g_original) == 0;
}

bool remove_hook() {
    if (g_target == nullptr) {
        return false;
    }
    bool ok = DobbyDestroy(g_target) == 0;
    g_target = nullptr;
    return ok;
}

bool patch_bytes(void* address, const void* data, size_t size) {
    return KittyMemory::patchMemory(address, data, size);
}

bool restore_bytes(void* address, const void* original, size_t size) {
    return KittyMemory::restoreMemory(address, original, size);
}

extern "C" JNIEXPORT void JNICALL
Java_com_android_support_MainActivity_nativeMenuCallback(JNIEnv* env, jclass clazz, jint feature, jboolean value) {
    (void)env;
    (void)clazz;
    (void)feature;
    (void)value;
    if (value == JNI_TRUE) {
        install_hook();
    } else {
        remove_hook();
    }
}
''', target="libil2cpp.so", symbol="il2cpp_init", **{})


def gen_cpp_stub(name: str = "hook") -> str:
    """Generate a C++ hook/patch stub with real API call sites and one TODO marker."""
    symbol = re.sub(r"[^A-Za-z0-9_]", "_", name or "hook")
    return _tpl(CPP_STUB, target="libil2cpp.so", symbol=symbol, **{})


PY_ELF_READER = _tpl(r'''#!/usr/bin/env python3
"""Standalone ELF header reader generated by shitsuke_toolz."""
import argparse
import json
import struct
import sys
from pathlib import Path


def parse(path):
    data = Path(path).read_bytes()
    if data[:4] != b"\x7fELF":
        raise SystemExit("not an ELF file")
    is64 = data[4] == 2
    endian = "<" if data[5] == 1 else ">"
    if is64:
        e_type, e_machine, e_version, e_entry, e_phoff, e_shoff = struct.unpack_from(endian + "HHIQQQ", data, 16)
        e_phnum, e_shentsize, e_shnum, e_shstrndx = struct.unpack_from(endian + "HHHH", data, 56)
    else:
        e_type, e_machine, e_version, e_entry, e_phoff, e_shoff = struct.unpack_from(endian + "HHIIII", data, 16)
        e_phnum, e_shentsize, e_shnum, e_shstrndx = struct.unpack_from(endian + "HHHH", data, 44)
    return {"class": 64 if is64 else 32, "endian": "little" if endian == "<" else "big",
            "type": e_type, "machine": e_machine, "entry": e_entry,
            "phoff": e_phoff, "shoff": e_shoff, "phnum": e_phnum,
            "shentsize": e_shentsize, "shnum": e_shnum, "shstrndx": e_shstrndx}


def main(argv=None):
    parser = argparse.ArgumentParser(description="Read ELF header fields.",
                                     epilog="Example: python elf_reader.py libil2cpp.so")
    parser.add_argument("path")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    info = parse(args.path)
    if args.json:
        print(json.dumps(info, indent=2))
    else:
        for key, value in info.items():
            print(key, value)
    return 0


if __name__ == "__main__":
    sys.exit(main())
''', **{})


PY_METADATA_HEADER = _tpl(r'''#!/usr/bin/env python3
"""Standalone IL2CPP metadata header reader generated by shitsuke_toolz."""
import argparse
import json
import struct
import sys
from pathlib import Path

MAGIC = 0xFAB11BAF
FIELDS = ["stringLiteral", "stringLiteralData", "string", "events", "properties", "methods",
          "parameters", "fields", "genericParameters", "genericParameterConstraints",
          "genericContainers", "nestedTypes", "interfaces", "vtableMethods", "interfaceOffsets",
          "typeDefinitions", "images", "assemblies", "fieldRefs", "referencedAssemblies",
          "attributeData", "attributeDataRange", "exportedTypeDefinitions"]


def parse(path):
    data = Path(path).read_bytes()
    magic, version = struct.unpack_from("<Ii", data, 0)
    if magic != MAGIC:
        raise SystemExit("bad metadata magic 0x%08X" % magic)
    stride = 12 if version == 39 else 8
    sections = {}
    offset = 8
    for name in FIELDS:
        if stride == 12:
            o, size, count = struct.unpack_from("<III", data, offset)
            sections[name] = {"offset": o, "size": size, "count": count}
        else:
            o, size = struct.unpack_from("<ii", data, offset)
            sections[name] = {"offset": o, "size": size}
        offset += stride
    return {"magic": magic, "version": version, "header_size": 8 + len(FIELDS) * stride,
            "sections": sections}


def main(argv=None):
    parser = argparse.ArgumentParser(description="Read global-metadata.dat header.",
                                     epilog="Example: python metadata_header.py global-metadata.dat")
    parser.add_argument("path")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    info = parse(args.path)
    if args.json:
        print(json.dumps(info, indent=2))
    else:
        print("version", info["version"], "header_size", info["header_size"])
        for name, section in info["sections"].items():
            print(name, section)
    return 0


if __name__ == "__main__":
    sys.exit(main())
''', **{})


PY_UNITYFS_READER = _tpl(r'''#!/usr/bin/env python3
"""Standalone UnityFS header/blocks reader generated by shitsuke_toolz."""
import argparse
import json
import struct
import sys
from pathlib import Path


def parse(path):
    data = Path(path).read_bytes()
    if not data.startswith(b"UnityFS\x00"):
        raise SystemExit("not a UnityFS bundle")
    off = 8
    version = struct.unpack_from(">I", data, off)[0]
    off += 4
    end = data.find(b"\x00", off)
    player = data[off:end].decode("utf-8", "replace")
    off = end + 1
    end = data.find(b"\x00", off)
    engine = data[off:end].decode("utf-8", "replace")
    off = end + 1
    bundle_size = struct.unpack_from(">q", data, off)[0]
    off += 8
    csize, usize, flags = struct.unpack_from(">III", data, off)
    off += 12
    if version >= 7:
        off = (off + 15) // 16 * 16
    return {"format_version": version, "player_version": player, "engine_version": engine,
            "bundle_size": bundle_size, "compressed_info_size": csize,
            "uncompressed_info_size": usize, "flags": flags, "header_size": off}


def main(argv=None):
    parser = argparse.ArgumentParser(description="Read UnityFS header fields.",
                                     epilog="Example: python unityfs_reader.py bundle.unity3d")
    parser.add_argument("path")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    info = parse(args.path)
    if args.json:
        print(json.dumps(info, indent=2))
    else:
        for key, value in info.items():
            print(key, value)
    return 0


if __name__ == "__main__":
    sys.exit(main())
''', **{})


PY_AOB_SCAN = _tpl(r'''#!/usr/bin/env python3
"""Standalone AOB scanner generated by shitsuke_toolz."""
import argparse
import sys
from pathlib import Path


def pattern_to_bytes_mask(pattern):
    tokens = pattern.split()
    values = bytearray()
    masks = bytearray()
    for token in tokens:
        if token in ("?", "??", "*"):
            values.append(0)
            masks.append(0)
        else:
            if len(token) == 1:
                token = "0" + token
            values.append(int(token, 16))
            masks.append(1)
    return bytes(values), bytes(masks)


def scan(data, pattern):
    values, masks = pattern_to_bytes_mask(pattern)
    hits = []
    for start in range(0, len(data) - len(values) + 1):
        ok = True
        for i, value in enumerate(values):
            if masks[i] and data[start + i] != value:
                ok = False
                break
        if ok:
            hits.append(start)
    return hits


def main(argv=None):
    parser = argparse.ArgumentParser(description="Scan a file for an AOB pattern.",
                                     epilog="Example: python aob_scan.py libil2cpp.so --pattern '48 8B ?? 90'")
    parser.add_argument("path")
    parser.add_argument("--pattern", required=True)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    data = Path(args.path).read_bytes()
    hits = scan(data, args.pattern)
    if args.json:
        print({"pattern": args.pattern, "hits": hits})
    else:
        for hit in hits:
            print("0x%x" % hit)
        print("hits=%d" % len(hits))
    return 0


if __name__ == "__main__":
    sys.exit(main())
''', **{})


LUA_TEMPLATES: Dict[str, Callable[[], str]] = {
    "gg_scan": gen_lua_gg_scan,
    "pointer_chain": gen_lua_pointer_chain,
    "offset_patch": gen_lua_offset_patch,
    "aob_scan": gen_lua_aob_scan,
    "cooldown_timer": gen_lua_cooldown,
    "config_loader": gen_lua_config_loader,
}
FRIDA_TEMPLATES: Dict[str, Callable[[], str]] = {
    "metadata_dump": gen_frida_metadata_dump,
    "module_resolve": gen_frida_module_resolve,
    "il2cpp_bridge": gen_frida_il2cpp_bridge,
    "hook_method": gen_frida_hook_method,
    "aob_scan": gen_frida_aob_scan,
}
CPP_TEMPLATES: Dict[str, Callable[[str], str]] = {"stub": gen_cpp_stub}
PYTHON_TEMPLATES: Dict[str, str] = {
    "elf_reader": PY_ELF_READER,
    "metadata_header": PY_METADATA_HEADER,
    "unityfs_reader": PY_UNITYFS_READER,
    "aob_scan": PY_AOB_SCAN,
}


def gen_template(kind: str, template: str, name: Optional[str] = None) -> Tuple[str, str]:
    """Generate and validate a template; returns (source, extension)."""
    if kind == "lua":
        if template not in LUA_TEMPLATES:
            raise UsageError("gen", "unknown Lua template %s (choices: %s)" %
                             (template, ", ".join(sorted(LUA_TEMPLATES))))
        src = LUA_TEMPLATES[template]()
        ext = ".lua"
        validator = validate_lua
    elif kind == "frida":
        if template not in FRIDA_TEMPLATES:
            raise UsageError("gen", "unknown Frida template %s (choices: %s)" %
                             (template, ", ".join(sorted(FRIDA_TEMPLATES))))
        src = FRIDA_TEMPLATES[template]()
        ext = ".js"
        validator = validate_js
    elif kind == "cpp":
        if template not in CPP_TEMPLATES:
            raise UsageError("gen", "unknown C++ template %s (choices: stub)" % template)
        src = CPP_TEMPLATES[template](name or "hook")
        ext = ".cpp"
        validator = validate_cpp
    elif kind == "python":
        if template not in PYTHON_TEMPLATES:
            raise UsageError("gen", "unknown Python template %s (choices: %s)" %
                             (template, ", ".join(sorted(PYTHON_TEMPLATES))))
        src = PYTHON_TEMPLATES[template]
        ext = ".py"
        validator = validate_python
    else:
        raise UsageError("gen", "unknown template kind %s" % kind)
    ok, msg = validator(src)
    if not ok:
        raise ParseError("gen", "%s validation failed: %s" % (template, msg))
    return src, ext

# 40 ADB
ADB_COMMON_PATHS = ("/usr/bin/adb", "/system/bin/adb", "/data/data/com.termux/files/usr/bin/adb",
                    "/sdcard/platform-tools/adb")


def resolve_adb(explicit: Optional[str] = None) -> str:
    """Resolve adb from an explicit path/name, PATH, or common Android/Linux locations."""
    if explicit:
        p = Path(explicit)
        if p.is_file():
            return str(p)
        found = shutil.which(explicit)
        if found:
            return found
        raise DepError("adb", "adb not found: %s" % explicit)
    found = shutil.which("adb")
    if found:
        return found
    for candidate in ADB_COMMON_PATHS:
        if Path(candidate).is_file():
            return candidate
    raise DepError("adb", "adb not found in PATH; pass --adb PATH")


def _adb_prefix(adb: str, serial: Optional[str]) -> List[str]:
    args = [adb]
    if serial:
        args += ["-s", serial]
    return args


def adb_devices(adb: str) -> List[Dict[str, str]]:
    """List attached devices and their states."""
    cp = run([adb, "devices"], timeout=15)
    if cp.returncode != 0:
        raise DeviceError("adb", cp.stderr.decode("utf-8", errors="replace").strip() or "adb devices failed")
    devices: List[Dict[str, str]] = []
    for line in cp.stdout.decode("utf-8", errors="replace").splitlines()[1:]:
        parts = line.split()
        if len(parts) >= 2 and not line.startswith("*"):
            devices.append({"serial": parts[0], "state": parts[1]})
    return devices


def adb_shell(adb: str, serial: Optional[str], command: Sequence[str], timeout: int = 30) -> subprocess.CompletedProcess:
    """Run a remote shell argv with a hard timeout."""
    return run(_adb_prefix(adb, serial) + ["shell"] + [str(c) for c in command], timeout=timeout)


def _remote_sha256(adb: str, serial: Optional[str], remote: str) -> Optional[str]:
    for command in (["sha256sum", remote], ["toybox", "sha256sum", remote], ["busybox", "sha256sum", remote]):
        try:
            cp = adb_shell(adb, serial, command, timeout=20)
        except (ShitsukeError, OSError):
            continue
        text = cp.stdout.decode("utf-8", errors="replace").strip()
        match = re.match(r"^([0-9a-fA-F]{64})\b", text)
        if match:
            return match.group(1).lower()
    return None


def adb_push(adb: str, serial: Optional[str], src: Union[str, Path], dst: str, timeout: int = 120) -> Dict[str, Any]:
    """Push a file and verify SHA-256 when the device exposes sha256sum."""
    local = require_file(src, "adb")
    local_hash = sha256_file(local)
    cp = run(_adb_prefix(adb, serial) + ["push", str(local), dst], timeout=timeout)
    if cp.returncode != 0:
        raise DeviceError("adb", cp.stderr.decode("utf-8", errors="replace").strip() or "adb push failed")
    remote_hash = _remote_sha256(adb, serial, dst)
    return {"src": str(local), "dst": dst, "stdout": cp.stdout.decode("utf-8", errors="replace"),
            "sha256_local": local_hash, "sha256_remote": remote_hash,
            "verified": (local_hash == remote_hash) if remote_hash else None}


def adb_pull(adb: str, serial: Optional[str], src: str, dst: Union[str, Path], timeout: int = 120) -> Dict[str, Any]:
    """Pull a file and verify SHA-256 against the remote when possible."""
    cp = run(_adb_prefix(adb, serial) + ["pull", src, str(dst)], timeout=timeout)
    if cp.returncode != 0:
        raise DeviceError("adb", cp.stderr.decode("utf-8", errors="replace").strip() or "adb pull failed")
    local = Path(dst)
    local_hash = sha256_file(local) if local.is_file() else None
    remote_hash = _remote_sha256(adb, serial, src)
    return {"src": src, "dst": str(local), "stdout": cp.stdout.decode("utf-8", errors="replace"),
            "sha256_local": local_hash, "sha256_remote": remote_hash,
            "verified": (local_hash == remote_hash) if (local_hash and remote_hash) else None}


def adb_logcat(adb: str, serial: Optional[str], tag: Optional[str] = None, pid: Optional[int] = None,
               regex: Optional[str] = None, tail: Optional[int] = None,
               duration: Optional[int] = None) -> str:
    """Capture logcat output with local tag/pid/regex filters and an optional duration."""
    args = _adb_prefix(adb, serial) + ["logcat", "-v", "threadtime"]
    if tail is not None:
        if tail < 1:
            raise UsageError("adb", "--tail must be >= 1")
        args += ["-t", str(tail)]
    elif duration is None:
        args += ["-d"]
    timeout = (duration + 5) if duration else 30
    try:
        cp = run(args, timeout=timeout)
        text = cp.stdout.decode("utf-8", errors="replace")
    except CommandTimeout as exc:
        if duration is None:
            raise DeviceError("adb", str(exc)) from exc
        text = exc.stdout.decode("utf-8", errors="replace")
    pid_token = None
    if pid is not None:
        pid_token = "(%d)" % pid
    rx = None
    if regex:
        try:
            rx = re.compile(regex)
        except re.error as exc:
            raise UsageError("adb", "invalid regex: %s" % exc) from exc
    lines: List[str] = []
    for line in text.splitlines():
        if tag and tag.lower() not in line.lower():
            if not (pid_token and pid_token in line):
                continue
        if pid is not None and pid_token not in line and (" %d " % pid) not in line:
            if tag is None:
                continue
        if rx is not None and not rx.search(line):
            continue
        lines.append(line)
    return "\n".join(lines)


def adb_pidof(adb: str, serial: Optional[str], pkg: str = APP_PKG) -> Optional[int]:
    """Return the first PID for a package, or None when not running."""
    cp = adb_shell(adb, serial, ["pidof", pkg], timeout=10)
    text = cp.stdout.decode("utf-8", errors="replace").strip()
    if not text:
        return None
    try:
        return int(text.split()[0])
    except (ValueError, IndexError):
        return None


def adb_dumpsys_package(adb: str, serial: Optional[str], pkg: str = APP_PKG) -> Dict[str, Any]:
    """Parse versionName/Code, dataDir and nativeLibraryDir from dumpsys package."""
    cp = adb_shell(adb, serial, ["dumpsys", "package", pkg], timeout=30)
    text = cp.stdout.decode("utf-8", errors="replace")
    out: Dict[str, Any] = {"package": pkg, "raw_returncode": cp.returncode}
    for line in text.splitlines():
        s = line.strip()
        for key in ("versionName", "versionCode", "dataDir", "nativeLibraryDir"):
            marker = key + "="
            if marker in s:
                value = s.split(marker, 1)[1].strip().split()[0]
                out[key] = value
    if "versionCode" in out:
        try:
            out["versionCode_int"] = int(str(out["versionCode"]).split()[0])
        except ValueError:
            out["versionCode_int"] = None
    return out


def adb_dumpsys_window(adb: str, serial: Optional[str]) -> Dict[str, Any]:
    """Return the current window focus lines from dumpsys window."""
    cp = adb_shell(adb, serial, ["dumpsys", "window", "windows"], timeout=30)
    text = cp.stdout.decode("utf-8", errors="replace")
    focus = [line.strip() for line in text.splitlines() if "mCurrentFocus" in line or "mFocusedApp" in line]
    return {"focus": focus, "returncode": cp.returncode}


def adb_run_as_probe(adb: str, serial: Optional[str], pkg: str = APP_PKG) -> Dict[str, Any]:
    """Probe whether run-as works for the game package."""
    cp = adb_shell(adb, serial, ["run-as", pkg, "id"], timeout=10)
    return {"available": cp.returncode == 0, "returncode": cp.returncode,
            "output": (cp.stdout + cp.stderr).decode("utf-8", errors="replace").strip()}


def adb_bugreport(adb: str, serial: Optional[str], out_dir: Path) -> Path:
    """Capture a bugreport into out_dir; warns because reports are large."""
    out_dir.mkdir(parents=True, exist_ok=True)
    info("adb", "bugreport can exceed 100 MB and may take several minutes")
    cp = run(_adb_prefix(adb, serial) + ["bugreport", str(out_dir)], timeout=300)
    if cp.returncode != 0:
        raise DeviceError("adb", cp.stderr.decode("utf-8", errors="replace").strip() or "bugreport failed")
    zips = sorted(out_dir.glob("*.zip"), key=lambda p: p.stat().st_mtime, reverse=True)
    return zips[0] if zips else out_dir


def env_probe(adb: str, serial: Optional[str]) -> Dict[str, Any]:
    """Collect root/SELinux/SDK/ABI/build properties and su state."""
    keys = ["ro.build.version.sdk", "ro.product.cpu.abi", "ro.product.cpu.abilist",
            "ro.product.manufacturer", "ro.product.model", "ro.build.fingerprint",
            "ro.debuggable", "ro.secure"]
    props: Dict[str, Any] = {}
    for key in keys:
        cp = adb_shell(adb, serial, ["getprop", key], timeout=8)
        props[key] = cp.stdout.decode("utf-8", errors="replace").strip()
    cp = adb_shell(adb, serial, ["getenforce"], timeout=8)
    props["selinux"] = cp.stdout.decode("utf-8", errors="replace").strip()
    cp = adb_shell(adb, serial, ["su", "-c", "id"], timeout=8)
    props["su_id"] = (cp.stdout or cp.stderr).decode("utf-8", errors="replace").strip()
    props["su_available"] = cp.returncode == 0 and "uid=0" in props["su_id"]
    return props


def format_env_profile(env: Dict[str, Any]) -> str:
    """Render the environment profile block used before device operations."""
    lines = ["=== DEVICE PROFILE ==="]
    for key in ("ro.build.version.sdk", "ro.product.cpu.abi", "ro.product.cpu.abilist",
                "ro.product.manufacturer", "ro.product.model", "ro.build.fingerprint",
                "ro.debuggable", "ro.secure", "selinux", "su_available", "su_id"):
        value = env.get(key)
        lines.append("%s=%s" % (key, "" if value is None else value))
    return "\n".join(lines)


MLBB_PATHS = {
    "data_dir": "/data/data/%s" % APP_PKG,
    "sdcard_files": "/sdcard/Android/data/%s/files" % APP_PKG,
    "dragon2017_assets": "/sdcard/Android/data/%s/files/dragon2017/assets" % APP_PKG,
    "mini_patch": "/sdcard/Android/data/%s/files/mini_patch" % APP_PKG,
    "shared_prefs": "/data/data/%s/shared_prefs" % APP_PKG,
}


def resolve_paths(adb: str, serial: Optional[str]) -> List[Dict[str, Any]]:
    """Resolve APK, data dir, native library dir, asset roots and report rwx state."""
    out: List[Dict[str, Any]] = []
    cp = adb_shell(adb, serial, ["pm", "path", APP_PKG], timeout=15)
    apk = ""
    for line in cp.stdout.decode("utf-8", errors="replace").splitlines():
        if line.startswith("package:"):
            apk = line.split("package:", 1)[1].strip()
            break
    out.append({"name": "apk", "path": apk, "exists": bool(apk), "rwx": None})
    pkg = adb_dumpsys_package(adb, serial, APP_PKG)
    native = pkg.get("nativeLibraryDir") or ""
    if native:
        out.append({"name": "native_lib_dir", "path": native, "exists": True, "rwx": None})
    for name, path in MLBB_PATHS.items():
        exists = False
        rwx = None
        try:
            cp_test = adb_shell(adb, serial, ["test", "-e", path], timeout=10)
            exists = cp_test.returncode == 0
            cp_ls = adb_shell(adb, serial, ["ls", "-ld", path], timeout=10)
            text = cp_ls.stdout.decode("utf-8", errors="replace").strip()
            if text:
                rwx = text.split()[0]
        except (ShitsukeError, OSError):
            exists = False
        out.append({"name": name, "path": path, "exists": exists, "rwx": rwx})
    return out


# 41 Shizuku
SHIZUKU_PKG = "moe.shizuku.privileged.api"


def shizuku_probe(adb: str, serial: Optional[str]) -> Dict[str, Any]:
    """Probe Shizuku package, service, version, appops and probable start mode."""
    out: Dict[str, Any] = {"available": False, "package": SHIZUKU_PKG, "version": None,
                           "start_mode": None, "service_check": None, "service_call": None,
                           "appops": None, "fallback": "install Shizuku; use root, wireless ADB, or run-as"}
    cp = adb_shell(adb, serial, ["pm", "list", "packages"], timeout=20)
    packages = cp.stdout.decode("utf-8", errors="replace")
    if SHIZUKU_PKG not in packages:
        return out
    out["available"] = True
    cp = adb_shell(adb, serial, ["sh", "-c", "service check %s" % SHIZUKU_PKG], timeout=10)
    out["service_check"] = (cp.stdout + cp.stderr).decode("utf-8", errors="replace").strip()
    cp = adb_shell(adb, serial, ["service", "call", SHIZUKU_PKG, "1"], timeout=10)
    out["service_call"] = (cp.stdout + cp.stderr).decode("utf-8", errors="replace").strip()
    cp = adb_shell(adb, serial, ["dumpsys", "package", SHIZUKU_PKG], timeout=15)
    for line in cp.stdout.decode("utf-8", errors="replace").splitlines():
        if "versionName=" in line:
            out["version"] = line.split("versionName=", 1)[1].split()[0]
            break
    cp = adb_shell(adb, serial, ["appops", "get", SHIZUKU_PKG], timeout=10)
    out["appops"] = (cp.stdout + cp.stderr).decode("utf-8", errors="replace").strip()
    cp = adb_shell(adb, serial, ["su", "-c", "id"], timeout=8)
    root_text = (cp.stdout or cp.stderr).decode("utf-8", errors="replace")
    if cp.returncode == 0 and "uid=0" in root_text:
        out["start_mode"] = "root"
    else:
        cp2 = adb_shell(adb, serial, ["settings", "get", "global", "adb_enabled"], timeout=8)
        adb_enabled = cp2.stdout.decode("utf-8", errors="replace").strip()
        out["start_mode"] = "adb/wireless" if adb_enabled == "1" else "unknown"
    if out["start_mode"] != "root":
        out["fallback"] = ("enable wireless debugging, run `adb pair` then `adb connect`, "
                           "or start Shizuku via root")
    return out


def wireless_adb_steps() -> str:
    """Return Android 11+ wireless ADB pairing/connect instructions and examples."""
    return (
        "Android 11+ wireless ADB:\n"
        "  1. Settings > Developer options > Wireless debugging > Pair device with pairing code.\n"
        "  2. Pair:   adb pair 192.168.1.10:37000 123456\n"
        "  3. Connect: adb connect 192.168.1.10:5555\n"
        "  4. Verify:  adb devices\n"
        "Use the pairing port shown on-device for `pair`; use the debug port for `connect`."
    )


def wireless_adb_action(adb: str, pair: Optional[str] = None, code: Optional[str] = None,
                        connect: Optional[str] = None) -> Dict[str, Any]:
    """Optionally execute adb pair/connect and return captured output."""
    out: Dict[str, Any] = {"pair": None, "connect": None}
    if pair:
        if not code:
            raise UsageError("adb", "--pair requires --code")
        cp = run([adb, "pair", pair, code], timeout=60)
        out["pair"] = {"returncode": cp.returncode,
                       "stdout": cp.stdout.decode("utf-8", errors="replace"),
                       "stderr": cp.stderr.decode("utf-8", errors="replace")}
        if cp.returncode != 0:
            raise DeviceError("adb", out["pair"]["stderr"].strip() or "adb pair failed")
    if connect:
        cp = run([adb, "connect", connect], timeout=30)
        out["connect"] = {"returncode": cp.returncode,
                          "stdout": cp.stdout.decode("utf-8", errors="replace"),
                          "stderr": cp.stderr.decode("utf-8", errors="replace")}
        if cp.returncode != 0:
            raise DeviceError("adb", out["connect"]["stderr"].strip() or "adb connect failed")
    return out

# 50 mod menu scaffold
def _menu_manifest_entry(path: str, purpose: str, language: str, deps: List[str], step: str) -> Dict[str, Any]:
    return {"path": path, "purpose": purpose, "language": language,
            "dependencies": deps, "build step": step}


def emit_mod_menu(out_dir: Union[str, Path], pkg: str = "com.android.support") -> List[Path]:
    """Emit an LGLTeam-style Android mod menu source tree with a complete manifest."""
    base = Path(out_dir)
    pkg = pkg.strip()
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)+", pkg):
        raise UsageError("menu", "invalid package name: %s" % pkg)
    pkg_path = pkg.replace(".", "/")
    jni = pkg.replace(".", "_")
    jroot = "app/src/main/java/%s" % pkg_path
    files: Dict[str, str] = {}

    files["app/build.gradle"] = '''plugins {
    id 'com.android.application'
}

android {
    namespace '__PKG__'
    compileSdk 34
    ndkVersion '26.1.10909125'

    defaultConfig {
        applicationId '__PKG__'
        minSdk 21
        targetSdk 34
        versionCode 1
        versionName '1.0'
        externalNativeBuild {
            cmake {
                cppFlags '-std=c++17 -fvisibility=hidden'
                abiFilters 'arm64-v8a', 'armeabi-v7a'
            }
        }
    }

    externalNativeBuild {
        cmake {
            path 'src/main/jni/CMakeLists.txt'
            version '3.22.1'
        }
    }

    compileOptions {
        sourceCompatibility JavaVersion.VERSION_1_8
        targetCompatibility JavaVersion.VERSION_1_8
    }

    buildTypes {
        debug { debuggable true }
        release {
            minifyEnabled false
            proguardFiles getDefaultProguardFile('proguard-android-optimize.txt'), 'proguard-rules.pro'
        }
    }
}
'''.replace("__PKG__", pkg)

    files["app/src/main/AndroidManifest.xml"] = '''<?xml version="1.0" encoding="utf-8"?>
<manifest xmlns:android="http://schemas.android.com/apk/res/android">
    <uses-permission android:name="android.permission.SYSTEM_ALERT_WINDOW" />
    <uses-permission android:name="android.permission.FOREGROUND_SERVICE" />
    <!-- <uses-permission android:name="android.permission.INTERNET" /> -->
    <uses-permission android:name="android.permission.POST_NOTIFICATIONS" />
    <application
        android:label="Shitsuke Toolz"
        android:allowBackup="false"
        android:supportsRtl="true">
        <activity android:name=".MainActivity" android:exported="true">
            <intent-filter>
                <action android:name="android.intent.action.MAIN" />
                <category android:name="android.intent.category.LAUNCHER" />
            </intent-filter>
        </activity>
        <service
            android:name=".base.FloatingWindowManager"
            android:exported="false"
            android:foregroundServiceType="specialUse" />
    </application>
</manifest>
'''

    files[jroot + "/MainActivity.java"] = '''package __PKG__;

import android.app.Activity;
import android.content.Intent;
import android.graphics.Color;
import android.net.Uri;
import android.os.Build;
import android.os.Bundle;
import android.provider.Settings;
import android.view.View;
import android.view.ViewGroup;
import android.widget.ArrayAdapter;
import android.widget.Button;
import android.widget.EditText;
import android.widget.LinearLayout;
import android.widget.SeekBar;
import android.widget.Spinner;
import android.widget.Switch;
import android.widget.TextView;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

import __PKG__.interfaces.IMenuBuilder;
import __PKG__.interfaces.IMenuComponentFactory;
import __PKG__.ThemesData.LGLTheme;
import __PKG__.base.FloatingWindowManager;

public class MainActivity extends Activity implements IMenuComponentFactory {
    static {
        System.loadLibrary("menu");
    }

    public static native void nativeMenuInit();
    public static native void nativeMenuSetFeature(String key, boolean enabled);
    public static native boolean nativeMenuGetFeature(String key);
    public static native void nativeMenuSetSeek(String key, int value);
    public static native int nativeMenuGetSeek(String key);

    private final List<Map<String, Object>> entries = new ArrayList<>();

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.M && !Settings.canDrawOverlays(this)) {
            Intent intent = new Intent(Settings.ACTION_MANAGE_OVERLAY_PERMISSION,
                    Uri.parse("package:" + getPackageName()));
            startActivity(intent);
            return;
        }
        TextView status = new TextView(this);
        status.setText("Shitsuke Toolz\\nOverlay permission granted. HUD starts on resume.");
        status.setTextColor(Color.WHITE);
        status.setBackgroundColor(Color.rgb(16, 16, 18));
        status.setPadding(32, 32, 32, 32);
        setContentView(status);
        startHud();
    }

    @Override
    protected void onResume() {
        super.onResume();
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.M || Settings.canDrawOverlays(this)) {
            startHud();
        }
    }

    private void startHud() {
        Intent intent = new Intent(this, FloatingWindowManager.class);
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            startForegroundService(intent);
        } else {
            startService(intent);
        }
    }

    @Override
    public View makeSwitch(String label, boolean value, final BoolCallback callback) {
        Switch view = new Switch(this);
        view.setText(label);
        view.setTextColor(Color.WHITE);
        view.setChecked(value);
        view.setOnCheckedChangeListener(new android.widget.CompoundButton.OnCheckedChangeListener() {
            @Override
            public void onCheckedChanged(android.widget.CompoundButton buttonView, boolean isChecked) {
                callback.onChanged(isChecked);
            }
        });
        return view;
    }

    @Override
    public View makeSlider(String label, float min, float max, float value, final FloatCallback callback) {
        LinearLayout group = new LinearLayout(this);
        group.setOrientation(LinearLayout.VERTICAL);
        TextView title = new TextView(this);
        title.setText(label);
        title.setTextColor(Color.WHITE);
        SeekBar bar = new SeekBar(this);
        bar.setMax(1000);
        bar.setProgress((int) ((value - min) / Math.max(0.0001f, max - min) * 1000.0f));
        bar.setOnSeekBarChangeListener(new SeekBar.OnSeekBarChangeListener() {
            @Override public void onProgressChanged(SeekBar seekBar, int progress, boolean fromUser) {
                callback.onChanged(min + (max - min) * progress / 1000.0f);
            }
            @Override public void onStartTrackingTouch(SeekBar seekBar) { }
            @Override public void onStopTrackingTouch(SeekBar seekBar) { }
        });
        group.addView(title);
        group.addView(bar);
        return group;
    }

    @Override
    public View makeInput(String label, String value, final StringCallback callback) {
        LinearLayout group = new LinearLayout(this);
        group.setOrientation(LinearLayout.VERTICAL);
        TextView title = new TextView(this);
        title.setText(label);
        title.setTextColor(Color.WHITE);
        EditText edit = new EditText(this);
        edit.setText(value);
        edit.setTextColor(Color.WHITE);
        edit.setHint(label);
        group.addView(title);
        group.addView(edit);
        edit.addTextChangedListener(new android.text.TextWatcher() {
            @Override public void beforeTextChanged(CharSequence s, int start, int count, int after) { }
            @Override public void onTextChanged(CharSequence s, int start, int before, int count) {
                callback.onChanged(s.toString());
            }
            @Override public void afterTextChanged(android.text.Editable s) { }
        });
        return group;
    }

    @Override
    public View makeButton(String label, final ButtonCallback callback) {
        Button button = new Button(this);
        button.setText(label);
        button.setOnClickListener(new View.OnClickListener() {
            @Override public void onClick(View view) { callback.onClick(); }
        });
        return button;
    }

    @Override
    public View makeCategoryHeader(String label) {
        TextView header = new TextView(this);
        header.setText(label.toUpperCase());
        header.setTextColor(Color.rgb(255, 92, 92));
        header.setPadding(8, 20, 8, 8);
        return header;
    }

    @Override
    public View makeSpinner(String label, String[] values, int selected, final IntCallback callback) {
        LinearLayout group = new LinearLayout(this);
        group.setOrientation(LinearLayout.VERTICAL);
        TextView title = new TextView(this);
        title.setText(label);
        title.setTextColor(Color.WHITE);
        Spinner spinner = new Spinner(this);
        ArrayAdapter<String> adapter = new ArrayAdapter<String>(this,
                android.R.layout.simple_spinner_dropdown_item, values);
        spinner.setAdapter(adapter);
        spinner.setSelection(Math.max(0, Math.min(selected, values.length - 1)));
        spinner.setOnItemSelectedListener(new android.widget.AdapterView.OnItemSelectedListener() {
            @Override public void onItemSelected(android.widget.AdapterView<?> parent, View view, int position, long id) {
                callback.onChanged(position);
            }
            @Override public void onNothingSelected(android.widget.AdapterView<?> parent) { }
        });
        group.addView(title);
        group.addView(spinner);
        return group;
    }

    @Override
    public View makeSeekBar(String label, int min, int max, int value, final IntCallback callback) {
        LinearLayout group = new LinearLayout(this);
        group.setOrientation(LinearLayout.VERTICAL);
        TextView title = new TextView(this);
        title.setText(label + ": " + value);
        title.setTextColor(Color.WHITE);
        SeekBar bar = new SeekBar(this);
        bar.setMax(Math.max(1, max - min));
        bar.setProgress(value - min);
        bar.setOnSeekBarChangeListener(new SeekBar.OnSeekBarChangeListener() {
            @Override public void onProgressChanged(SeekBar seekBar, int progress, boolean fromUser) {
                int actual = min + progress;
                title.setText(label + ": " + actual);
                callback.onChanged(actual);
            }
            @Override public void onStartTrackingTouch(SeekBar seekBar) { }
            @Override public void onStopTrackingTouch(SeekBar seekBar) { }
        });
        group.addView(title);
        group.addView(bar);
        return group;
    }

    @Override
    public View makeCollapseGroup(String label, View content) {
        LinearLayout group = new LinearLayout(this);
        group.setOrientation(LinearLayout.VERTICAL);
        Button header = new Button(this);
        header.setText(label);
        final View body = content;
        header.setOnClickListener(new View.OnClickListener() {
            @Override public void onClick(View view) {
                body.setVisibility(body.getVisibility() == View.VISIBLE ? View.GONE : View.VISIBLE);
            }
        });
        group.addView(header);
        group.addView(body);
        return group;
    }

    @Override
    public View makeColorPicker(String label, int color, final IntCallback callback) {
        LinearLayout group = new LinearLayout(this);
        group.setOrientation(LinearLayout.HORIZONTAL);
        TextView title = new TextView(this);
        title.setText(label);
        title.setTextColor(Color.WHITE);
        final EditText hex = new EditText(this);
        hex.setText(String.format("#%06X", color & 0xFFFFFF));
        hex.setTextColor(Color.WHITE);
        hex.addTextChangedListener(new android.text.TextWatcher() {
            @Override public void beforeTextChanged(CharSequence s, int start, int count, int after) { }
            @Override public void onTextChanged(CharSequence s, int start, int before, int count) {
                try {
                    callback.onChanged(Color.parseColor(s.toString()));
                } catch (IllegalArgumentException ignored) {
                }
            }
            @Override public void afterTextChanged(android.text.Editable s) { }
        });
        group.addView(title);
        group.addView(hex, new LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1.0f));
        return group;
    }

    private final class MenuBuilderImpl implements IMenuBuilder {
        @Override
        public void addEntry(String key, String label, String kind, Object value) {
            Map<String, Object> entry = new LinkedHashMap<>();
            entry.put("key", key);
            entry.put("label", label);
            entry.put("kind", kind);
            entry.put("value", value);
            entries.add(entry);
        }

        @Override
        public List<Map<String, Object>> getEntries() {
            return entries;
        }
    }
}
'''.replace("__PKG__", pkg)

    files[jroot + "/Launcher.java"] = '''package __PKG__;

import android.content.Context;
import android.content.Intent;
import android.net.Uri;
import android.os.Build;
import android.provider.Settings;

import __PKG__.base.FloatingWindowManager;

public final class Launcher {
    private Launcher() { }

    public static boolean launch(Context context) {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.M && !Settings.canDrawOverlays(context)) {
            Intent intent = new Intent(Settings.ACTION_MANAGE_OVERLAY_PERMISSION,
                    Uri.parse("package:" + context.getPackageName()));
            intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
            context.startActivity(intent);
            return false;
        }
        Intent service = new Intent(context, FloatingWindowManager.class);
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            context.startForegroundService(service);
        } else {
            context.startService(service);
        }
        return true;
    }
}
'''.replace("__PKG__", pkg)

    files[jroot + "/Preferences.java"] = '''package __PKG__;

import android.content.Context;
import android.content.SharedPreferences;

public final class Preferences {
    private final SharedPreferences prefs;

    public Preferences(Context context) {
        prefs = context.getSharedPreferences("shitsuke", Context.MODE_PRIVATE);
    }

    public boolean enabled() { return prefs.getBoolean("enabled", true); }
    public void setEnabled(boolean value) { prefs.edit().putBoolean("enabled", value).apply(); }
    public boolean stealth() { return prefs.getBoolean("stealth", false); }
    public void setStealth(boolean value) { prefs.edit().putBoolean("stealth", value).apply(); }
    public int theme() { return prefs.getInt("theme", 0); }
    public void setTheme(int value) { prefs.edit().putInt("theme", value).apply(); }
    public boolean feature(String key, boolean fallback) {
        return prefs.getBoolean("feature_" + key, fallback);
    }
    public void setFeature(String key, boolean value) {
        prefs.edit().putBoolean("feature_" + key, value).apply();
    }
    public int seek(String key, int fallback) {
        return prefs.getInt("seek_" + key, fallback);
    }
    public void setSeek(String key, int value) {
        prefs.edit().putInt("seek_" + key, value).apply();
    }
}
'''.replace("__PKG__", pkg)

    files[jroot + "/CrashHandler.java"] = '''package __PKG__;

import android.content.Context;
import android.content.pm.PackageInfo;
import android.os.Build;

import java.io.File;
import java.io.FileWriter;
import java.io.PrintWriter;
import java.io.StringWriter;
import java.text.SimpleDateFormat;
import java.util.Arrays;
import java.util.Comparator;
import java.util.Date;
import java.util.Locale;

public final class CrashHandler implements Thread.UncaughtExceptionHandler {
    private final Context context;
    private final Thread.UncaughtExceptionHandler previous;

    public CrashHandler(Context context) {
        this.context = context.getApplicationContext();
        this.previous = Thread.getDefaultUncaughtExceptionHandler();
    }

    public void install() {
        Thread.setDefaultUncaughtExceptionHandler(this);
    }

    @Override
    public void uncaughtException(Thread thread, Throwable error) {
        try {
            File dir = new File(context.getExternalFilesDir(null), "LOG_DIR");
            if (!dir.exists() && !dir.mkdirs()) {
                throw new IllegalStateException("cannot create crash directory");
            }
            String stamp = new SimpleDateFormat("yyyyMMdd_HHmmss", Locale.US).format(new Date());
            File log = new File(dir, "crash_" + stamp + ".log");
            PrintWriter out = new PrintWriter(new FileWriter(log, true));
            out.println("model=" + Build.MODEL);
            out.println("manufacturer=" + Build.MANUFACTURER);
            out.println("sdk=" + Build.VERSION.SDK_INT);
            out.println("abi=" + (Build.SUPPORTED_ABIS.length > 0 ? Build.SUPPORTED_ABIS[0] : "unknown"));
            try {
                PackageInfo info = context.getPackageManager().getPackageInfo(context.getPackageName(), 0);
                out.println("app_version=" + info.versionName + " (" + info.versionCode + ")");
            } catch (Exception ignored) {
                out.println("app_version=unknown");
            }
            out.println("thread=" + thread.getName());
            StringWriter buffer = new StringWriter();
            error.printStackTrace(new PrintWriter(buffer));
            out.println(buffer.toString());
            out.close();
            prune(dir);
        } catch (Exception ignored) {
        }
        if (previous != null) {
            previous.uncaughtException(thread, error);
        } else {
            android.os.Process.killProcess(android.os.Process.myPid());
            System.exit(1);
        }
    }

    private void prune(File dir) {
        File[] logs = dir.listFiles();
        if (logs == null || logs.length <= 5) {
            return;
        }
        Arrays.sort(logs, new Comparator<File>() {
            @Override public int compare(File a, File b) {
                return Long.compare(a.lastModified(), b.lastModified());
            }
        });
        for (int i = 0; i < logs.length - 5; i++) {
            if (!logs[i].delete()) {
                logs[i].deleteOnExit();
            }
        }
    }
}
'''.replace("__PKG__", pkg)

    files[jroot + "/base/IFloatingBuilder.java"] = '''package __PKG__.base;

public interface IFloatingBuilder {
    void buildBubble();
    void buildExpandedMenu();
    void show();
    void hide();
    boolean isShowing();
}
'''.replace("__PKG__", pkg)

    files[jroot + "/base/FloatingWindowManager.java"] = '''package __PKG__.base;

import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.app.Service;
import android.content.Context;
import android.content.Intent;
import android.content.res.Configuration;
import android.graphics.Color;
import android.graphics.PixelFormat;
import android.graphics.drawable.GradientDrawable;
import android.os.Build;
import android.os.IBinder;
import android.util.DisplayMetrics;
import android.view.Gravity;
import android.view.MotionEvent;
import android.view.View;
import android.view.WindowManager;
import android.widget.Button;
import android.widget.LinearLayout;
import android.widget.SeekBar;
import android.widget.Switch;
import android.widget.TextView;

import __PKG__.MainActivity;
import __PKG__.Preferences;

public class FloatingWindowManager extends Service implements IFloatingBuilder {
    public static final String ACTION_RESTORE = "__PKG__.RESTORE";
    private static final String CHANNEL = "shitsuke_hud";
    private static final int NOTIFICATION_ID = 0x5A17;

    private WindowManager windowManager;
    private WindowManager.LayoutParams bubbleParams;
    private WindowManager.LayoutParams panelParams;
    private View bubble;
    private View panel;
    private boolean expanded;
    private boolean stealth;
    private int bubbleX = 24;
    private int bubbleY = 180;
    private Preferences preferences;

    @Override
    public void onCreate() {
        super.onCreate();
        preferences = new Preferences(this);
        createChannel();
        startForeground(NOTIFICATION_ID, buildNotification());
        windowManager = (WindowManager) getSystemService(Context.WINDOW_SERVICE);
        buildBubble();
        buildExpandedMenu();
        show();
    }

    @Override
    public int onStartCommand(Intent intent, int flags, int startId) {
        if (intent != null && ACTION_RESTORE.equals(intent.getAction())) {
            setStealth(false);
        }
        return START_STICKY;
    }

    @Override
    public IBinder onBind(Intent intent) {
        return null;
    }

    @Override
    public void buildBubble() {
        TextView button = new TextView(this);
        button.setText("ST");
        button.setTextColor(Color.WHITE);
        button.setTextSize(12);
        button.setGravity(Gravity.CENTER);
        GradientDrawable shape = new GradientDrawable();
        shape.setShape(GradientDrawable.OVAL);
        shape.setColor(Color.rgb(196, 30, 58));
        shape.setStroke(2, Color.rgb(255, 210, 210));
        button.setBackground(shape);
        int size = dp(46);
        bubble = button;
        int type = Build.VERSION.SDK_INT >= Build.VERSION_CODES.O
                ? WindowManager.LayoutParams.TYPE_APPLICATION_OVERLAY
                : WindowManager.LayoutParams.TYPE_PHONE;
        bubbleParams = new WindowManager.LayoutParams(size, size, type,
                WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE
                        | WindowManager.LayoutParams.FLAG_LAYOUT_NO_LIMITS
                        | WindowManager.LayoutParams.FLAG_LAYOUT_IN_SCREEN,
                PixelFormat.TRANSLUCENT);
        bubbleParams.gravity = Gravity.TOP | Gravity.START;
        bubbleParams.x = bubbleX;
        bubbleParams.y = bubbleY;
        button.setOnClickListener(new View.OnClickListener() {
            @Override public void onClick(View view) {
                expanded = !expanded;
                if (panel != null) {
                    panel.setVisibility(expanded ? View.VISIBLE : View.GONE);
                }
            }
        });
        button.setOnTouchListener(new View.OnTouchListener() {
            private int downX;
            private int downY;
            private float touchX;
            private float touchY;
            @Override
            public boolean onTouch(View view, MotionEvent event) {
                switch (event.getActionMasked()) {
                    case MotionEvent.ACTION_DOWN:
                        downX = bubbleParams.x;
                        downY = bubbleParams.y;
                        touchX = event.getRawX();
                        touchY = event.getRawY();
                        return false;
                    case MotionEvent.ACTION_MOVE:
                        bubbleX = downX + (int) (event.getRawX() - touchX);
                        bubbleY = downY + (int) (event.getRawY() - touchY);
                        clamp();
                        bubbleParams.x = bubbleX;
                        bubbleParams.y = bubbleY;
                        if (windowManager != null && bubble != null) {
                            windowManager.updateViewLayout(bubble, bubbleParams);
                        }
                        return true;
                    default:
                        return false;
                }
            }
        });
    }

    @Override
    public void buildExpandedMenu() {
        LinearLayout root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        root.setPadding(dp(14), dp(14), dp(14), dp(14));
        GradientDrawable background = new GradientDrawable();
        background.setColor(Color.argb(235, 18, 18, 22));
        background.setCornerRadius(dp(12));
        background.setStroke(1, Color.rgb(196, 30, 58));
        root.setBackground(background);

        TextView title = new TextView(this);
        title.setText("SHITSUKE TOOLZ");
        title.setTextColor(Color.rgb(255, 92, 92));
        title.setTextSize(15);
        root.addView(title);

        root.addView(featureSwitch("aim_assist", "Aim assist", false));
        root.addView(featureSwitch("esp", "ESP overlay", false));
        root.addView(featureSwitch("cooldown", "Cooldown clamp", false));
        root.addView(seekRow("fov", "FOV", 30, 180, 90));

        Button hide = new Button(this);
        hide.setText("HIDE");
        hide.setOnClickListener(new View.OnClickListener() {
            @Override public void onClick(View view) {
                if (panel != null) {
                    panel.setVisibility(View.GONE);
                }
                expanded = false;
            }
        });
        root.addView(hide);

        Button secure = new Button(this);
        secure.setText("STEALTH");
        secure.setOnClickListener(new View.OnClickListener() {
            @Override public void onClick(View view) {
                setStealth(!stealth);
            }
        });
        root.addView(secure);

        int width = Math.min(dp(240), screenWidth() - dp(24));
        panel = root;
        int type = Build.VERSION.SDK_INT >= Build.VERSION_CODES.O
                ? WindowManager.LayoutParams.TYPE_APPLICATION_OVERLAY
                : WindowManager.LayoutParams.TYPE_PHONE;
        panelParams = new WindowManager.LayoutParams(width, WindowManager.LayoutParams.WRAP_CONTENT, type,
                WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE
                        | WindowManager.LayoutParams.FLAG_LAYOUT_NO_LIMITS
                        | WindowManager.LayoutParams.FLAG_LAYOUT_IN_SCREEN,
                PixelFormat.TRANSLUCENT);
        panelParams.gravity = Gravity.TOP | Gravity.START;
        panelParams.x = Math.max(0, screenWidth() - width - dp(12));
        panelParams.y = dp(80);
        panel.setVisibility(View.GONE);
    }

    private View featureSwitch(final String key, String label, boolean fallback) {
        Switch toggle = new Switch(this);
        toggle.setText(label);
        toggle.setTextColor(Color.WHITE);
        toggle.setChecked(preferences.feature(key, fallback));
        toggle.setOnCheckedChangeListener(new android.widget.CompoundButton.OnCheckedChangeListener() {
            @Override public void onCheckedChanged(android.widget.CompoundButton buttonView, boolean isChecked) {
                preferences.setFeature(key, isChecked);
                MainActivity.nativeMenuSetFeature(key, isChecked);
            }
        });
        return toggle;
    }

    private View seekRow(final String key, String label, final int min, final int max, int fallback) {
        LinearLayout row = new LinearLayout(this);
        row.setOrientation(LinearLayout.VERTICAL);
        TextView caption = new TextView(this);
        int value = preferences.seek(key, fallback);
        caption.setText(label + ": " + value);
        caption.setTextColor(Color.WHITE);
        SeekBar bar = new SeekBar(this);
        bar.setMax(max - min);
        bar.setProgress(Math.max(0, Math.min(value - min, max - min)));
        bar.setOnSeekBarChangeListener(new SeekBar.OnSeekBarChangeListener() {
            @Override public void onProgressChanged(SeekBar seekBar, int progress, boolean fromUser) {
                int actual = min + progress;
                caption.setText(label + ": " + actual);
                preferences.setSeek(key, actual);
                MainActivity.nativeMenuSetSeek(key, actual);
            }
            @Override public void onStartTrackingTouch(SeekBar seekBar) { }
            @Override public void onStopTrackingTouch(SeekBar seekBar) { }
        });
        row.addView(caption);
        row.addView(bar);
        return row;
    }

    @Override
    public void show() {
        if (windowManager == null) {
            return;
        }
        if (bubble != null && bubble.getParent() == null) {
            windowManager.addView(bubble, bubbleParams);
        }
        if (panel != null && panel.getParent() == null) {
            windowManager.addView(panel, panelParams);
        }
    }

    @Override
    public void hide() {
        if (windowManager == null) {
            return;
        }
        if (bubble != null && bubble.getParent() != null) {
            windowManager.removeView(bubble);
        }
        if (panel != null && panel.getParent() != null) {
            windowManager.removeView(panel);
        }
    }

    @Override
    public boolean isShowing() {
        return bubble != null && bubble.getParent() != null;
    }

    public void setStealth(boolean enabled) {
        stealth = enabled;
        if (panelParams != null) {
            if (enabled) {
                panelParams.flags |= WindowManager.LayoutParams.FLAG_SECURE;
            } else {
                panelParams.flags &= ~WindowManager.LayoutParams.FLAG_SECURE;
            }
            if (windowManager != null && panel != null && panel.getParent() != null) {
                windowManager.updateViewLayout(panel, panelParams);
            }
        }
        startForeground(NOTIFICATION_ID, buildNotification());
    }

    @Override
    public void onConfigurationChanged(Configuration newConfig) {
        super.onConfigurationChanged(newConfig);
        clamp();
        if (bubbleParams != null && bubble != null && windowManager != null && bubble.getParent() != null) {
            windowManager.updateViewLayout(bubble, bubbleParams);
        }
        if (panelParams != null && panel != null && windowManager != null && panel.getParent() != null) {
            int width = Math.min(dp(240), screenWidth() - dp(24));
            panelParams.width = width;
            panelParams.x = Math.max(0, Math.min(panelParams.x, screenWidth() - width));
            panelParams.y = Math.max(0, Math.min(panelParams.y, screenHeight() - dp(80)));
            windowManager.updateViewLayout(panel, panelParams);
        }
    }

    private void clamp() {
        int width = screenWidth();
        int height = screenHeight();
        int bubbleSize = bubble == null ? dp(46) : bubble.getWidth();
        if (bubbleSize <= 0) {
            bubbleSize = dp(46);
        }
        bubbleX = Math.max(0, Math.min(bubbleX, width - bubbleSize));
        bubbleY = Math.max(0, Math.min(bubbleY, height - bubbleSize));
        if (bubbleParams != null) {
            bubbleParams.x = bubbleX;
            bubbleParams.y = bubbleY;
        }
    }

    private int screenWidth() {
        DisplayMetrics metrics = new DisplayMetrics();
        if (windowManager != null) {
            windowManager.getDefaultDisplay().getRealMetrics(metrics);
        }
        return metrics.widthPixels;
    }

    private int screenHeight() {
        DisplayMetrics metrics = new DisplayMetrics();
        if (windowManager != null) {
            windowManager.getDefaultDisplay().getRealMetrics(metrics);
        }
        return metrics.heightPixels;
    }

    private int dp(int value) {
        return Math.round(value * getResources().getDisplayMetrics().density);
    }

    private void createChannel() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            NotificationManager manager = (NotificationManager) getSystemService(Context.NOTIFICATION_SERVICE);
            NotificationChannel channel = new NotificationChannel(CHANNEL, "Shitsuke HUD",
                    NotificationManager.IMPORTANCE_LOW);
            channel.setDescription("Overlay service status");
            manager.createNotificationChannel(channel);
        }
    }

    private Notification buildNotification() {
        Intent restore = new Intent(this, FloatingWindowManager.class);
        restore.setAction(ACTION_RESTORE);
        int flags = PendingIntent.FLAG_UPDATE_CURRENT;
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.M) {
            flags |= PendingIntent.FLAG_IMMUTABLE;
        }
        PendingIntent pending = PendingIntent.getService(this, 7, restore, flags);
        Notification.Builder builder;
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            builder = new Notification.Builder(this, CHANNEL);
        } else {
            builder = new Notification.Builder(this);
        }
        builder.setSmallIcon(android.R.drawable.ic_dialog_info)
                .setContentTitle("Shitsuke Toolz")
                .setContentText(stealth ? "Stealth mode active" : "HUD overlay active")
                .setOngoing(true)
                .addAction(new Notification.Action.Builder(
                        android.R.drawable.ic_menu_view, "Restore overlay", pending).build());
        return builder.build();
    }

    @Override
    public void onDestroy() {
        hide();
        super.onDestroy();
    }
}
'''.replace("__PKG__", pkg)

    files[jroot + "/interfaces/IMenuBuilder.java"] = '''package __PKG__.interfaces;

import java.util.List;
import java.util.Map;

public interface IMenuBuilder {
    void addEntry(String key, String label, String kind, Object value);
    List<Map<String, Object>> getEntries();
}
'''.replace("__PKG__", pkg)

    files[jroot + "/interfaces/IMenuComponentFactory.java"] = '''package __PKG__.interfaces;

import android.view.View;

public interface IMenuComponentFactory {
    interface BoolCallback { void onChanged(boolean value); }
    interface FloatCallback { void onChanged(float value); }
    interface StringCallback { void onChanged(String value); }
    interface IntCallback { void onChanged(int value); }
    interface ButtonCallback { void onClick(); }

    View makeSwitch(String label, boolean value, BoolCallback callback);
    View makeSlider(String label, float min, float max, float value, FloatCallback callback);
    View makeInput(String label, String value, StringCallback callback);
    View makeButton(String label, ButtonCallback callback);
    View makeCategoryHeader(String label);
    View makeSpinner(String label, String[] values, int selected, IntCallback callback);
    View makeSeekBar(String label, int min, int max, int value, IntCallback callback);
    View makeCollapseGroup(String label, View content);
    View makeColorPicker(String label, int color, IntCallback callback);
}
'''.replace("__PKG__", pkg)

    files[jroot + "/ThemesData/LGLTheme.java"] = '''package __PKG__.ThemesData;

import android.graphics.Color;

public class LGLTheme {
    public final int backgroundColor = Color.argb(235, 18, 18, 22);
    public final int panelColor = Color.argb(245, 26, 26, 31);
    public final int textColor = Color.WHITE;
    public final int mutedTextColor = Color.rgb(174, 174, 184);
    public final int accentColor = Color.rgb(255, 92, 92);
    public final int trackColor = Color.rgb(70, 70, 78);
    public final int switchOnColor = Color.rgb(196, 30, 58);
    public final float cornerRadius = 12.0f;
    public final float itemRadius = 8.0f;
    public final String fontFamily = "sans-serif-condensed";
    public final int padding = 14;
    public final int itemSpacing = 8;
    public final int headerTextSize = 15;
    public final int bodyTextSize = 13;
}
'''.replace("__PKG__", pkg)

    files[jroot + "/ThemesData/DZTheme.java"] = '''package __PKG__.ThemesData;

import android.graphics.Color;

public class DZTheme {
    public final int backgroundColor = Color.argb(240, 8, 12, 16);
    public final int panelColor = Color.argb(250, 14, 22, 30);
    public final int textColor = Color.rgb(230, 245, 255);
    public final int mutedTextColor = Color.rgb(140, 168, 184);
    public final int accentColor = Color.rgb(0, 200, 255);
    public final int trackColor = Color.rgb(36, 58, 72);
    public final int switchOnColor = Color.rgb(0, 160, 210);
    public final float cornerRadius = 4.0f;
    public final float itemRadius = 3.0f;
    public final String fontFamily = "monospace";
    public final int padding = 12;
    public final int itemSpacing = 6;
    public final int headerTextSize = 14;
    public final int bodyTextSize = 12;
}
'''.replace("__PKG__", pkg)

    files["app/src/main/jni/CMakeLists.txt"] = '''cmake_minimum_required(VERSION 3.22.1)
project(shitsuke_menu CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

add_library(menu SHARED
        Main.cpp
        Menu/Menu.cpp)

target_include_directories(menu PRIVATE ${CMAKE_CURRENT_SOURCE_DIR})
target_link_libraries(menu log android)
'''

    files["app/src/main/jni/Includes/Macros.h"] = '''#pragma once

#define SHITSUKE_TAG "ShitsukeMenu"
#define SHITSUKE_LOG(...) __android_log_print(ANDROID_LOG_INFO, SHITSUKE_TAG, __VA_ARGS__)
#define SHITSUKE_UNUSED(x) (void)(x)
#define SHITSUKE_EXPORT extern "C" __attribute__((visibility("default")))
'''

    files["app/src/main/jni/Includes/Utils.h"] = '''#pragma once

#include <jni.h>
#include <android/log.h>
#include <cstddef>
#include <cstdint>
#include <string>

#include "Macros.h"

extern "C" {
void* xdl_open(const char* name, int flags);
void* xdl_sym(void* handle, const char* symbol, void* caller);
int xdl_close(void* handle);
int DobbyHook(void* address, void* replace, void** origin);
int DobbyDestroy(void* address);
}

namespace KittyMemory {
bool patchMemory(void* address, const void* data, size_t size);
bool restoreMemory(void* address, const void* original, size_t size);
int getProtection(void* address);
}

namespace shitsuke {
inline std::string obfuscate(const char* text) {
    std::string out(text == nullptr ? "" : text);
    for (size_t i = 0; i < out.size(); i++) {
        out[i] = static_cast<char>(out[i] ^ static_cast<char>(0x5A + (i & 7)));
    }
    return out;
}

inline void log(const char* message) {
    __android_log_print(ANDROID_LOG_INFO, SHITSUKE_TAG, "%s", message);
}
}

#define AY_OBFUSCATE(text) shitsuke::obfuscate(text)
'''

    files["app/src/main/jni/Menu/Menu.h"] = '''#pragma once

#include <jni.h>

bool menuInit();
void menuSetFeature(const char* key, bool enabled);
bool menuGetFeature(const char* key);
void menuSetSeek(const char* key, int value);
int menuGetSeek(const char* key);
bool install_hooks();
void remove_hooks();
'''

    files["app/src/main/jni/Menu/Menu.cpp"] = '''#include "Menu.h"
#include "Includes/Utils.h"

#include <mutex>
#include <string>
#include <unordered_map>

namespace {
std::mutex g_mutex;
std::unordered_map<std::string, bool> g_features;
std::unordered_map<std::string, int> g_seeks;
void* g_library = nullptr;
void* g_target = nullptr;
void* g_original = nullptr;

void hook_dispatch(void* self) {
    // TODO: business logic
    reinterpret_cast<void (*)(void*)>(g_original)(self);
}
}  // namespace

bool menuInit() {
    std::lock_guard<std::mutex> lock(g_mutex);
    g_features["aim_assist"] = false;
    g_features["esp"] = false;
    g_features["cooldown"] = false;
    g_seeks["fov"] = 90;
    return true;
}

void menuSetFeature(const char* key, bool enabled) {
    if (key == nullptr) {
        return;
    }
    std::lock_guard<std::mutex> lock(g_mutex);
    g_features[std::string(key)] = enabled;
}

bool menuGetFeature(const char* key) {
    if (key == nullptr) {
        return false;
    }
    std::lock_guard<std::mutex> lock(g_mutex);
    auto it = g_features.find(std::string(key));
    return it != g_features.end() && it->second;
}

void menuSetSeek(const char* key, int value) {
    if (key == nullptr) {
        return;
    }
    std::lock_guard<std::mutex> lock(g_mutex);
    g_seeks[std::string(key)] = value;
}

int menuGetSeek(const char* key) {
    if (key == nullptr) {
        return 0;
    }
    std::lock_guard<std::mutex> lock(g_mutex);
    auto it = g_seeks.find(std::string(key));
    return it == g_seeks.end() ? 0 : it->second;
}

bool install_hooks() {
    g_library = xdl_open(AY_OBFUSCATE("libil2cpp.so").c_str(), 0);
    if (g_library == nullptr) {
        shitsuke::log("target library not loaded");
        return false;
    }
    g_target = xdl_sym(g_library, AY_OBFUSCATE("il2cpp_init").c_str(), nullptr);
    if (g_target == nullptr) {
        shitsuke::log("target symbol not found");
        return false;
    }
    int result = DobbyHook(g_target, reinterpret_cast<void*>(hook_dispatch), &g_original);
    return result == 0;
}

void remove_hooks() {
    if (g_target != nullptr) {
        DobbyDestroy(g_target);
        g_target = nullptr;
    }
    if (g_library != nullptr) {
        xdl_close(g_library);
        g_library = nullptr;
    }
}
'''

    files["app/src/main/jni/Main.cpp"] = '''#include <jni.h>

#include "Menu/Menu.h"
#include "Includes/Macros.h"
#include "Includes/Utils.h"

SHITSUKE_EXPORT jint JNI_OnLoad(JavaVM* vm, void* reserved) {
    SHITSUKE_UNUSED(reserved);
    JNIEnv* env = nullptr;
    if (vm->GetEnv(reinterpret_cast<void**>(&env), JNI_VERSION_1_6) != JNI_OK) {
        return JNI_ERR;
    }
    menuInit();
    if (!install_hooks()) {
        shitsuke::log("JNI_OnLoad: hook installation failed");
    }
    return JNI_VERSION_1_6;
}

extern "C" JNIEXPORT jboolean JNICALL
Java___JNI___MainActivity_nativeMenuInit(JNIEnv* env, jclass clazz) {
    SHITSUKE_UNUSED(env);
    SHITSUKE_UNUSED(clazz);
    return menuInit() ? JNI_TRUE : JNI_FALSE;
}

extern "C" JNIEXPORT void JNICALL
Java___JNI___MainActivity_nativeMenuSetFeature(JNIEnv* env, jclass clazz, jstring key, jboolean enabled) {
    SHITSUKE_UNUSED(clazz);
    if (key == nullptr) {
        return;
    }
    const char* text = env->GetStringUTFChars(key, nullptr);
    menuSetFeature(text, enabled == JNI_TRUE);
    env->ReleaseStringUTFChars(key, text);
}

extern "C" JNIEXPORT jboolean JNICALL
Java___JNI___MainActivity_nativeMenuGetFeature(JNIEnv* env, jclass clazz, jstring key) {
    SHITSUKE_UNUSED(clazz);
    if (key == nullptr) {
        return JNI_FALSE;
    }
    const char* text = env->GetStringUTFChars(key, nullptr);
    bool result = menuGetFeature(text);
    env->ReleaseStringUTFChars(key, text);
    return result ? JNI_TRUE : JNI_FALSE;
}

extern "C" JNIEXPORT void JNICALL
Java___JNI___MainActivity_nativeMenuSetSeek(JNIEnv* env, jclass clazz, jstring key, jint value) {
    SHITSUKE_UNUSED(clazz);
    if (key == nullptr) {
        return;
    }
    const char* text = env->GetStringUTFChars(key, nullptr);
    menuSetSeek(text, static_cast<int>(value));
    env->ReleaseStringUTFChars(key, text);
}

extern "C" JNIEXPORT jint JNICALL
Java___JNI___MainActivity_nativeMenuGetSeek(JNIEnv* env, jclass clazz, jstring key) {
    SHITSUKE_UNUSED(clazz);
    if (key == nullptr) {
        return 0;
    }
    const char* text = env->GetStringUTFChars(key, nullptr);
    int result = menuGetSeek(text);
    env->ReleaseStringUTFChars(key, text);
    return static_cast<jint>(result);
}
'''.replace("__JNI__", jni)

    files["app/src/main/jni/KittyMemory/README"] = '''KittyMemory is not vendored by this generator.

Add the KittyMemory headers and sources used by your build:
  KittyMemory/KittyMemory.hpp
  KittyMemory/MemoryPatch.hpp
  KittyMemory/KittyMemory.cpp
  KittyMemory/MemoryPatch.cpp

Utils.h declares the subset used by this scaffold:
  KittyMemory::patchMemory
  KittyMemory::restoreMemory
  KittyMemory::getProtection

Dobby and xDL are likewise external dependencies. Add their static/shared
libraries to CMakeLists.txt and link them into the `menu` target. The generator
emits source only; it does not compile or download native dependencies.
'''

    notes = '''# Shitsuke Toolz Mod Menu Build Notes

## Prerequisites
- Android Studio with Android SDK 34 and build-tools.
- Android NDK 26.1.10909125 (or change ndkVersion in app/build.gradle).
- CMake 3.22.1.
- minSdk 21; targetSdk 34.

## Configure the target
- Set the applicationId in app/build.gradle. The default package root is
  com.android.support. This intentionally collides with legacy Android support
  libraries; do not add androidx/support dependencies to this module.
- Set the target library and symbol in app/src/main/jni/Menu/Menu.cpp
  (`libil2cpp.so`, `il2cpp_init`).
- Add hook logic on the single `// TODO: business logic` line.
- Add features by extending the maps in Menu.cpp and adding JNI declarations
  in Main.cpp only when exposing a new native entry point.
- Patch/restore bytes with KittyMemory::patchMemory / restoreMemory.
- Resolve modules and symbols with xdl_open / xdl_sym / xdl_close.
- Resolve target exports with DobbyHook / DobbyDestroy.

## Build
- Debug:   ./gradlew :app:assembleDebug
- Release: ./gradlew :app:assembleRelease
- Native only: cmake --build app/.cxx/... (configure through Gradle first).

This tool emits source files only. It does not compile, sign, or install the
APK, and it does not download native dependencies.
'''
    files["BUILD_NOTES.md"] = notes

    manifest: List[Dict[str, Any]] = []
    purposes = {
        "app/build.gradle": ("Android application build configuration", "gradle", [], "gradle :app:assembleDebug"),
        "app/src/main/AndroidManifest.xml": ("Overlay service manifest and permissions", "xml", ["app/build.gradle"], "gradle :app:assembleDebug"),
        jroot + "/MainActivity.java": ("Overlay permission gate and menu component factory", "java", ["app/src/main/AndroidManifest.xml"], "gradle :app:assembleDebug"),
        jroot + "/Launcher.java": ("Programmatic HUD launcher", "java", [jroot + "/MainActivity.java"], "gradle :app:assembleDebug"),
        jroot + "/Preferences.java": ("Persistent feature/seek/stealth settings", "java", [], "gradle :app:assembleDebug"),
        jroot + "/CrashHandler.java": ("Crash log rotation (last 5)", "java", [], "gradle :app:assembleDebug"),
        jroot + "/base/IFloatingBuilder.java": ("Overlay builder contract", "java", [], "gradle :app:assembleDebug"),
        jroot + "/base/FloatingWindowManager.java": ("Foreground overlay service, draggable HUD, stealth mode", "java", [jroot + "/Preferences.java", jroot + "/MainActivity.java"], "gradle :app:assembleDebug"),
        jroot + "/interfaces/IMenuBuilder.java": ("Menu entry collector contract", "java", [], "gradle :app:assembleDebug"),
        jroot + "/interfaces/IMenuComponentFactory.java": ("One factory method per menu component", "java", [], "gradle :app:assembleDebug"),
        jroot + "/ThemesData/LGLTheme.java": ("LGL color/radius/font/padding theme", "java", [], "gradle :app:assembleDebug"),
        jroot + "/ThemesData/DZTheme.java": ("DZ color/radius/font/padding theme", "java", [], "gradle :app:assembleDebug"),
        "app/src/main/jni/CMakeLists.txt": ("Native menu module build", "cmake", ["app/build.gradle"], "gradle :app:assembleDebug"),
        "app/src/main/jni/Main.cpp": ("JNI_OnLoad and menu JNI entry points", "cpp", ["app/src/main/jni/Menu/Menu.cpp"], "gradle :app:assembleDebug"),
        "app/src/main/jni/Menu/Menu.cpp": ("Feature maps, target resolution and hook lifecycle", "cpp", ["app/src/main/jni/Menu/Menu.h"], "gradle :app:assembleDebug"),
        "app/src/main/jni/Menu/Menu.h": ("Menu native API declarations", "cpp", [], "gradle :app:assembleDebug"),
        "app/src/main/jni/Includes/Utils.h": ("xDL, Dobby, KittyMemory declarations and obfuscator", "cpp", [], "gradle :app:assembleDebug"),
        "app/src/main/jni/Includes/Macros.h": ("Logging/export macros", "cpp", [], "gradle :app:assembleDebug"),
        "app/src/main/jni/KittyMemory/README": ("External KittyMemory dependency notes", "text", [], "manual dependency setup"),
        "BUILD_NOTES.md": ("Build and customization notes", "markdown", [], "none"),
    }
    for rel, content in files.items():
        purpose, language, deps, step = purposes.get(rel, ("Mod menu scaffold", "text", [], "gradle"))
        manifest.append(_menu_manifest_entry(rel, purpose, language, deps, step))
    manifest.append(_menu_manifest_entry("manifest.json", "Per-file scaffold inventory", "json", [], "none"))
    files["manifest.json"] = json.dumps(manifest, indent=2) + "\n"

    for rel, content in files.items():
        if rel.endswith(".json"):
            try:
                json.loads(content)
            except json.JSONDecodeError as exc:
                raise ParseError("menu", "invalid generated JSON %s: %s" % (rel, exc))
        elif rel.endswith(".xml"):
            try:
                ET.fromstring(content)
            except ET.ParseError as exc:
                raise ParseError("menu", "invalid generated XML %s: %s" % (rel, exc))
        elif rel.endswith(".cpp") or rel.endswith(".h"):
            ok, msg = validate_cpp(content)
            if not ok:
                raise ParseError("menu", "invalid generated C++ %s: %s" % (rel, msg))
        elif rel.endswith(".java"):
            stripped = _strip_c_like(content)
            ok, msg = _bracket_check(stripped, "menu")
            if not ok:
                raise ParseError("menu", "invalid generated Java %s: %s" % (rel, msg))

    written: List[Path] = []
    for rel, content in files.items():
        path = base / rel
        atomic_write(path, content.encode("utf-8"))
        written.append(path)
    return written

# 60 surface map
MAP_SOURCE_WEIGHTS = {"symbol": 3.0, "metadata": 3.0, "asset": 2.0, "string": 1.0}
MAP_MAX_ASSET_BYTES = 16 * 1024 * 1024
MAP_MAX_TEXT = 240
MAP_MAX_ROWS = 5000


def load_keywords(path: Union[str, Path]) -> List[str]:
    """Load keywords from a text file, ignoring blanks and # comments."""
    p = require_file(path, "map")
    try:
        lines = p.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError as exc:
        raise ToolIOError("map", "cannot read %s: %s" % (p, exc))
    keywords: List[str] = []
    seen = set()
    for line in lines:
        value = line.strip()
        if not value or value.startswith("#"):
            continue
        if value in seen:
            continue
        seen.add(value)
        keywords.append(value)
    if not keywords:
        raise UsageError("map", "no keywords in %s" % p)
    return keywords


def _compile_keywords(keywords: Sequence[str], use_regex: bool) -> List[Tuple[str, "re.Pattern[str]"]]:
    """Compile keywords for case-insensitive substring or regex matching."""
    compiled: List[Tuple[str, "re.Pattern[str]"]] = []
    for keyword in keywords:
        try:
            pattern = re.compile(keyword if use_regex else re.escape(keyword), re.IGNORECASE)
        except re.error as exc:
            raise UsageError("map", "invalid regex %r: %s" % (keyword, exc))
        compiled.append((keyword, pattern))
    return compiled


def _map_sources_from_file(path: Path) -> List[Dict[str, Any]]:
    """Collect strings, symbols and metadata literals from a single file."""
    sources: List[Dict[str, Any]] = []
    data = path.read_bytes()
    for item in extract_strings(data, 4):
        if len(item["value"]) > MAP_MAX_TEXT * 8:
            continue
        sources.append({"file": str(path), "type": "string", "offset": item["offset"],
                        "encoding": item["encoding"], "text": item["value"], "detail": item["encoding"]})
    if data.startswith(ELF_MAGIC):
        try:
            elf = parse_elf(path)
        except ShitsukeError:
            elf = None
        if elf is not None:
            for symbol in elf.get("symbols", []):
                if not symbol.get("name"):
                    continue
                sources.append({"file": str(path), "type": "symbol", "offset": None,
                                "encoding": None, "text": symbol["name"],
                                "detail": "%s value=0x%x table=%s" % (symbol["type_name"],
                                                                      symbol["value"], symbol["table"])})
    if path.name in ("global-metadata.dat", "global-metadata.dat.enc"):
        try:
            header = parse_metadata_header(data)
        except ShitsukeError:
            header = None
        if header is not None:
            for literal in metadata_string_literals(data, header, limit=200000):
                sources.append({"file": str(path), "type": "metadata", "offset": literal.get("offset"),
                                "encoding": None, "text": literal.get("value", ""),
                                "detail": "string literal"})
            for item in metadata_type_names(data, header, limit=50000):
                name = item.get("name")
                if name:
                    sources.append({"file": str(path), "type": "metadata", "offset": None,
                                    "encoding": None, "text": name,
                                    "detail": "type namespace=%s" % item.get("namespace", "")})
    return sources


def _map_sources_from_asset(path: Path) -> List[Dict[str, Any]]:
    """Collect text from XML/JSON/plain assets, skipping oversized blobs."""
    try:
        size = path.stat().st_size
    except OSError:
        return []
    if size <= 0 or size > MAP_MAX_ASSET_BYTES:
        return []
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    return [{"file": str(path), "type": "asset", "offset": None, "encoding": None,
             "text": text, "detail": "asset text"}]


def collect_surface_sources(binary: Union[str, Path]) -> List[Dict[str, Any]]:
    """Walk a file or asset tree and collect all searchable surfaces."""
    base = Path(binary)
    if not base.exists():
        raise ToolIOError("map", "not found: %s" % base)
    sources: List[Dict[str, Any]] = []
    if base.is_file():
        return _map_sources_from_file(base)
    if not base.is_dir():
        raise ToolIOError("map", "cannot search: %s" % base)
    for path in sorted(base.rglob("*")):
        if not path.is_file():
            continue
        suffix = path.suffix.lower()
        if suffix in (".xml", ".json", ".txt", ".csv", ".html", ".cfg", ".ini", ".bytes"):
            sources.extend(_map_sources_from_asset(path))
        elif path.name in ("global-metadata.dat", "global-metadata.dat.enc") or suffix in (".so", ".bin", ".dat"):
            try:
                sources.extend(_map_sources_from_file(path))
            except (OSError, ShitsukeError):
                continue
        if len(sources) > 2000000:
            break
    return sources


def build_surface_map(binary: Union[str, Path], keywords_path: Union[str, Path],
                      exact: bool = False, use_regex: bool = False) -> Dict[str, Any]:
    """Match keywords against every collected surface and score the hits."""
    keywords = load_keywords(keywords_path)
    compiled = _compile_keywords(keywords, use_regex)
    sources = collect_surface_sources(binary)
    rows: List[Dict[str, Any]] = []
    groups: Dict[str, List[Dict[str, Any]]] = {keyword: [] for keyword in keywords}
    truncated = False
    for source in sources:
        text = source["text"]
        lower_text = text.lower()
        for keyword, pattern in compiled:
            if use_regex:
                matches = list(pattern.finditer(text))
                if not matches:
                    continue
                matched_text = matches[0].group(0)
                occurrences = len(matches)
            elif exact:
                if lower_text != keyword.lower():
                    continue
                matched_text = text
                occurrences = 1
            else:
                occurrences = lower_text.count(keyword.lower())
                if occurrences == 0:
                    continue
                position = lower_text.find(keyword.lower())
                matched_text = text[position:position + len(keyword)]
            weight = MAP_SOURCE_WEIGHTS.get(source["type"], 1.0)
            length_ratio = min(len(keyword) / max(len(text), 1), 0.5)
            score = weight * (1.0 + length_ratio)
            if exact:
                score += 1.0
            row = {
                "keyword": keyword, "source_type": source["type"], "file": source["file"],
                "offset": source["offset"], "encoding": source["encoding"],
                "matched_text": matched_text[:MAP_MAX_TEXT],
                "detail": source["detail"], "occurrences": occurrences,
                "score": round(score, 4),
            }
            rows.append(row)
            groups[keyword].append(row)
            if len(rows) >= MAP_MAX_ROWS:
                truncated = True
                break
        if truncated:
            break
    rows.sort(key=lambda item: (-item["score"], item["keyword"], item["file"]))
    summary = {}
    for keyword in keywords:
        bucket = groups[keyword]
        summary[keyword] = {
            "hits": len(bucket),
            "top_score": bucket[0]["score"] if bucket else 0.0,
            "types": sorted({row["source_type"] for row in bucket}),
        }
    return {
        "binary": str(binary), "keyword_file": str(keywords_path),
        "keyword_count": len(keywords), "source_count": len(sources),
        "total_hits": len(rows), "truncated": truncated,
        "groups": summary, "rows": rows,
        "mode": "regex" if use_regex else ("exact" if exact else "substring"),
    }


def surface_map_csv(result: Dict[str, Any]) -> str:
    """Render surface map rows as CSV."""
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=["keyword", "source_type", "file", "offset",
                                             "encoding", "occurrences", "score", "detail",
                                             "matched_text"])
    writer.writeheader()
    for row in result["rows"]:
        writer.writerow(row)
    return buf.getvalue()


def emit_surface_frida(result: Dict[str, Any], path: Union[str, Path]) -> Path:
    """Write a Frida resolver that scans modules for the mapped keywords."""
    keywords = sorted(result["groups"])
    module_names = sorted({Path(row["file"]).name for row in result["rows"]
                           if Path(row["file"]).suffix in (".so", ".so.enc")}) or ["libil2cpp.so"]
    payload = json.dumps({"keywords": keywords, "modules": module_names})
    source = '''// shitsuke_toolz surface resolver
'use strict';

const CONFIG = __CONFIG__;

function asciiBytes(text) {
    const out = [];
    for (let i = 0; i < text.length; i++) {
        out.push(text.charCodeAt(i) & 0xff);
    }
    return out;
}

function utf16Bytes(text) {
    const out = [];
    for (let i = 0; i < text.length; i++) {
        const code = text.charCodeAt(i);
        out.push(code & 0xff, (code >> 8) & 0xff);
    }
    return out;
}

function toHexPattern(bytes) {
    return bytes.map(function (value) {
        return ('0' + value.toString(16)).slice(-2);
    }).join(' ');
}

function scanModule(moduleName, keyword) {
    const mod = Process.findModuleByName(moduleName);
    if (mod === null) {
        send({ kind: 'missing-module', module: moduleName });
        return;
    }
    const needles = [
        { encoding: 'ascii', pattern: toHexPattern(asciiBytes(keyword)) },
        { encoding: 'utf16le', pattern: toHexPattern(utf16Bytes(keyword)) }
    ];
    needles.forEach(function (needle) {
        Memory.scan(mod.base, mod.size, needle.pattern, {
            onMatch: function (address, size) {
                send({
                    kind: 'match', module: moduleName, keyword: keyword,
                    encoding: needle.encoding, address: address.toString(), size: size
                });
            },
            onError: function (reason) {
                send({ kind: 'scan-error', module: moduleName, reason: reason });
            }
        });
    });
}

function resolveSymbols() {
    Process.enumerateModules().forEach(function (mod) {
        if (CONFIG.modules.indexOf(mod.name) === -1) {
            return;
        }
        mod.enumerateSymbols().forEach(function (symbol) {
            const name = symbol.name || '';
            for (let i = 0; i < CONFIG.keywords.length; i++) {
                if (name.toLowerCase().indexOf(CONFIG.keywords[i].toLowerCase()) !== -1) {
                    send({
                        kind: 'symbol', module: mod.name, keyword: CONFIG.keywords[i],
                        symbol: name, address: symbol.address.toString()
                    });
                    break;
                }
            }
        });
    });
}

rpc.exports = {
    scan: function () {
        resolveSymbols();
        CONFIG.modules.forEach(function (moduleName) {
            CONFIG.keywords.forEach(function (keyword) {
                scanModule(moduleName, keyword);
            });
        });
        return { modules: CONFIG.modules, keywords: CONFIG.keywords.length };
    }
};

setImmediate(function () {
    send({ kind: 'ready', modules: CONFIG.modules, keywords: CONFIG.keywords.length });
});
'''.replace("__CONFIG__", payload)
    ok, message = validate_js(source)
    if not ok:
        raise ParseError("map", "generated Frida resolver failed validation: %s" % message)
    target = Path(path)
    atomic_write(target, source.encode("utf-8"))
    return target

# 70 selftest
def _selftest_elf() -> bytes:
    """Build a minimal ELF64 shared object with .text, .dynsym, .strtab and .shstrtab."""
    text = b"SHITSUKE_SELFTEST_MARKER\x00" + b"\x48\x8b\x11\x90" + b"\x00" * 12
    dynsym = struct.pack("<IBBHQQ", 1, (1 << 4) | 2, 0, 1, 0x10000 + 120, 8)
    strtab = b"\x00shitsuke_symbol\x00"
    shstr = b"\x00.text\x00.dynsym\x00.strtab\x00.shstrtab\x00"
    text_off = 64 + 56
    dyn_off = text_off + len(text)
    str_off = dyn_off + len(dynsym)
    shstr_off = str_off + len(strtab)
    shoff = align_up(shstr_off + len(shstr), 8)
    total = shoff + 5 * 64
    out = bytearray(total)
    ident = b"\x7fELF" + bytes([2, 1, 1, 0]) + b"\x00" * 8
    ehdr = ident + struct.pack("<HHIQQQIHHHHHH", 3, 183, 1, 0, 64, shoff, 0,
                               64, 56, 1, 64, 5, 4)
    out[0:64] = ehdr
    out[64:120] = struct.pack("<IIQQQQQQ", 1, 5, 0, 0x10000, 0x10000, total, total, 0x1000)
    out[text_off:text_off + len(text)] = text
    out[dyn_off:dyn_off + len(dynsym)] = dynsym
    out[str_off:str_off + len(strtab)] = strtab
    out[shstr_off:shstr_off + len(shstr)] = shstr

    def shdr(index: int, name: int, typ: int, flags: int, addr: int, offset: int,
             size: int, link: int = 0, info: int = 0, alignment: int = 1, entsize: int = 0) -> None:
        start = shoff + index * 64
        out[start:start + 64] = struct.pack("<IIQQQQIIQQ", name, typ, flags, addr, offset,
                                            size, link, info, alignment, entsize)

    shdr(0, 0, 0, 0, 0, 0, 0)
    shdr(1, 1, 1, 6, 0x10000 + text_off, text_off, len(text), alignment=16)
    shdr(2, 7, 11, 2, 0x10000 + dyn_off, dyn_off, len(dynsym), link=3, info=1,
         alignment=8, entsize=24)
    shdr(3, 15, 3, 0, 0, str_off, len(strtab))
    shdr(4, 23, 3, 0, 0, shstr_off, len(shstr))
    return bytes(out)


def _selftest_metadata() -> bytes:
    """Build a plausible global-metadata.dat header (version 24) for recovery tests."""
    header_size = 8 + len(METADATA_FIELDS) * 8
    out = bytearray(struct.pack("<II", METADATA_MAGIC, 24))
    for name in METADATA_FIELDS:
        if name == "stringLiteral":
            out += struct.pack("<ii", header_size, 8)
        else:
            out += struct.pack("<ii", 0, 0)
    out += b"\x00" * (header_size - len(out))
    out += struct.pack("<ii", 0, 0)
    return bytes(out)


def _selftest_serialized(bundle_name: str = "orig_bundle") -> bytes:
    """Build a SerializedFile (v22) containing one AssetBundle pathID 1 object."""
    blob = bytearray()
    blob += encode_lp_string("selftest_cab")
    blob += struct.pack("<i", 0)
    blob += struct.pack("<i", 2)
    for path in ("assets/selftest/a.bundle", "assets/selftest/b.bundle"):
        blob += encode_lp_string(path)
        blob += struct.pack("<iiIq", 0, 1, 0, 1)
    blob += struct.pack("<iiIq", 0, 0, 0, 0)
    blob += struct.pack("<i", 0)
    blob += encode_lp_string(bundle_name)
    blob += encode_lp_string("")
    blob += struct.pack("<i", 0)
    blob = bytes(blob)
    meta = bytearray()
    meta += b"2021.3.0f1\x00"
    meta += struct.pack("<i", 0)
    meta += b"\x01"
    meta += struct.pack("<i", 1)
    meta += struct.pack("<i", ASSET_BUNDLE_CLASS_ID)
    meta += b"\x00"
    meta += struct.pack("<h", -1)
    meta += struct.pack("<ii", 0, 0)
    meta += struct.pack("<i", 1)
    meta += struct.pack("<qqIi", 1, 0, len(blob), 0)
    data_offset = 44 + len(meta)
    file_size = data_offset + len(blob)
    header = bytearray()
    header += struct.pack("<IIII", len(meta), file_size, 22, data_offset)
    header += b"\x00\x00\x00\x00"
    header += struct.pack("<QQQ", len(meta), file_size, data_offset)
    if len(header) != 44:
        raise AssertionError("serialized selftest header size")
    return bytes(header) + bytes(meta) + blob


def _selftest_unityfs(serialized_blob: bytes, flags: int) -> bytes:
    """Wrap a SerializedFile in a synthetic UnityFS bundle."""
    header = {"format_version": 6, "player_version": "5.x.x",
              "engine_version": "2019.4.0f1", "flags": flags}
    node = {"offset": 0, "size": len(serialized_blob), "flags": 0, "path": "CAB-selftest"}
    return build_unityfs(header, [node], [serialized_blob])


def _selftest_fake_adb(path: Path) -> None:
    """Write a POSIX shell adb double used by device selftests."""
    script = '''#!/bin/sh
case "$1" in
  devices)
    printf 'List of devices attached\\nemulator-5554\\tdevice\\n'
    exit 0
    ;;
  -s)
    shift 2
    ;;
esac
case "$1" in
  shell)
    shift
    case "$1" in
      getprop) printf '30\\n'; exit 0 ;;
      getenforce) printf 'Enforcing\\n'; exit 0 ;;
      pidof) printf '4242\\n'; exit 0 ;;
      echo) shift; printf '%s\\n' "$*"; exit 0 ;;
      test) exit 0 ;;
      ls) printf -- '-rw-r--r-- 1 root root 1 2020-01-01 00:00 %s\\n' "$2"; exit 0 ;;
      su) shift; shift; printf 'uid=0(root) gid=0(root)\\n'; exit 0 ;;
    esac
    ;;
  push|pull) exit 0 ;;
esac
exit 0
'''
    atomic_write(path, script.encode("utf-8"))
    path.chmod(0o755)


def run_selftest() -> int:
    """Run every subsystem against synthetic fixtures and report PASS/FAIL per check."""
    passed = 0
    failed = 0
    failures: List[Tuple[str, str]] = []

    def check(name: str, fn: Any) -> None:
        nonlocal passed, failed
        try:
            fn()
        except Exception as exc:
            failed += 1
            failures.append((name, "%s: %s" % (type(exc).__name__, exc)))
            print("FAIL %s: %s: %s" % (name, type(exc).__name__, exc))
        else:
            passed += 1
            print("PASS %s" % name)

    tmp_root = Path(tempfile.mkdtemp(prefix="shitsuke_selftest_"))
    try:
        elf_path = tmp_root / "libil2cpp.so"
        atomic_write(elf_path, _selftest_elf())
        elf_data = elf_path.read_bytes()
        text_off = 120
        elf_info: Dict[str, Any] = {}

        def check_bytes() -> None:
            assert read_u32_le(b"\x01\x00\x00\x00", 0) == 1
            assert align_up(17, 8) == 24
            values, masks = pattern_to_bytes_mask("48 8B ?? 90")
            assert values == b"\x48\x8b\x00\x90" and masks == b"\x01\x01\x00\x01"
            assert human_size(2048) == "2.00 KiB"

        check("bytes", check_bytes)

        def check_elf() -> None:
            info = parse_elf(elf_path)
            elf_info.update(info)
            assert info["class"] == "ELF64" and info["arch"] == "AArch64"
            assert info["section_header_count"] == 5
            assert any(section["name"] == ".text" and section["executable"] for section in info["sections"])
            assert any(symbol["name"] == "shitsuke_symbol" for symbol in info["symbols"])
            assert elf_offset_to_vaddr(info, text_off) == 0x10000 + text_off
            assert elf_offset_section(info, text_off) == ".text"
            assert elf_offset_is_exec(info, text_off) is True

        check("elf_parse", check_elf)

        def check_scan() -> None:
            pattern = "48 8B ?? 90"
            hits = aob_scan(elf_data, pattern)
            assert hits == [text_off + len(b"SHITSUKE_SELFTEST_MARKER\x00")]
            enriched = aob_hits(elf_data, pattern, context=4, elf_info=elf_info)
            assert len(enriched) == 1
            assert enriched[0]["section"] == ".text"
            assert enriched[0]["vaddr"] == 0x10000 + hits[0]

        check("aob_scan", check_scan)

        def check_strings() -> None:
            strings = extract_strings(elf_data, 4)
            assert any(item["value"].startswith("SHITSUKE_SELFTEST_MARKER") for item in strings)
            symbols = extract_symbols(elf_path)
            assert any(item["name"] == "shitsuke_symbol" for item in symbols)
            report = strings_report(elf_path, 4)
            assert report["string_count"] > 0 and report["symbol_count"] == 1
            assert "value" in strings_csv(report["strings"]).splitlines()[0]

        check("strings_symbols", check_strings)

        def check_recon() -> None:
            abi_dir = tmp_root / "apk" / "lib" / "arm64-v8a"
            abi_dir.mkdir(parents=True)
            shutil.copy2(elf_path, abi_dir / "libil2cpp.so")
            result = resolve_targets(tmp_root / "apk")
            assert result["abi_dirs"] == ["arm64-v8a"]
            found = [item for item in result["found"] if item["name"] == "libil2cpp.so"]
            assert found and found[0]["arch"] == "AArch64"
            assert "liblogic.so" in result["missing"]

        check("recon", check_recon)

        meta = _selftest_metadata()

        def check_metadata() -> None:
            header = parse_metadata_header(meta)
            assert header["magic_ok"] and header["version"] == 24
            assert header["stringLiteral_count"] == 1
            direct = metadata_recover(meta)
            assert direct["rung"] == 1
            wrapped = metadata_recover(b"\x00" * 16 + meta)
            assert wrapped["rung"] == 2 and wrapped["header"]["version"] == 24
            inverted = metadata_recover(bytes((~byte) & 0xFF for byte in meta))
            assert inverted["rung"] == 3
            xor_one = metadata_recover(bytes(byte ^ 0x37 for byte in meta))
            assert xor_one["rung"] == 4
            key = b"\x12\x34\x56\x78"
            xor_four = metadata_recover(bytes(byte ^ key[index % 4] for index, byte in enumerate(meta)))
            assert xor_four["rung"] == 5
            report = metadata_report(meta, recover=True, base_dir=None)
            assert report["header"] is not None and report["recovery"]["rung"] == 1
            export_dir = tmp_root / "metadata-export"
            written = export_metadata_reference(meta, header, export_dir, elf_path)
            names = {path.name for path in written}
            assert names == {"dump.cs", "script.json", "stringliteral.json", "dump-manifest.json"}
            assert (export_dir / "dump-manifest.json").is_file()

        check("metadata", check_metadata)

        serialized = _selftest_serialized()
        bundle_raw = _selftest_unityfs(serialized, 0)
        bundle_lz4 = _selftest_unityfs(serialized, 0x43)
        bundle_tail = _selftest_unityfs(serialized, 0xC3)
        bundle_path = tmp_root / "selftest.unity3d"
        atomic_write(bundle_path, bundle_raw)

        def check_unityfs() -> None:
            for flags, blob in ((0, bundle_raw), (0x43, bundle_lz4), (0xC3, bundle_tail)):
                parsed = read_unityfs_bytes(blob, "fixture")
                assert parsed["header"]["format_version"] == 6
                assert parsed["header"]["flags"] == flags
                assert len(parsed["nodes"]) == 1
                assert node_bytes(parsed, parsed["nodes"][0]) == serialized
            loaded = read_unityfs(bundle_path)
            assert loaded["file_size"] == len(bundle_raw)
            lz4_payload = b"shitsuke lz4 roundtrip " * 16
            assert lz4_block_decompress_pure(lz4_block_compress_pure(lz4_payload), len(lz4_payload)) == lz4_payload
            assert decompress_block(compress_block(lz4_payload, 3), 3, len(lz4_payload))[0] == lz4_payload
            assert decompress_block(compress_block(lz4_payload, 1), 1, len(lz4_payload))[0] == lz4_payload

        check("unityfs", check_unityfs)

        def check_serialized_alias() -> None:
            info = serialized_bundle_info(serialized)
            assert info["asset_bundle"]["container_count"] == 2
            assert info["asset_bundle"]["assetbundle_name"] == "orig_bundle"
            patched, report = alias_inject_bundle(bundle_lz4, ["_skin_selftest_", "_skin01_selftest_"])
            assert report["container_count_before"] == 2
            assert report["container_count_after"] == 4
            assert report["aliases_added"] == ["_skin_selftest_", "_skin01_selftest_"]
            parsed = read_unityfs_bytes(patched, "patched")
            payload = node_bytes(parsed, parsed["nodes"][0])
            after = serialized_bundle_info(payload)
            paths = [entry["asset_path"] for entry in after["asset_bundle"]["containers"]]
            assert "_skin_selftest_" in paths and "_skin01_selftest_" in paths
            renamed, report2 = alias_inject_bundle(bundle_raw, [], new_name="renamed_bundle")
            parsed2 = read_unityfs_bytes(renamed, "renamed")
            renamed_info = serialized_bundle_info(node_bytes(parsed2, parsed2["nodes"][0]))
            assert report2["assetbundle_name_after"] == "renamed_bundle"
            assert renamed_info["asset_bundle"]["assetbundle_name"] == "renamed_bundle"
            deduped, report3 = alias_inject_bundle(bundle_raw, ["_skin_selftest_", "_skin_selftest_"])
            assert report3["container_count_delta"] == 1
            assert report3["aliases_skipped"] == ["_skin_selftest_"]

        check("serialized_alias", check_serialized_alias)

        def check_xml() -> None:
            a = "<root><!--keep--><a x='1'>hi</a></root>"
            b = "<root><a x='2'>ho</a><b/></root>"
            pretty = xml_pretty(a)
            assert "<!--keep-->" in pretty
            diffs = xml_diff(a, b)
            assert diffs
            merged = xml_merge(a, b)
            assert "<b" in merged
            ok, _ = xml_validate(a)
            assert ok
            ok, _ = xml_validate("<root>")
            assert not ok
            ok, _ = xml_validate(a, "<xs:schema xmlns:xs='http://www.w3.org/2001/XMLSchema'><xs:element name='root'/></xs:schema>")
            assert ok

        check("xml", check_xml)

        def check_json() -> None:
            a = '{"a": 1, "b": [1, 2]}'
            b = '{"a": 2, "c": true}'
            assert '"a": 1' in json_pretty(a)
            diffs = json_diff(a, b)
            paths = {item["path"] for item in diffs}
            assert "$.a" in paths and "$.c" in paths
            merged = json.loads(json_merge(a, b))
            assert merged["a"] == 2 and merged["c"] is True
            ok, _ = json_validate(a)
            assert ok
            ok, _ = json_validate("{", None)
            assert not ok
            ok, _ = json_validate(a, '{"required": ["a"], "types": {"a": "int"}}')
            assert ok
            ok, _ = json_validate(a, '{"required": ["missing"]}')
            assert not ok

        check("json", check_json)

        def check_templates() -> None:
            for template in LUA_TEMPLATES:
                source, ext = gen_template("lua", template)
                assert source and ext == ".lua" and validate_lua(source)[0]
            for template in FRIDA_TEMPLATES:
                source, ext = gen_template("frida", template)
                assert source and ext == ".js" and validate_js(source)[0]
            source, ext = gen_template("cpp", "stub", "selftest_hook")
            assert source and ext == ".cpp" and validate_cpp(source)[0]
            for template in PYTHON_TEMPLATES:
                source, ext = gen_template("python", template)
                assert source and ext == ".py" and validate_python(source)[0]
            assert validate_js(metadata_dump_frida_script())[0]

        check("templates", check_templates)

        files_root = tmp_root / "files"
        assets_root = files_root / "dragon2017" / "assets"
        assets_root.mkdir(parents=True)
        (assets_root / "heroes").mkdir()
        (assets_root / "config").mkdir()
        atomic_write(assets_root / "heroes" / "hero_fanny.unity3d", bundle_raw)
        atomic_write(assets_root / "config" / "items.xml", b"<items><item id='1'/></items>")
        atomic_write(assets_root / "config" / "items-copy.xml", b"<items><item id='1'/></items>")
        mini_root = files_root / "mini_patch"
        (mini_root / "assets" / "heroes").mkdir(parents=True)
        atomic_write(mini_root / "assets" / "heroes" / "hero_fanny.unity3d", b"patched-mini-patch")

        def check_assets() -> None:
            index = build_asset_index(files_root)
            assert index["assets_root"] == str(assets_root)
            assert index["file_count"] == 3
            assert index["format_counts"].get("unityfs") == 1
            assert index["shadowed_count"] == 1
            assert index["duplicate_group_count"] == 1
            assert index["mini_patch_root"] == str(mini_root)
            assert "relative_path" in asset_index_csv(index).splitlines()[0]
            assert "files=3" in format_asset_summary(index)

        check("assets", check_assets)

        def check_skin_hero_map() -> None:
            mapping = load_hero_map()
            assert mapping["Fanny"] == "hero_fanny" and mapping["Brody"] == "hero_feiden"
            override = tmp_root / "hero-map.json"
            atomic_write(override, json.dumps({"Fanny": "hero_override"}).encode("utf-8"))
            assert resolve_hero_prefix("Fanny", override) == "hero_override"
            assert resolve_hero_prefix("fanny") == "hero_fanny"
            assert resolve_hero_prefix("hero_explicit") == "hero_explicit"
            assert classify_skin_role("hero_x_skin.mesh") == "skin mesh"
            assert classify_skin_role("hero_x_shadow_high_add.mesh") == "_shadow_high_add"

        check("skin_hero_map", check_skin_hero_map)

        def check_skin_apply() -> None:
            source = tmp_root / "skin-src"
            target = tmp_root / "skin-target"
            source.mkdir()
            target.mkdir()
            atomic_write(source / "hero_test.mesh", b"new-base")
            atomic_write(source / "hero_test_skin.mesh", b"new-skin")
            atomic_write(source / "hero_test_add.mesh", b"new-add")
            atomic_write(target / "hero_test_skin.mesh", b"old-skin")
            atomic_write(target / "notes.txt", b"untouched")
            plan = skin_plan(source, target, "hero_test")
            actions = {entry["relative_path"]: entry for entry in plan["actions"]}
            assert plan["base_mesh_present"] is True
            assert actions["hero_test_skin.mesh"]["action"] == "replace"
            assert actions["hero_test_add.mesh"]["action"] == "create"
            out = tmp_root / "skin-out"
            result = skin_apply(plan, out)
            assert result["applied"] and result["backup_count"] == 1
            assert (target / "hero_test_skin.mesh").read_bytes() == b"new-skin"
            assert (target / "notes.txt").read_bytes() == b"untouched"
            assert (out / "restore.py").is_file() and (out / "skinswap-manifest.json").is_file()
            restore = run([sys.executable, str(out / "restore.py")], timeout=30)
            assert restore.returncode == 0, restore.stderr.decode("utf-8", errors="replace")
            assert (target / "hero_test_skin.mesh").read_bytes() == b"old-skin"
            assert not (target / "hero_test_add.mesh").exists()
            shadow_source = tmp_root / "shadow-src"
            shadow_source.mkdir()
            atomic_write(shadow_source / "hero_test_shadow_add.mesh", b"shadow")
            shadow_plan = skin_plan(shadow_source, target, "hero_test")
            kinds = {risk["kind"] for risk in shadow_plan["risks"]}
            assert "fallback-sphere" in kinds and "shadow-without-add" in kinds

        check("skin_apply_restore", check_skin_apply)

        def check_skin_mini_patch() -> None:
            source = tmp_root / "skin-sync-src"
            source.mkdir()
            atomic_write(source / "hero_sync_skin.mesh", b"sync-new")
            target = assets_root
            plan = skin_plan(source, target, "hero_sync", sync_mini_patch=True)
            action = plan["actions"][0]
            assert plan["mini_patch_root"] == str(mini_root)
            assert action["mirrors"] and action["mirrors"][0].endswith("hero_sync_skin.mesh")
            out = tmp_root / "skin-sync-out"
            result = skin_apply(plan, out)
            assert result["created_count"] == 1
            mirror = Path(action["mirrors"][0])
            assert mirror.read_bytes() == b"sync-new"
            restore = run([sys.executable, str(out / "restore.py")], timeout=30)
            assert restore.returncode == 0, restore.stderr.decode("utf-8", errors="replace")
            assert not mirror.exists()
            assert not (target / "hero_sync_skin.mesh").exists()

        check("skin_mini_patch", check_skin_mini_patch)

        def check_cache_integrity() -> None:
            cache_target = tmp_root / "cache-target"
            (cache_target / "cache").mkdir(parents=True)
            atomic_write(cache_target / "cache" / "empty.bin", b"")
            atomic_write(cache_target / "cache" / "a.bin", b"same")
            atomic_write(cache_target / "cache" / "b.bin", b"same")
            result = _skin_cache_integrity(cache_target)
            assert result is not None and result["healthy"] is False
            assert result["zero_byte_count"] == 1
            assert result["duplicate_group_count"] == 1

        check("cache_integrity", check_cache_integrity)

        def check_resmap() -> None:
            table = tmp_root / "mulonggame_table_1"
            atomic_write(table, struct.pack("<II", 10, 20))
            found = find_resmap_table(tmp_root)
            assert found == table
            entries = resmap_entries(table.read_bytes())
            assert [entry["value"] for entry in entries] == [10, 20]
            edited = resmap_edit(table, 1, 99)
            assert edited["old_value"] == 20 and edited["new_value"] == 99
            assert (table.with_name(table.name + ".bak")).is_file()
            assert read_u32_le(table.read_bytes(), 4) == 99
            restored = resmap_restore(table)
            assert restored["restored"] and read_u32_le(table.read_bytes(), 4) == 20
            report = resmap_report(table, resmap_entries(table.read_bytes()))
            assert report["entry_count"] == 2 and report["entry_stride"] == 4

        check("resmap", check_resmap)

        def check_surface_map() -> None:
            keywords = tmp_root / "keywords.txt"
            atomic_write(keywords, b"# selftest\nshitsuke\nSHITSUKE_SE\nmissing_keyword\n")
            result = build_surface_map(elf_path, keywords)
            assert result["keyword_count"] == 3
            assert result["groups"]["shitsuke"]["hits"] > 0
            assert result["groups"]["missing_keyword"]["hits"] == 0
            assert "keyword" in surface_map_csv(result).splitlines()[0]
            exact = build_surface_map(elf_path, keywords, exact=True)
            assert exact["groups"]["SHITSUKE_SE"]["hits"] == 0
            regex = build_surface_map(elf_path, keywords, use_regex=True)
            assert regex["mode"] == "regex"
            frida_path = tmp_root / "surface-resolver.js"
            emit_surface_frida(result, frida_path)
            assert frida_path.is_file() and validate_js(frida_path.read_text(encoding="utf-8"))[0]

        check("surface_map", check_surface_map)

        def check_menu() -> None:
            out = tmp_root / "modmenu"
            written = emit_mod_menu(out, "com.shitsuke.selftest")
            assert len(written) > 20
            activity = out / "app/src/main/java/com/shitsuke/selftest/MainActivity.java"
            assert activity.is_file()
            text = activity.read_text(encoding="utf-8")
            assert "System.loadLibrary(\"menu\")" in text
            assert "nativeMenuSetFeature" in text and "nativeMenuSetSeek" in text
            assert (out / "manifest.json").is_file()
            manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
            assert any(entry["path"] == "app/src/main/jni/Main.cpp" for entry in manifest)

        check("menu", check_menu)

        def check_adb() -> None:
            fake = tmp_root / "fakeadb.sh"
            _selftest_fake_adb(fake)
            assert resolve_adb(str(fake)) == str(fake)
            devices = adb_devices(str(fake))
            assert devices == [{"serial": "emulator-5554", "state": "device"}]
            shell = adb_shell(str(fake), None, ["echo", "hello"], timeout=10)
            assert shell.stdout.strip() == b"hello"
            assert adb_pidof(str(fake), None) == 4242
            env = env_probe(str(fake), None)
            assert env["ro.build.version.sdk"] == "30"
            assert env["selinux"] == "Enforcing"
            assert env["su_available"] is True
            assert "DEVICE PROFILE" in format_env_profile(env)
            steps = wireless_adb_steps()
            assert "adb pair" in steps and "adb connect" in steps

        check("adb_shizuku_helpers", check_adb)

        def check_archive_helpers() -> None:
            target = tmp_root / "atomic.txt"
            atomic_write(target, b"hello")
            assert target.read_bytes() == b"hello"
            assert sha256_file(target) == sha256_bytes(b"hello")
            json_path = tmp_root / "doc.json"
            write_json(json_path, {"ok": True})
            assert json.loads(json_path.read_text(encoding="utf-8"))["ok"] is True
            try:
                require_file(tmp_root / "missing", "selftest")
            except ToolIOError:
                pass
            else:
                raise AssertionError("require_file did not raise")

        check("io_helpers", check_archive_helpers)
    finally:
        shutil.rmtree(tmp_root, ignore_errors=True)
    print("")
    print("selftest: %d passed, %d failed" % (passed, failed))
    if failed:
        for name, message in failures:
            print("  failed: %s -> %s" % (name, message))
        return EXIT_SELFTEST
    return EXIT_OK

# 99 dispatch/main
def _write_bytes(args: argparse.Namespace, path: Union[str, Path], data: bytes) -> Optional[Path]:
    """Write bytes unless --dry-run is active."""
    if getattr(args, "dry_run", False):
        info("dry-run", "would write %s" % path)
        return None
    return atomic_write(path, data)


def _write_json(args: argparse.Namespace, path: Union[str, Path], obj: Any) -> Optional[Path]:
    """Write a JSON document unless --dry-run is active."""
    if getattr(args, "dry_run", False):
        info("dry-run", "would write %s" % path)
        return None
    return write_json(path, obj)


def _read_text(path: Union[str, Path], subsystem: str) -> str:
    p = require_file(path, subsystem)
    try:
        return p.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        raise ToolIOError(subsystem, "cannot read %s: %s" % (p, exc))


def _out_base(args: argparse.Namespace) -> Path:
    """Return the output directory without creating it during --dry-run."""
    if getattr(args, "dry_run", False):
        return Path(args.out) if args.out else Path(".")
    return out_dir(args)


def _target_path(args: argparse.Namespace, filename: str) -> Path:
    """Resolve an output filename without creating directories during --dry-run."""
    if args.out:
        base = Path(args.out)
        if base.suffix or (base.exists() and base.is_file()):
            return base
        return base / filename
    return Path(filename)



def _sanitize_node_path(name: str) -> Path:
    parts = [part for part in name.replace("\\", "/").split("/")
             if part and part not in (".", "..")]
    if not parts:
        raise ParseError("unityfs", "empty node path")
    return Path(*parts)


def _console(obj: Any) -> None:
    sys.stdout.write(str(obj) + "\n")
    sys.stdout.flush()


def _table(rows: Sequence[Sequence[Any]], headers: Sequence[str]) -> str:
    widths = [len(header) for header in headers]
    for row in rows:
        for index, value in enumerate(row):
            widths[index] = max(widths[index], len(str(value)))
    lines = ["  ".join(str(headers[i]).ljust(widths[i]) for i in range(len(headers)))]
    lines.append("  ".join("-" * width for width in widths))
    for row in rows:
        lines.append("  ".join(str(row[i]).ljust(widths[i]) for i in range(len(headers))))
    return "\n".join(lines)


def cmd_banner(args: argparse.Namespace) -> int:
    info("banner", "%s %s" % (TOOL_NAME, TOOL_VERSION))
    info("banner", "target=%s assets=%s" % (APP_PKG, ASSET_ROOT))
    return EXIT_OK


def cmd_recon(args: argparse.Namespace) -> int:
    result = resolve_targets(args.path)
    if JSON_MODE:
        emit_json(result)
        return EXIT_OK
    _console("=== RECON ===")
    _console("root=%s abi=%s" % (result["root"], ", ".join(result["abi_dirs"]) or "(none)"))
    for item in result["found"]:
        _console("%s  abi=%s arch=%s size=%s sha256=%s" %
                 (item["name"], item.get("abi"), item.get("arch"),
                  human_size(item["size"]), item["sha256"]))
    if result["missing"]:
        _console("missing: " + ", ".join(result["missing"]))
    return EXIT_OK


def cmd_elf(args: argparse.Namespace) -> int:
    elf = parse_elf(args.path)
    if JSON_MODE:
        emit_json(elf)
        return EXIT_OK
    _console("=== ELF ===")
    _console("%s %s %s endian=%s size=%s" % (elf["class"], elf["type_name"], elf["arch"],
                                             elf["endian"], human_size(elf["size"])))
    _console("sha256=%s entry=0x%x sections=%d symbols=%d" %
             (elf["sha256"], elf["entry"], elf["section_header_count"], len(elf["symbols"])))
    rows = [(section["index"], section["name"] or "(null)", section["type_name"],
             "".join(section["flags_list"]) or "-", "0x%x" % section["addr"],
             human_size(section["size"])) for section in elf["sections"]]
    if rows:
        _console(_table(rows, ("idx", "name", "type", "flags", "addr", "size")))
    return EXIT_OK


def cmd_metadata(args: argparse.Namespace) -> int:
    path = require_file(args.path, "metadata")
    data = path.read_bytes()
    report = metadata_report(data, args.recover, path.parent)
    payload = data
    header = report.get("header")
    if args.recover:
        found = metadata_recover(data, path.parent)
        payload = found.get("data") or data
        header = found.get("header")
        report["recovery"] = {key: value for key, value in found.items() if key not in ("data", "script")}
        if found.get("script") and not args.frida_out:
            report["recovery"]["script_available"] = True
    if args.export:
        if header is None:
            raise ParseError("metadata", "no metadata header available to export")
        written = export_metadata_reference(payload, header, Path(args.export), path,
                                            report.get("recovery"))
        info("metadata", "exported %d file(s) to %s" % (len(written), args.export))
    if args.frida_out:
        _write_bytes(args, args.frida_out, metadata_dump_frida_script().encode("utf-8"))
        info("metadata", "wrote rung-8 Frida dumper to %s" % args.frida_out)
    if JSON_MODE:
        emit_json(report)
        return EXIT_OK
    _console("=== METADATA ===")
    _console("file=%s size=%s sha256=%s" % (path, human_size(len(data)), report["input_sha256"]))
    if header is None:
        _console("header=unavailable recovery_rung=%s confidence=%s" %
                 (report["recovery"].get("rung"), report["recovery"].get("confidence")))
        _console("next: run the generated Frida dumper against %s" % APP_PKG)
        return EXIT_OK
    _console("version=%d stride=%d header=%d bytes" %
             (header["version"], header["header_stride"], header["header_size"]))
    counts = header.get("counts", {})
    _console("string_literals=%d type_definitions=%d images=%d assemblies=%d" %
             (header["stringLiteral_count"], header["typeDefinition_count"],
              counts.get("image_count", 0), counts.get("assembly_count", 0)))
    _console("recovery=%s (%s)" % (report["recovery"].get("description"), report["recovery"].get("confidence")))
    rows = [(name, "0x%x" % section["offset"], human_size(section["size"]), "%.2f%%" % section["pct"])
            for name, section in header["sections"].items() if section["size"]]
    if rows:
        _console(_table(rows, ("section", "offset", "size", "share")))
    return EXIT_OK


def cmd_scan(args: argparse.Namespace) -> int:
    path = require_file(args.path, "scan")
    data = path.read_bytes()
    elf_info = None
    if data.startswith(ELF_MAGIC):
        try:
            elf_info = parse_elf(path)
        except ShitsukeError:
            elf_info = None
    hits = aob_hits(data, args.pattern, args.context, elf_info)
    report = {"path": str(path), "size": len(data), "sha256": sha256_bytes(data),
              "pattern": args.pattern, "hit_count": len(hits), "hits": hits,
              "context_bytes": args.context}
    if args.out:
        out = _out_base(args)
        _write_json(args, out / "scan-hits.json", report)
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow(["offset", "vaddr", "section", "match", "context_before", "context_after"])
        for hit in hits:
            writer.writerow([hit["offset"], hit["vaddr"], hit["section"], hit["match"],
                             hit["context_before"], hit["context_after"]])
        _write_bytes(args, out / "scan-hits.csv", buf.getvalue().encode("utf-8"))
    if JSON_MODE:
        emit_json(report)
        return EXIT_OK
    _console("=== AOB SCAN ===")
    _console("pattern=%s hits=%d" % (args.pattern, len(hits)))
    for hit in hits[:200]:
        _console("  0x%08x vaddr=%s section=%s match=%s" %
                 (hit["offset"], ("0x%x" % hit["vaddr"]) if hit["vaddr"] else "-",
                  hit["section"] or "-", hit["match"]))
    if len(hits) > 200:
        _console("  ... %d more (write with --out)" % (len(hits) - 200))
    return EXIT_OK


def cmd_strings(args: argparse.Namespace) -> int:
    report = strings_report(args.path, args.min)
    if args.out:
        out = _out_base(args)
        _write_json(args, out / "strings.json", report)
        _write_bytes(args, out / "strings.csv", strings_csv(report["strings"]).encode("utf-8"))
    if JSON_MODE:
        summary = {key: value for key, value in report.items() if key != "strings"}
        summary["strings"] = report["strings"][:200]
        summary["strings_truncated"] = len(report["strings"]) > 200
        emit_json(summary)
        return EXIT_OK
    _console("=== STRINGS ===")
    _console("path=%s size=%s strings=%d symbols=%d" %
             (report["path"], human_size(report["size"]), report["string_count"],
              report["symbol_count"]))
    for item in report["strings"][:25]:
        _console("  0x%08x %-7s %s" % (item["offset"], item["encoding"], item["value"][:120]))
    for symbol in report["symbols"][:25]:
        _console("  sym %-8s %s value=0x%x" % (symbol["type_name"], symbol["name"], symbol["value"]))
    return EXIT_OK


def cmd_assets(args: argparse.Namespace) -> int:
    index = build_asset_index(args.root, args.mini_patch)
    if args.out:
        out = _out_base(args)
        _write_json(args, out / "assets-index.json", index)
        _write_bytes(args, out / "assets-index.csv", asset_index_csv(index).encode("utf-8"))
    if JSON_MODE:
        summary = {key: value for key, value in index.items() if key != "entries"}
        summary["entries"] = index["entries"][:100]
        summary["entries_truncated"] = len(index["entries"]) > 100
        emit_json(summary)
        return EXIT_OK
    _console(format_asset_summary(index))
    for entry in index["shadowed"][:10]:
        _console("  shadow %s -> %s" % (entry["relative_path"], entry["mini_patch"]["path"]))
    return EXIT_OK


def cmd_unityfs(args: argparse.Namespace) -> int:
    bundle = read_unityfs(args.path)
    summary = {
        "path": bundle["path"], "file_size": bundle["file_size"], "sha256": bundle["sha256"],
        "format_version": bundle["header"]["format_version"],
        "player_version": bundle["header"]["player_version"],
        "engine_version": bundle["header"]["engine_version"],
        "flags": bundle["header"]["flags"], "compression": bundle["header"]["compression"],
        "compression_paths": bundle["compression_paths"],
        "blocks": bundle["blocks"],
        "nodes": [{"offset": node["offset"], "size": node["size"],
                   "flags": node["flags"], "path": node["path"]} for node in bundle["nodes"]],
        "serialized": [],
    }
    if args.serialized:
        for node in bundle["nodes"]:
            try:
                info = serialized_bundle_info(node_bytes(bundle, node))
            except ShitsukeError as exc:
                summary["serialized"].append({"path": node["path"], "error": str(exc)})
            else:
                summary["serialized"].append({"path": node["path"], "info": info})
    if args.extract:
        extract_root = Path(args.extract)
        extracted: List[str] = []
        for node in bundle["nodes"]:
            rel = _sanitize_node_path(node["path"])
            destination = extract_root / rel
            _write_bytes(args, destination, node_bytes(bundle, node))
            extracted.append(str(destination))
        summary["extracted"] = extracted
        if JSON_MODE:
            info("unityfs", "extracted %d node(s) to %s" % (len(extracted), extract_root))
    if args.out:
        _write_json(args, _out_base(args) / "unityfs-summary.json", summary)
    if JSON_MODE:
        emit_json(summary)
        return EXIT_OK
    _console("=== UNITYFS ===")
    _console("path=%s size=%s sha256=%s" % (summary["path"], human_size(summary["file_size"]),
                                             summary["sha256"]))
    _console("format=%d player=%s engine=%s flags=0x%x compression=%d" %
             (summary["format_version"], summary["player_version"], summary["engine_version"],
              summary["flags"], summary["compression"]))
    rows = [(node["path"], human_size(node["size"]), "0x%x" % node["flags"]) for node in summary["nodes"]]
    if rows:
        _console(_table(rows, ("node", "size", "flags")))
    for entry in summary["serialized"]:
        if "error" in entry:
            _console("  serialized %s: %s" % (entry["path"], entry["error"]))
            continue
        ab = entry["info"]["asset_bundle"]
        _console("  serialized %s objects=%d asset_bundle=%s containers=%s" %
                 (entry["path"], entry["info"]["object_count"],
                  (ab or {}).get("assetbundle_name"), (ab or {}).get("container_count")))
    return EXIT_OK


def cmd_skin(args: argparse.Namespace) -> int:
    if args.prefix:
        prefix = args.prefix
        if not re.fullmatch(r"[A-Za-z0-9_]+", prefix):
            raise UsageError("skin", "invalid prefix %r" % prefix)
    elif args.hero:
        prefix = resolve_hero_prefix(args.hero, args.hero_map)
    else:
        raise UsageError("skin", "provide --hero NAME, --prefix PREFIX, or both")
    plan = skin_plan(args.source, args.target, prefix, args.hero_map,
                     args.sync_mini_patch, args.mini_patch_root)
    if args.apply:
        stamp = time.strftime("%Y%m%d-%H%M%S")
        out = Path(args.out) if args.out else Path("skinswap-backup-" + stamp)
        result = skin_apply(plan, out, force=args.force, dry_run=args.dry_run)
        result["prefix"] = prefix
        result["risks"] = plan["risks"]
        result["cache"] = plan["cache"]
        if JSON_MODE:
            emit_json(result)
            return EXIT_OK
        _console("=== SKIN APPLY ===")
        _console("applied=%s changed=%d created=%d backups=%d risks=%d" %
                 (result["applied"], result["changed_count"], result["created_count"],
                  result["backup_count"], result["risk_count"]))
        _console("backup_dir=%s" % result["backup_dir"])
        for risk in plan["risks"]:
            _console("  risk [%s] %s" % (risk["kind"], risk.get("detail", "")))
        return EXIT_OK
    if args.out:
        _write_json(args, _out_base(args) / "skinswap-plan.json", plan)
    if JSON_MODE:
        emit_json(plan)
        return EXIT_OK
    _console("=== SKIN PLAN ===")
    _console("prefix=%s source=%s target=%s" % (plan["prefix"], plan["source"], plan["target"]))
    for action in plan["actions"]:
        _console("  %-9s %-14s %s" % (action["action"], action["role"], action["relative_path"]))
        for mirror in action["mirrors"]:
            _console("    mirror -> %s" % mirror)
    for risk in plan["risks"]:
        _console("  risk [%s] %s" % (risk["kind"], risk.get("detail", "")))
    if plan["cache"] is not None:
        _console("cache files=%d healthy=%s" % (plan["cache"]["file_count"],
                                                 plan["cache"]["healthy"]))
    if not args.apply:
        _console("plan only; re-run with --apply to back up and write")
    return EXIT_OK


def _alias_mini_patch_path(args: argparse.Namespace, bundle_path: Path,
                           output: Path) -> Path:
    asset_root = Path(args.asset_root) if args.asset_root else bundle_path.parent
    if args.mini_patch_root:
        mini_root = Path(args.mini_patch_root)
        if not args.dry_run:
            mini_root.mkdir(parents=True, exist_ok=True)
    else:
        candidates = [asset_root / "mini_patch", asset_root.parent / "mini_patch",
                      asset_root.parent.parent / "mini_patch"]
        mini_root = next((candidate for candidate in candidates if candidate.is_dir()), None)
        if mini_root is None:
            mini_root = asset_root.parent / "mini_patch"
    rel = None
    for candidate in (bundle_path, output):
        try:
            rel = candidate.resolve().relative_to(asset_root.resolve())
            break
        except ValueError:
            continue
    if rel is None:
        raise UsageError("alias", "--asset-root must contain the bundle or output path "
                                  "so mini_patch mirrors can be mapped")
    mirror = mini_root / "assets" / rel
    if (mini_root / rel).exists() and not (mini_root / "assets").is_dir():
        mirror = mini_root / rel
    return mirror


def cmd_alias(args: argparse.Namespace) -> int:
    path = require_file(args.path, "alias")
    data = path.read_bytes()
    output = Path(args.output) if args.output else path.with_name(path.name + ".patched")
    if output.resolve() == path.resolve() and not args.force:
        raise ToolIOError("alias", "refusing to overwrite input without --force: %s" % path)
    patched, report = alias_inject_bundle(data, args.aliases, args.set_name)
    written: List[str] = []
    if _write_bytes(args, output, patched) is not None:
        written.append(str(output))
    mirror = None
    if args.sync_mini_patch:
        mirror = _alias_mini_patch_path(args, path, output)
        if _write_bytes(args, mirror, patched) is not None:
            written.append(str(mirror))
    report["input"] = str(path)
    report["output"] = str(output)
    report["mini_patch_mirror"] = str(mirror) if mirror else None
    report["written"] = written
    report["dry_run"] = bool(args.dry_run)
    if JSON_MODE:
        emit_json(report)
        return EXIT_OK
    _console("=== ALIAS INJECT ===")
    _console("input=%s output=%s" % (path, output))
    _console("containers %d -> %d (+%d), size %s -> %s" %
             (report["container_count_before"], report["container_count_after"],
              report["container_count_delta"], human_size(report["original_size"]),
              human_size(report["new_size"])))
    _console("aliases_added=%s skipped=%s" % (report["aliases_added"], report["aliases_skipped"]))
    if report["assetbundle_name_before"] != report["assetbundle_name_after"]:
        _console("bundle name: %s -> %s" % (report["assetbundle_name_before"],
                                             report["assetbundle_name_after"]))
    if mirror:
        _console("mini_patch mirror=%s" % mirror)
    return EXIT_OK


def cmd_resmap(args: argparse.Namespace) -> int:
    table = find_resmap_table(args.path, args.table_name)
    if args.restore and (args.index is not None or args.skin_id is not None):
        raise UsageError("resmap", "--restore cannot be combined with --index/--skin-id")
    if args.restore:
        result = resmap_restore(table)
        result["mode"] = "restore"
    elif args.index is None or args.skin_id is None:
        entries = resmap_entries(table.read_bytes())
        result = resmap_report(table, entries)
        result["mode"] = "list"
    else:
        result = resmap_edit(table, args.index, args.skin_id, force=args.force,
                             dry_run=args.dry_run)
        result["mode"] = "edit"
    if JSON_MODE:
        emit_json(result)
        return EXIT_OK
    _console("=== RESMAP ===")
    _console("table=%s mode=%s" % (table, result["mode"]))
    if result["mode"] == "list":
        _console("entries=%d stride=%d nonzero=%d" %
                 (result["entry_count"], result["entry_stride"], result["nonzero_count"]))
        for entry in result["preview"][:32]:
            _console("  [%04d] %d" % (entry["index"], entry["value"]))
    elif result["mode"] == "edit":
        _console("index=%d %d -> %d dry_run=%s" %
                 (result["index"], result["old_value"], result["new_value"], result["dry_run"]))
        _console("backup=%s created=%s reused=%s" %
                 (result["backup"], result["backup_created"], result["backup_reused"]))
    else:
        _console("restored %s from %s" % (table, result["backup"]))
    return EXIT_OK


def _xml_schema(args: argparse.Namespace) -> Optional[str]:
    return _read_text(args.schema, "xml") if args.schema else None


def cmd_xml(args: argparse.Namespace) -> int:
    a = _read_text(args.a, "xml")
    if args.mode in ("diff", "merge") and not args.b:
        raise UsageError("xml", "%s requires two files" % args.mode)
    b = _read_text(args.b, "xml") if args.b else ""
    if args.mode == "pretty":
        result = xml_pretty(a, keep_comments=not args.no_comments)
        if args.out:
            _write_bytes(args, _target_path(args, Path(args.a).stem + ".pretty.xml"),
                         result.encode("utf-8"))
        else:
            sys.stdout.write(result if result.endswith("\n") else result + "\n")
        return EXIT_OK
    if args.mode == "diff":
        diffs = xml_diff(a, b)
        if args.out:
            _write_json(args, _out_base(args) / "xml-diff.json", diffs)
        if JSON_MODE:
            emit_json(diffs)
        else:
            _console("=== XML DIFF ===")
            for item in diffs:
                _console("  %s %s" % (item.get("change"), item.get("path")))
            _console("differences=%d" % len(diffs))
        return EXIT_OK
    if args.mode == "merge":
        merged = xml_merge(a, b)
        if args.out:
            _write_bytes(args, _target_path(args, Path(args.a).stem + ".merged.xml"),
                         merged.encode("utf-8"))
        else:
            sys.stdout.write(merged if merged.endswith("\n") else merged + "\n")
        return EXIT_OK
    ok, message = xml_validate(a, _xml_schema(args))
    if JSON_MODE:
        emit_json({"valid": ok, "message": message, "path": args.a})
    else:
        _console(("OK " if ok else "INVALID ") + message)
    if not ok:
        raise ParseError("xml", message)
    return EXIT_OK


def cmd_json(args: argparse.Namespace) -> int:
    a = _read_text(args.a, "json")
    if args.mode in ("diff", "merge") and not args.b:
        raise UsageError("json", "%s requires two files" % args.mode)
    b = _read_text(args.b, "json") if args.b else ""
    if args.mode == "pretty":
        result = json_pretty(a)
        if args.out:
            _write_bytes(args, _target_path(args, Path(args.a).stem + ".pretty.json"),
                         result.encode("utf-8"))
        else:
            sys.stdout.write(result)
        return EXIT_OK
    if args.mode == "diff":
        diffs = json_diff(a, b)
        if args.out:
            _write_json(args, _out_base(args) / "json-diff.json", diffs)
        if JSON_MODE:
            emit_json(diffs)
        else:
            _console("=== JSON DIFF ===")
            for item in diffs:
                _console("  %s %s" % (item.get("change"), item.get("path")))
            _console("differences=%d" % len(diffs))
        return EXIT_OK
    if args.mode == "merge":
        merged = json_merge(a, b)
        if args.out:
            _write_bytes(args, _target_path(args, Path(args.a).stem + ".merged.json"),
                         merged.encode("utf-8"))
        else:
            sys.stdout.write(merged)
        return EXIT_OK
    schema = _read_text(args.schema, "json") if args.schema else None
    ok, message = json_validate(a, schema)
    if JSON_MODE:
        emit_json({"valid": ok, "message": message, "path": args.a})
    else:
        _console(("OK " if ok else "INVALID ") + message)
    if not ok:
        raise ParseError("json", message)
    return EXIT_OK


def cmd_gen(args: argparse.Namespace) -> int:
    source, extension = gen_template(args.kind, args.template, args.name)
    filename = "%s%s" % (args.template, extension)
    if args.out:
        destination = _target_path(args, filename)
        written = _write_bytes(args, destination, source.encode("utf-8"))
        if JSON_MODE:
            emit_json({"kind": args.kind, "template": args.template,
                       "path": str(destination), "written": written is not None,
                       "bytes": len(source.encode("utf-8")), "valid": True})
        else:
            info("gen", "wrote %s (%d bytes, validated)" % (destination, len(source.encode("utf-8"))))
    else:
        sys.stdout.write(source if source.endswith("\n") else source + "\n")
    return EXIT_OK


def cmd_adb(args: argparse.Namespace) -> int:
    adb = resolve_adb(args.adb)
    if not args.adb_cmd:
        raise UsageError("adb", "choose a subcommand: devices, shell, push, pull, logcat, "
                                "pidof, dumpsys, bugreport, wireless")
    if args.adb_cmd == "devices":
        devices = adb_devices(adb)
        if JSON_MODE:
            emit_json({"adb": adb, "devices": devices})
        else:
            _console("=== ADB DEVICES ===")
            for device in devices:
                _console("  %-24s %s" % (device["serial"], device["state"]))
            if not devices:
                _console("  (none)")
        return EXIT_OK
    if args.adb_cmd == "shell":
        command = list(args.command)
        if command and command[0] == "--":
            command = command[1:]
        if not command:
            raise UsageError("adb", "shell requires a command")
        cp = run([adb] + (["-s", args.device] if args.device else []) + ["shell"] + command,
                 timeout=120)
        sys.stdout.write(cp.stdout.decode("utf-8", errors="replace"))
        sys.stderr.write(cp.stderr.decode("utf-8", errors="replace"))
        return cp.returncode
    if args.adb_cmd in ("push", "pull"):
        if args.adb_cmd == "push":
            result = adb_push(adb, args.device, args.src, args.dst)
        else:
            result = adb_pull(adb, args.device, args.src, args.dst)
        if JSON_MODE:
            emit_json(result)
        else:
            _console("=== ADB %s ===" % args.adb_cmd.upper())
            _console("src=%s dst=%s" % (result["src"], result["dst"]))
            _console("sha256_local=%s remote=%s verified=%s" %
                     (result["sha256_local"], result["sha256_remote"], result["verified"]))
        return EXIT_OK
    if args.adb_cmd == "logcat":
        text = adb_logcat(adb, args.device, args.tag, args.pid, args.regex,
                          args.tail, args.duration)
        if args.out:
            _write_bytes(args, _target_path(args, "logcat.txt"), text.encode("utf-8"))
        else:
            sys.stdout.write(text)
        return EXIT_OK
    if args.adb_cmd == "pidof":
        pid = adb_pidof(adb, args.device)
        if JSON_MODE:
            emit_json({"package": APP_PKG, "pid": pid})
        else:
            _console("%s pid=%s" % (APP_PKG, pid if pid is not None else "(not running)"))
        return EXIT_OK
    if args.adb_cmd == "dumpsys":
        if args.what == "window":
            result = adb_dumpsys_window(adb, args.device)
        else:
            result = adb_dumpsys_package(adb, args.device)
        if JSON_MODE:
            emit_json(result)
        else:
            _console("=== DUMPSYS %s ===" % args.what.upper())
            for key, value in result.items():
                if value is None:
                    continue
                if isinstance(value, (dict, list)):
                    _console("%s=%s" % (key, json.dumps(value)))
                else:
                    _console("%s=%s" % (key, value))
        return EXIT_OK
    if args.adb_cmd == "bugreport":
        destination = adb_bugreport(adb, args.device, Path(args.output).parent if args.output
                                    else Path("."))
        info("adb", "bugreport saved under %s" % destination)
        return EXIT_OK
    if args.adb_cmd == "wireless":
        if args.pair or args.connect:
            result = wireless_adb_action(adb, args.pair, args.code, args.connect)
            if JSON_MODE:
                emit_json(result)
            else:
                _console(json.dumps(result, indent=2))
        else:
            _console(wireless_adb_steps())
        return EXIT_OK
    raise UsageError("adb", "unknown subcommand: %s" % args.adb_cmd)


def cmd_shizuku(args: argparse.Namespace) -> int:
    adb = resolve_adb(args.adb)
    if args.pair or args.connect:
        result = wireless_adb_action(adb, args.pair, args.code, args.connect)
        if JSON_MODE:
            emit_json(result)
        else:
            _console(json.dumps(result, indent=2))
        return EXIT_OK
    env = env_probe(adb, args.device)
    paths = resolve_paths(adb, args.device)
    shizuku = shizuku_probe(adb, args.device)
    payload = {"adb": adb, "device": args.device, "env": env, "paths": paths, "shizuku": shizuku}
    if JSON_MODE:
        emit_json(payload)
        return EXIT_OK
    _console(format_env_profile(env))
    _console("=== PATHS ===")
    for item in paths:
        _console("  %-18s exists=%-5s rwx=%s %s" %
                 (item["name"], item["exists"], item["rwx"] or "-", item["path"]))
    _console("=== SHIZUKU ===")
    _console("available=%s version=%s start_mode=%s" %
             (shizuku["available"], shizuku["version"], shizuku["start_mode"]))
    if shizuku["fallback"]:
        _console("fallback=%s" % shizuku["fallback"])
    return EXIT_OK


def cmd_menu(args: argparse.Namespace) -> int:
    destination = Path(args.out) if args.out else Path("modmenu")
    if args.dry_run:
        with tempfile.TemporaryDirectory(prefix="shitsuke_menu_") as td:
            written = emit_mod_menu(td, args.pkg)
        result = {"out": str(destination), "file_count": len(written), "dry_run": True,
                  "files": [str(path).replace(td, "<plan>") for path in written]}
        if JSON_MODE:
            emit_json(result)
        else:
            info("menu", "would emit %d file(s) to %s" % (len(written), destination))
        return EXIT_OK
    written = emit_mod_menu(destination, args.pkg)
    result = {"out": str(destination), "file_count": len(written), "dry_run": False,
              "files": [str(path) for path in written]}
    if JSON_MODE:
        emit_json(result)
    else:
        info("menu", "emitted %d file(s) to %s" % (len(written), destination))
    return EXIT_OK


def cmd_map(args: argparse.Namespace) -> int:
    if args.exact and args.regex:
        raise UsageError("map", "--exact and --regex are mutually exclusive")
    result = build_surface_map(args.binary, args.keywords, args.exact, args.regex)
    if args.out:
        out = _out_base(args)
        _write_json(args, out / "surface-map.json", result)
        _write_bytes(args, out / "surface-map.csv", surface_map_csv(result).encode("utf-8"))
    if args.frida_emit:
        destination = _target_path(args, "surface-resolver.js")
        if not args.dry_run:
            emit_surface_frida(result, destination)
        else:
            info("dry-run", "would write %s" % destination)
    if JSON_MODE:
        summary = {key: value for key, value in result.items() if key != "rows"}
        summary["rows"] = result["rows"][:200]
        summary["rows_truncated"] = len(result["rows"]) > 200
        emit_json(summary)
        return EXIT_OK
    _console("=== SURFACE MAP ===")
    _console("mode=%s keywords=%d sources=%d hits=%d truncated=%s" %
             (result["mode"], result["keyword_count"], result["source_count"],
              result["total_hits"], result["truncated"]))
    rows = [(keyword, info["hits"], "%.2f" % info["top_score"], ", ".join(info["types"]) or "-")
            for keyword, info in result["groups"].items()]
    _console(_table(rows, ("keyword", "hits", "top", "types")))
    for row in result["rows"][:15]:
        _console("  %-24s %-8s %s" % (row["keyword"], row["source_type"], row["file"]))
    return EXIT_OK


DISPATCH: Dict[str, Callable[[argparse.Namespace], int]] = {
    "banner": cmd_banner,
    "recon": cmd_recon,
    "elf": cmd_elf,
    "metadata": cmd_metadata,
    "scan": cmd_scan,
    "strings": cmd_strings,
    "assets": cmd_assets,
    "unityfs": cmd_unityfs,
    "skin": cmd_skin,
    "alias": cmd_alias,
    "resmap": cmd_resmap,
    "xml": cmd_xml,
    "json": cmd_json,
    "gen": cmd_gen,
    "adb": cmd_adb,
    "shizuku": cmd_shizuku,
    "menu": cmd_menu,
    "map": cmd_map,
}


def _install_signal_handlers() -> None:
    if hasattr(signal, "SIGPIPE"):
        try:
            signal.signal(signal.SIGPIPE, signal.SIG_DFL)
        except (ValueError, OSError):
            pass


def main(argv: Optional[Sequence[str]] = None) -> int:
    """CLI entry point: banner, parse, dispatch, and map failures to exit codes."""
    global COLOR, VERBOSE, JSON_MODE
    _install_signal_handlers()
    print_banner()
    try:
        parser = make_parser()
        args = parser.parse_args(list(argv) if argv is not None else None)
    except UsageError as exc:
        err(exc.subsystem, str(exc))
        return EXIT_USAGE
    COLOR = not bool(getattr(args, "no_color", False))
    VERBOSE = bool(getattr(args, "verbose", False))
    JSON_MODE = bool(getattr(args, "json_out", False))
    if getattr(args, "selftest_flag", False) or args.cmd == "selftest":
        return run_selftest()
    if not args.cmd:
        parser.print_help()
        return EXIT_USAGE
    handler = DISPATCH.get(args.cmd)
    if handler is None:
        err("cli", "unknown command: %s" % args.cmd)
        return EXIT_USAGE
    try:
        return int(handler(args) or EXIT_OK)
    except UsageError as exc:
        err(exc.subsystem, str(exc))
        return EXIT_USAGE
    except ToolIOError as exc:
        err(exc.subsystem, str(exc))
        return EXIT_IO
    except ParseError as exc:
        err(exc.subsystem, str(exc))
        return EXIT_PARSE
    except DepError as exc:
        err(exc.subsystem, str(exc))
        return EXIT_DEP
    except DeviceError as exc:
        err(exc.subsystem, str(exc))
        return EXIT_DEVICE
    except CommandTimeout as exc:
        err("timeout", str(exc))
        return EXIT_DEVICE
    except BrokenPipeError:
        return EXIT_OK
    except KeyboardInterrupt:
        err("interrupt", "aborted")
        return 130
    except OSError as exc:
        err("io", str(exc))
        return EXIT_IO
    except ShitsukeError as exc:
        err(exc.subsystem, str(exc))
        return exc.code
    except Exception as exc:
        if VERBOSE:
            traceback.print_exc()
        err("internal", "%s: %s" % (type(exc).__name__, exc))
        return 1


if __name__ == "__main__":
    sys.exit(main())
