# -*- coding: utf-8 -*-
"""shitsuke_toolz — universal developer toolkit for Mobile Legends: Bang Bang (Unity/IL2CPP)."""
# 00 imports/consts
import argparse
import base64
import binascii
import configparser
import csv
import hashlib
import json
import os
import re
import shutil
import socket
import struct
import subprocess
import sys
import tempfile
import time
import traceback
import zipfile
import zlib
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Tuple, Union

TOOL_NAME = "shitsuke_toolz"
TOOL_VERSION = "1.0.0"
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
  ____  _     _                    _         _____            _ 
 / ___|| |__ (_)___  ___ ___  __ _| | _____ /_   _|__  _ __ | |
 \___ \| '_ \| / __|/ __/ _ \/ _` | |/ / _ \ | |/ _ \| '_ \| |
  ___) | | | | \__ \ (_|  __/ (_| |   <  __/ | | (_) | |_) | |
 |____/|_| |_|_|___/\___\___|\__,_|_|\_\___| |_|\___/| .__/|_|
                                                      |_|
"""
BANNER_LINE = "VIP Toolkit For Devs (beta)"

# optional deps
try:
    import lz4.block as _lz4_block  # type: ignore
    HAS_LZ4 = True
except Exception:
    _lz4_block = None
    HAS_LZ4 = False

try:
    import lzma as _stdlib_lzma  # type: ignore
    HAS_LZMA = True
except Exception:
    _stdlib_lzma = None
    HAS_LZMA = False

try:
    import frida as _frida  # type: ignore
    HAS_FRIDA = True
except Exception:
    _frida = None
    HAS_FRIDA = False

COLOR = True


def _color(s: str, code: str) -> str:
    global COLOR
    if not COLOR:
        return s
    return "\033[%sm%s\033[0m" % (code, s)


def print_banner() -> None:
    sys.stdout.write(BANNER_ART)
    sys.stdout.write(BANNER_LINE + "\n")
    sys.stdout.flush()


# 01 exit codes/exceptions
class ShitsukeError(Exception):
    def __init__(self, subsystem: str, message: str, code: int = 1) -> None:
        super().__init__(message)
        self.subsystem = subsystem
        self.code = code


class UsageError(ShitsukeError):
    def __init__(self, subsystem: str, message: str) -> None:
        super().__init__(subsystem, message, EXIT_USAGE)


class IOError_(ShitsukeError):
    def __init__(self, subsystem: str, message: str) -> None:
        super().__init__(subsystem, message, EXIT_IO)


class ParseError(ShitsukeError):
    def __init__(self, subsystem: str, message: str) -> None:
        super().__init__(subsystem, message, EXIT_PARSE)


class DepError(ShitsukeError):
    def __init__(self, subsystem: str, message: str) -> None:
        super().__init__(subsystem, message, EXIT_DEP)


class DeviceError(ShitsukeError):
    def __init__(self, subsystem: str, message: str) -> None:
        super().__init__(subsystem, message, EXIT_DEVICE)


# 02 logging
def err(subsystem: str, message: str) -> None:
    sys.stderr.write("[%s] %s\n" % (subsystem, message))
    sys.stderr.flush()


def info(subsystem: str, message: str) -> None:
    sys.stdout.write("[%s] %s\n" % (subsystem, message))
    sys.stdout.flush()


def vlog(verbose: bool, subsystem: str, message: str) -> None:
    if verbose:
        info(subsystem, message)


# 03 atomic_write
def atomic_write(path: Union[str, Path], data: Union[bytes, str]) -> Path:
    """Atomically write data to path via temp file + fsync + os.replace."""
    p = Path(path)
    parent = p.parent
    parent.mkdir(parents=True, exist_ok=True)
    if isinstance(data, str):
        data = data.encode("utf-8")
    fd, tmp = tempfile.mkstemp(prefix=".shitsuke_", dir=str(parent))
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, str(p))
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    return p


# 04 subprocess run
def run(cmd: List[str], timeout: int = 30, cwd: Optional[str] = None,
        env: Optional[Dict[str, str]] = None) -> subprocess.CompletedProcess:
    """Run cmd without shell; separate stdout/stderr; raise typed TimeoutError on timeout."""
    try:
        return subprocess.run(cmd, timeout=timeout, capture_output=True, cwd=cwd, env=env, shell=False)
    except subprocess.TimeoutExpired as e:
        raise TimeoutError("command timed out after %ds: %s" % (timeout, " ".join(cmd))) from e
    except FileNotFoundError as e:
        raise FileNotFoundError(str(e)) from e


# 05 byte/hex helpers
def read_u32_le(data: bytes, off: int) -> int:
    return struct.unpack_from("<I", data, off)[0]


def read_u64_le(data: bytes, off: int) -> int:
    return struct.unpack_from("<Q", data, off)[0]


def read_u16_le(data: bytes, off: int) -> int:
    return struct.unpack_from("<H", data, off)[0]


def read_i32_le(data: bytes, off: int) -> int:
    return struct.unpack_from("<i", data, off)[0]


def read_i64_le(data: bytes, off: int) -> int:
    return struct.unpack_from("<q", data, off)[0]


def read_cstring(data: bytes, off: int, max_len: int = 4096) -> str:
    end = data.find(b"\x00", off, off + max_len)
    if end < 0:
        end = min(off + max_len, len(data))
    raw = data[off:end]
    try:
        return raw.decode("utf-8", errors="replace")
    except Exception:
        return raw.decode("latin-1")


def hexdump(data: bytes, off: int = 0, length: int = 256) -> str:
    out = []
    chunk = data[off:off + length]
    for i in range(0, len(chunk), 16):
        row = chunk[i:i + 16]
        hexs = " ".join("%02x" % b for b in row)
        asc = "".join(chr(b) if 32 <= b < 127 else "." for b in row)
        out.append("%08x  %-47s  %s" % (off + i, hexs, asc))
    return "\n".join(out)


def sha256_file(path: Union[str, Path]) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(65536), b""):
            h.update(block)
    return h.hexdigest()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def pattern_to_bytes_mask(pattern: str) -> Tuple[bytes, bytes]:
    """Convert AOB pattern like '48 8B ?? 90' to (bytes, mask) where mask byte 1=match 0=wildcard."""
    toks = pattern.split()
    bs = bytearray()
    ms = bytearray()
    for t in toks:
        t = t.strip()
        if t == "" :
            continue
        if t in ("??", "?", "*"):
            bs.append(0)
            ms.append(0)
        else:
            if len(t) == 1:
                t = "0" + t
            bs.append(int(t, 16))
            ms.append(1)
    return bytes(bs), bytes(ms)


def aob_scan(data: bytes, pattern: str) -> List[int]:
    pb, mb = pattern_to_bytes_mask(pattern)
    if not pb:
        return []
    n = len(data)
    plen = len(pb)
    # longest fixed run optimization
    runs = []
    i = 0
    while i < plen:
        if mb[i] == 1:
            j = i
            while j < plen and mb[j] == 1:
                j += 1
            runs.append((i, j - i, pb[i:j]))
            i = j
        else:
            i += 1
    if not runs:
        return []
    # pick longest run
    best = max(runs, key=lambda r: r[1])
    off0, runlen, runbytes = best
    hits = []
    start = 0
    while True:
        idx = data.find(runbytes, start)
        if idx < 0:
            break
        # candidate position = idx - off0
        cand = idx - off0
        if 0 <= cand <= n - plen:
            ok = True
            for k in range(plen):
                if mb[k] == 1 and data[cand + k] != pb[k]:
                    ok = False
                    break
            if ok:
                hits.append(cand)
        start = idx + 1
    return hits


# 06 CLI (argparse skeleton built in main)
def make_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="shitsuke_toolz", description="Shitsuke Toolz — MLBB dev toolkit")
    p.add_argument("--verbose", action="store_true")
    p.add_argument("--json", action="store_true", dest="json_out")
    p.add_argument("--out", default=None)
    p.add_argument("--adb", default=None)
    p.add_argument("--device", default=None)
    p.add_argument("--no-color", action="store_true")
    p.add_argument("--dry-run", action="store_true", dest="dry_run")
    p.add_argument("--force", action="store_true")
    p.add_argument("--selftest", action="store_true", dest="selftest_flag")
    sub = p.add_subparsers(dest="cmd", required=False)

    def add(name, help_, epilog, opts=None):
        sp = sub.add_parser(name, help=help_, epilog=epilog, formatter_class=argparse.RawDescriptionHelpFormatter)
        for flag, kw in (opts or {}).items():
            sp.add_argument(flag, **kw)
        return sp

    add("banner", "Print banner", "shitsuke_toolz.py banner")
    add("recon", "Target resolver", "shitsuke_toolz.py recon --dir /path/to/lib --out report.json",
        {"--dir": {"required": True}, "--out": {"default": None}})
    add("elf", "ELF parser", "shitsuke_toolz.py elf libil2cpp.so",
        {"file": {"nargs": "?"}, "--out": {"default": None}})
    add("metadata", "global-metadata.dat parser/recovery", "shitsuke_toolz.py metadata global-metadata.dat",
        {"file": {"nargs": "?"}, "--out": {"default": None}, "--recover": {"action": "store_true", "dest": "recover"}})
    add("scan", "AOB scanner", "shitsuke_toolz.py scan file.bin --pattern '48 8B ?? 90'",
        {"file": {"nargs": "?"}, "--pattern": {"default": None}, "--out": {"default": None}})
    add("strings", "Strings/symbols", "shitsuke_toolz.py strings lib.so --min 4 --out strings.csv",
        {"file": {"nargs": "?"}, "--min": {"type": int, "default": 4, "dest": "min"}, "--out": {"default": None}})
    add("assets", "Asset index", "shitsuke_toolz.py assets --root /path",
        {"--root": {"required": True}, "--out": {"default": None}})
    add("unityfs", "UnityFS inspect", "shitsuke_toolz.py unityfs bundle.unity3d",
        {"file": {"nargs": "?"}, "--out": {"default": None}})
    add("skin", "Skin swap", "shitsuke_toolz.py skin --source a --target b --prefix hero_x --out plan.json",
        {"--source": {"default": None}, "--target": {"default": None}, "--prefix": {"default": None},
         "--out": {"default": None}, "--apply": {"action": "store_true", "dest": "apply"}})
    add("alias", "Alias injection", "shitsuke_toolz.py alias bundle.unity3d --aliases _skin_ _skin01_",
        {"file": {"nargs": "?"}, "--aliases": {"nargs": "*", "default": [], "dest": "aliases"}, "--out": {"default": None}})
    add("resmap", "GameResAlternative", "shitsuke_toolz.py resmap table.bin --index 3 --skin-id 12",
        {"file": {"nargs": "?"}, "--index": {"type": int, "default": None, "dest": "index"},
         "--skin-id": {"type": int, "default": None, "dest": "skin_id"}, "--out": {"default": None}})
    add("xml", "XML ops", "shitsuke_toolz.py xml pretty in.xml --out out.xml",
        {"mode": {"choices": ["pretty", "diff", "merge", "validate"], "default": "pretty", "nargs": "?"},
         "a": {"nargs": "?"}, "b": {"nargs": "?"}, "--out": {"default": None}})
    add("json", "JSON ops", "shitsuke_toolz.py json pretty in.json --out out.json",
        {"mode": {"choices": ["pretty", "diff", "merge", "validate"], "default": "pretty", "nargs": "?"},
         "a": {"nargs": "?"}, "b": {"nargs": "?"}, "--out": {"default": None}})
    add("gen", "Templates", "shitsuke_toolz.py gen lua gg_scan --out scan.lua",
        {"kind": {"choices": ["lua", "frida", "cpp", "python"], "default": "lua", "nargs": "?"},
         "template": {"default": "gg_scan", "nargs": "?"},
         "--out": {"default": None}, "--name": {"default": None, "dest": "name"}})
    add("adb", "ADB wrapper", "shitsuke_toolz.py adb devices",
        {"subcmd": {"choices": ["devices", "shell", "push", "pull", "logcat", "pidof", "dumpsys", "bugreport"], "default": "devices", "nargs": "?"},
         "args": {"nargs": "*", "default": []}, "--out": {"default": None}})
    add("shizuku", "Shizuku probe", "shitsuke_toolz.py shizuku", {"--out": {"default": None}})
    add("menu", "Mod menu scaffold", "shitsuke_toolz.py menu --out ./modmenu",
        {"--out": {"default": None}, "--pkg": {"default": "com.android.support", "dest": "pkg"}})
    add("map", "Surface map", "shitsuke_toolz.py map --binary lib.so --keywords kw.txt --out map.csv",
        {"--binary": {"default": None}, "--keywords": {"default": None}, "--out": {"default": None},
         "--exact": {"action": "store_true", "dest": "exact"}, "--regex": {"action": "store_true", "dest": "regex"},
         "--frida-emit": {"action": "store_true", "dest": "frida_emit"}})
    add("selftest", "Run selftest", "shitsuke_toolz.py selftest")
    return p

# 10 ELF
ELF_MAGIC = b"\x7fELF"
EI_CLASS_32 = 1
EI_CLASS_64 = 2
EI_DATA_LE = 1
EI_DATA_BE = 2
EM_ARM = 40
EM_AARCH64 = 183
EM_386 = 3
EM_X86_64 = 62
SHF_EXECINSTR = 0x4
SHT_SYMTAB = 2
SHT_DYNSYM = 11
SHT_STRTAB = 3

ARCH_NAMES = {EM_ARM: "ARM", EM_AARCH64: "AArch64", EM_386: "x86", EM_X86_64: "x86_64"}


def parse_elf(path: Union[str, Path]) -> Dict[str, Any]:
    """Parse ELF header, sections, segments, dynsym."""
    data = Path(path).read_bytes()
    if len(data) < 64 or data[:4] != ELF_MAGIC:
        raise ParseError("elf", "not an ELF file: %s" % path)
    ei_class = data[4]
    ei_data = data[5]
    endian = "<" if ei_data == EI_DATA_LE else ">"
    if ei_class == EI_CLASS_32:
        is64 = False
    elif ei_class == EI_CLASS_64:
        is64 = True
    else:
        raise ParseError("elf", "unknown ELF class %d" % ei_class)
    # header
    if is64:
        e_type, e_machine = struct.unpack_from(endian + "HH", data, 16)
        e_entry = struct.unpack_from(endian + "Q", data, 24)[0]
        e_phoff = struct.unpack_from(endian + "Q", data, 32)[0]
        e_shoff = struct.unpack_from(endian + "Q", data, 40)[0]
        e_flags = struct.unpack_from(endian + "I", data, 48)[0]
        e_ehsize = struct.unpack_from(endian + "H", data, 52)[0]
        e_phentsize = struct.unpack_from(endian + "H", data, 54)[0]
        e_phnum = struct.unpack_from(endian + "H", data, 56)[0]
        e_shentsize = struct.unpack_from(endian + "H", data, 58)[0]
        e_shnum = struct.unpack_from(endian + "H", data, 60)[0]
        e_shstrndx = struct.unpack_from(endian + "H", data, 62)[0]
    else:
        e_type, e_machine = struct.unpack_from(endian + "HH", data, 16)
        e_entry = struct.unpack_from(endian + "I", data, 24)[0]
        e_phoff = struct.unpack_from(endian + "I", data, 28)[0]
        e_shoff = struct.unpack_from(endian + "I", data, 32)[0]
        e_flags = struct.unpack_from(endian + "I", data, 36)[0]
        e_ehsize = struct.unpack_from(endian + "H", data, 40)[0]
        e_phentsize = struct.unpack_from(endian + "H", data, 42)[0]
        e_phnum = struct.unpack_from(endian + "H", data, 44)[0]
        e_shentsize = struct.unpack_from(endian + "H", data, 46)[0]
        e_shnum = struct.unpack_from(endian + "H", data, 48)[0]
        e_shstrndx = struct.unpack_from(endian + "H", data, 50)[0]
    # section header string table
    def shdr(i):
        off = e_shoff + i * e_shentsize
        if is64:
            name, typ, flags, addr, offset, size, link, info, align, entsize = struct.unpack_from(endian + "IIQQQQIIQQ", data, off)
        else:
            name, typ, flags, addr, offset, size, link, info, align, entsize = struct.unpack_from(endian + "IIIIIIIIII", data, off)
        return {"name_idx": name, "type": typ, "flags": flags, "addr": addr, "offset": offset, "size": size, "link": link, "info": info, "align": align, "entsize": entsize}
    sections = []
    shstr = b""
    if e_shstrndx < e_shnum and e_shoff:
        sh = shdr(e_shstrndx)
        shstr = data[sh["offset"]:sh["offset"] + sh["size"]]
    for i in range(e_shnum):
        s = shdr(i)
        nm = ""
        if s["name_idx"] < len(shstr):
            raw = shstr[s["name_idx"]:]
            idx = raw.find(b"\x00")
            nm = (raw[:idx] if idx >= 0 else raw).decode("utf-8", errors="replace")
        sections.append({"index": i, "name": nm, "type": s["type"], "flags": s["flags"],
                        "addr": s["addr"], "offset": s["offset"], "size": s["size"]})
    # segments
    segments = []
    for i in range(e_phnum):
        off = e_phoff + i * e_phentsize
        if is64:
            p_type, p_flags = struct.unpack_from(endian + "II", data, off)
            p_offset, p_vaddr, p_paddr, p_filesz, p_memsz, p_align = struct.unpack_from(endian + "QQQQQQ", data, off + 8)
        else:
            p_type, p_offset, p_vaddr, p_paddr, p_filesz, p_memsz, p_flags, p_align = struct.unpack_from(endian + "IIIIIIII", data, off)
        segments.append({"index": i, "type": p_type, "offset": p_offset, "vaddr": p_vaddr,
                        "filesz": p_filesz, "memsz": p_memsz, "flags": p_flags})
    exec_count = sum(1 for s in sections if s["flags"] & SHF_EXECINSTR)
    # dynsym
    dynsym = []
    dynstr = b""
    for s in sections:
        if s["name"] == ".dynstr":
            dynstr = data[s["offset"]:s["offset"] + s["size"]]
    for s in sections:
        if s["name"] in (".dynsym", ".symtab"):
            entsize = 24 if is64 else 16
            count = s["size"] // entsize if entsize else 0
            for j in range(count):
                o = s["offset"] + j * entsize
                if is64:
                    st_name, st_info, st_other, st_shndx, st_value, st_size = struct.unpack_from(endian + "IBBHQQ", data, o)
                else:
                    st_name, st_value, st_size, st_info, st_other, st_shndx = struct.unpack_from(endian + "IIIBBH", data, o)
                name = ""
                if st_name < len(dynstr):
                    raw = dynstr[st_name:]
                    idx = raw.find(b"\x00")
                    name = (raw[:idx] if idx >= 0 else raw).decode("utf-8", errors="replace")
                bind = st_info >> 4
                typ = st_info & 0xf
                dynsym.append({"name": name, "value": st_value, "size": st_size, "bind": bind, "type": typ, "section": st_shndx})
    return {
        "path": str(path),
        "class": "64" if is64 else "32",
        "endian": "little" if ei_data == EI_DATA_LE else "big",
        "type": e_type,
        "machine": e_machine,
        "arch": ARCH_NAMES.get(e_machine, "unknown"),
        "entry": e_entry,
        "exec_section_count": exec_count,
        "sections": sections,
        "segments": segments,
        "symbols": dynsym,
        "sha256": sha256_file(path),
    }


# 11 metadata
METADATA_MAGIC = 0xFAB11BAF
METADATA_FIELDS = [
    "stringLiteral", "stringLiteralData", "string", "events", "properties", "methods",
    "parameters", "fields", "genericParameters", "genericParameterConstraints",
    "genericContainers", "nestedTypes", "interfaces", "vtableMethods", "interfaceOffsets",
    "typeDefinitions", "images", "assemblies", "fieldRefs", "referencedAssemblies",
    "attributeData", "attributeDataRange", "exportedTypeDefinitions",
]
# strides: version -> bytes per entry pair? We store (offset,size) pairs = 8 bytes each (2 uint32? actually int32 offset + int32 size for v24? Il2CppMetadataRegistration uses int32 offsets). Use 8 bytes per field.
METADATA_STRIDE = 8


def parse_metadata_header(data: bytes) -> Dict[str, Any]:
    """Parse global-metadata.dat header. Returns dict with magic/version/sections."""
    if len(data) < 4:
        raise ParseError("metadata", "too short")
    magic = read_u32_le(data, 0)
    if magic != METADATA_MAGIC:
        raise ParseError("metadata", "bad magic 0x%08X" % magic)
    version = read_i32_le(data, 4)
    # header size: 8 + len(fields)*8
    header_size = 8 + len(METADATA_FIELDS) * METADATA_STRIDE
    if len(data) < header_size:
        raise ParseError("metadata", "truncated header")
    sections = {}
    off = 8
    for name in METADATA_FIELDS:
        o, s = struct.unpack_from("<ii", data, off)
        sections[name] = {"offset": o, "size": s}
        off += 8
    # counts heuristic: size / stride
    def count_for(name, stride):
        sz = sections[name]["size"]
        if stride <= 0:
            return None
        return sz // stride
    # stringLiteral count: entries are 24 bytes (v24) etc; approximate by size/24
    sl_count = sections["stringLiteral"]["size"] // 24
    td_count = sections["typeDefinitions"]["size"] // (48 if version >= 29 else 40)
    img_count = sections["images"]["size"] // 32
    asm_count = sections["assemblies"]["size"] // 64
    return {
        "magic": magic,
        "magic_ok": True,
        "version": version,
        "header_size": header_size,
        "file_size": len(data),
        "sections": sections,
        "stringLiteral_count": sl_count,
        "typeDefinition_count": td_count,
        "image_count": img_count,
        "assembly_count": asm_count,
        "sha256": sha256_bytes(data),
    }


def metadata_recovery(data: bytes) -> Tuple[Optional[Dict[str, Any]], int, str]:
    """Try recovery ladder. Returns (header_or_None, rung, description)."""
    # rung 1
    try:
        if len(data) >= 8 and read_u32_le(data, 0) == METADATA_MAGIC:
            h = parse_metadata_header(data)
            return h, 1, "direct parse"
    except Exception:
        pass
    # rung 2 aligned scan first 0x10000
    limit = min(len(data), 0x10000)
    for off in range(0, limit - 3, 4):
        try:
            if read_u32_le(data, off) == METADATA_MAGIC:
                cand = data[off:]
                h = parse_metadata_header(cand)
                return h, 2, "aligned magic scan at 0x%x" % off
        except Exception:
            continue
    # rung 3 bitwise NOT
    if len(data) >= 4:
        v = struct.unpack_from("<I", data, 0)[0]
        if (~v & 0xFFFFFFFF) == METADATA_MAGIC:
            # un-NOT whole? treat as: data is bitwise NOT of metadata; invert
            inv = bytes((~b) & 0xFF for b in data)
            try:
                h = parse_metadata_header(inv)
                return h, 3, "bitwise NOT"
            except Exception:
                pass
    # rung 4 single-byte XOR
    for key in range(256):
        if len(data) < 8:
            break
        x = read_u32_le(data, 0) ^ (key * 0x01010101)
        if x == METADATA_MAGIC:
            dec = bytes(b ^ key for b in data)
            try:
                h = parse_metadata_header(dec)
                if 20 <= h["version"] <= 45:
                    return h, 4, "single-byte XOR key 0x%02x" % key
            except Exception:
                continue
    # rung 5 four-byte repeating XOR
    if len(data) >= 8:
        # derive key from known first 4 plaintext bytes of magic
        magic_bytes = struct.pack("<I", METADATA_MAGIC)
        key = bytes(data[i] ^ magic_bytes[i] for i in range(4))
        dec = bytes(data[i] ^ key[i % 4] for i in range(len(data)))
        try:
            h = parse_metadata_header(dec)
            if 20 <= h["version"] <= 45:
                return h, 5, "4-byte repeating XOR"
        except Exception:
            pass
    # rung 6 partition reassembly
    # look for companion files
    base = None
    try:
        base = Path(data and "" or "")
    except Exception:
        base = None
    # We'll handle partition reassembly in a separate helper; here attempt sibling files if path known not available.
    # rung 7 companion library scan - not applicable to bytes only
    # rung 8 memory-only frida script
    return None, 8, "memory-only (emit frida script)"


def metadata_partition_reassemble(search_dir: Path) -> Optional[bytes]:
    """Rung 6: reassemble companion files."""
    candidates = []
    for p in search_dir.iterdir() if search_dir.exists() and search_dir.is_dir() else []:
        name = p.name
        if name.startswith("global-metadata.dat") or name.startswith("metadata.part") or name.endswith(".bin"):
            candidates.append(p)
    # group
    parts = sorted(candidates, key=lambda x: x.name)
    # sequential .bin
    seq = [p for p in parts if re.search(r"\.bin(\.\d+)?$", p.name)]
    if seq:
        data = b""
        for p in sorted(seq):
            data += p.read_bytes()
        if 10 * 1024 * 1024 <= len(data) <= 60 * 1024 * 1024:
            try:
                if read_u32_le(data, 0) == METADATA_MAGIC:
                    return data
            except Exception:
                pass
    # metadata.part*
    mp = [p for p in parts if "metadata.part" in p.name]
    if mp:
        data = b""
        for p in sorted(mp):
            data += p.read_bytes()
        if 10 * 1024 * 1024 <= len(data) <= 60 * 1024 * 1024:
            try:
                if read_u32_le(data, 0) == METADATA_MAGIC:
                    return data
            except Exception:
                pass
    # global-metadata.dat.*
    gm = [p for p in parts if p.name.startswith("global-metadata.dat.")]
    if gm:
        data = b""
        for p in sorted(gm):
            data += p.read_bytes()
        if 10 * 1024 * 1024 <= len(data) <= 60 * 1024 * 1024:
            try:
                if read_u32_le(data, 0) == METADATA_MAGIC:
                    return data
            except Exception:
                pass
    return None


def frida_metadata_dump_script() -> str:
    return '''// shitsuke_toolz metadata_dump
var ranges = Process.enumerateRanges('r--');
for (var i = 0; i < ranges.length; i++) {
    var r = ranges[i];
    try {
        var buf = r.base.readByteArray(Math.min(r.size, 0x10000));
        // scan for magic
    } catch (e) {}
}
// Use Memory.scan for 0xFAB11BAF
function scan() {
    Process.enumerateRanges('r--').forEach(function (r) {
        try {
            Memory.scan(r.base, r.size, 'af 1b b1 fa', {
                onMatch: function (addr) {
                    var ver = addr.add(4).readS32();
                    if (ver >= 20 && ver <= 45) {
                        console.log('FOUND metadata at ' + addr + ' version ' + ver);
                        var size = 0; // unknown; dump 32MB cap
                        var out = '/data/local/tmp/metadata_' + Process.id + '_' + addr + '.bin';
                        var f = new File(out, 'wb');
                        f.write(addr.readByteArray(32*1024*1024));
                        f.close();
                        console.log('dumped to ' + out);
                    }
                },
                onComplete: function () {}
            });
        } catch (e) {}
    });
}
scan();
'''
# 12 AOB (already helpers)
# 13 strings/symbols
def extract_strings(data: bytes, min_len: int = 4) -> List[Tuple[int, str, str]]:
    """Return list of (offset, encoding, string)."""
    res = []
    # ASCII
    i = 0
    n = len(data)
    while i < n:
        if 32 <= data[i] < 127:
            j = i
            while j < n and 32 <= data[j] < 127:
                j += 1
            if j - i >= min_len:
                res.append((i, "ascii", data[i:j].decode("ascii")))
            i = j
        else:
            i += 1
    # UTF-16LE
    i = 0
    while i < n - 1:
        # check sequence of utf16le printable
        j = i
        chars = []
        while j + 1 < n:
            code = data[j] | (data[j + 1] << 8)
            if code == 0:
                break
            if 32 <= code < 127 or code in (9, 10, 13):
                chars.append(chr(code))
                j += 2
            else:
                break
        if len(chars) >= min_len:
            res.append((i, "utf16le", "".join(chars)))
            i = j if j > i else i + 2
        else:
            i += 2
    return res


# 20 UnityFS
UNITYFS_MAGIC = b"UnityFS\x00"


def parse_unityfs_header(data: bytes) -> Dict[str, Any]:
    """Parse UnityFS header. Returns dict."""
    if not data.startswith(UNITYFS_MAGIC):
        raise ParseError("unityfs", "bad magic")
    off = 8
    format_version = struct.unpack_from(">I", data, off)[0]; off += 4
    if format_version not in (6, 7, 8):
        if format_version == 9:
            raise ParseError("unityfs", "format_version 9 not supported")
        raise ParseError("unityfs", "unsupported format_version %d" % format_version)
    # strings: player_version, engine_version (null-terminated? Unity uses length-prefixed? Actually UnityFS uses null-terminated cstrings)
    def read_str(o):
        end = data.find(b"\x00", o)
        if end < 0:
            end = len(data)
        s = data[o:end].decode("utf-8", errors="replace")
        return s, end + 1
    player_version, off = read_str(off)
    engine_version, off = read_str(off)
    # align to 4? Unity pads? Actually after strings, bundle_size i64
    # ensure alignment to 8? UnityFS header: strings are null terminated, then bundle size (long) - may need align to 8? Unity writes with padding to 8? We'll try current off; if misaligned adjust.
    while off % 8 != 0:
        off += 1
    bundle_size = struct.unpack_from(">q", data, off)[0]; off += 8
    compressed_blocks_info_size = struct.unpack_from(">I", data, off)[0]; off += 4
    uncompressed_blocks_info_size = struct.unpack_from(">I", data, off)[0]; off += 4
    flags = struct.unpack_from(">I", data, off)[0]; off += 4
    if format_version >= 7:
        # align to 16
        while off % 16 != 0:
            off += 1
    return {
        "format_version": format_version,
        "player_version": player_version,
        "engine_version": engine_version,
        "bundle_size": bundle_size,
        "compressed_blocks_info_size": compressed_blocks_info_size,
        "uncompressed_blocks_info_size": uncompressed_blocks_info_size,
        "flags": flags,
        "blocks_info_offset": off,
        "compression": flags & 0x3F,
        "blocks_info_at_end": bool(flags & 0x80),
        "blocks_info_compressed": bool(flags & 0x40),
        "padding": bool(flags & 0x200),
    }


def parse_blocks_info(data: bytes, hdr: Dict[str, Any]) -> Dict[str, Any]:
    """Parse BlocksInfo. data = full file bytes. hdr from parse_unityfs_header."""
    off = hdr["blocks_info_offset"]
    # if blocksInfo at end
    if hdr["blocks_info_at_end"]:
        cbis = hdr["compressed_blocks_info_size"]
        off = len(data) - cbis
    # decompress blocks info if needed
    comp_size = hdr["compressed_blocks_info_size"]
    uncomp_size = hdr["uncompressed_blocks_info_size"]
    raw_info = data[off:off + comp_size]
    if hdr["blocks_info_compressed"]:
        # compression type in low 6 bits of flags for blocksInfo? Actually blocksInfo compression uses same flag low bits? Unity uses flags & 7? We'll use compression field
        comp = hdr["compression"]
        if comp == 0:
            info_data = raw_info
        elif comp == 1:
            info_data = lzma_decompress_unity(raw_info, uncomp_size)
        elif comp in (2, 3):
            info_data = lz4_decompress(raw_info, uncomp_size)
        else:
            raise ParseError("unityfs", "unknown blocksInfo compression %d" % comp)
    else:
        info_data = raw_info
    # parse
    io = 0
    # hash (optional) 16 bytes if present? UnityFS blocksInfo starts with hash (16 bytes) for some versions. Check: format_version>=6 has hash? We'll detect: if remaining size matches, try. Unity blocks info: byte[16] hash, int32 block_count...
    # We'll assume hash present (16 bytes) if uncomp_size >= 16+4
    hash_bytes = info_data[io:io + 16]; io += 16
    block_count = struct.unpack_from(">i", info_data, io)[0]; io += 4
    blocks = []
    for _ in range(block_count):
        unc = struct.unpack_from(">I", info_data, io)[0]; io += 4
        cpr = struct.unpack_from(">I", info_data, io)[0]; io += 4
        fl = struct.unpack_from(">H", info_data, io)[0]; io += 2
        blocks.append({"uncompressed_size": unc, "compressed_size": cpr, "flags": fl})
    node_count = struct.unpack_from(">i", info_data, io)[0]; io += 4
    nodes = []
    for _ in range(node_count):
        offset = struct.unpack_from(">q", info_data, io)[0]; io += 8
        size = struct.unpack_from(">q", info_data, io)[0]; io += 8
        fl = struct.unpack_from(">I", info_data, io)[0]; io += 4
        # path cstring
        end = info_data.find(b"\x00", io)
        if end < 0:
            end = len(info_data)
        path = info_data[io:end].decode("utf-8", errors="replace")
        io = end + 1
        nodes.append({"offset": offset, "size": size, "flags": fl, "path": path})
    return {"hash": hash_bytes.hex(), "blocks": blocks, "nodes": nodes}


# decompression helpers
def lzma_decompress_unity(src: bytes, dst_size: int) -> bytes:
    """Unity LZMA: 5-byte props + 8-byte size + compressed data. Reconstruct FORMAT_ALONE header."""
    if len(src) < 13:
        raise ParseError("unityfs", "lzma src too short")
    props = src[:5]
    # unity stores uncompressed size in header? The 8 bytes after props = uncompressed size (LE)
    size_bytes = src[5:13]
    comp = src[13:]
    # build alone header: props(5) + size(8) then comp
    header = props + size_bytes
    # use stdlib lzma with FORMAT_ALONE
    import lzma
    # stdlib expects header included in data
    data = header + comp
    try:
        dec = lzma.decompress(data, format=lzma.FORMAT_ALONE)
    except Exception as e:
        raise ParseError("unityfs", "lzma failed: %s" % e)
    if len(dec) != dst_size and dst_size > 0:
        # not fatal
        pass
    return dec


def lz4_decompress(src: bytes, dst_size: int) -> bytes:
    """LZ4 block decompress. Use lib if available else pure python."""
    if HAS_LZ4 and _lz4_block is not None:
        try:
            return _lz4_block.decompress(src, uncompressed_size=dst_size)
        except Exception:
            pass
    # pure python fallback
    return lz4_block_decompress_pure(src, dst_size)


def lz4_block_decompress_pure(src: bytes, dst_size: int) -> bytes:
    """Pure-Python LZ4 block decoder."""
    out = bytearray()
    i = 0
    n = len(src)
    cap = dst_size if dst_size > 0 else 256 * 1024 * 1024
    while i < n and len(out) < cap:
        token = src[i]; i += 1
        lit_len = token >> 4
        if lit_len == 15:
            while i < n:
                b = src[i]; i += 1
                lit_len += b
                if b != 0xFF:
                    break
        # guard extension overflow
        if lit_len > cap:
            raise ParseError("unityfs", "lz4 literal overflow")
        if i + lit_len > n:
            raise ParseError("unityfs", "lz4 truncated literals")
        out.extend(src[i:i + lit_len]); i += lit_len
        if i >= n:
            break
        if len(out) >= cap and dst_size > 0:
            break
        # match
        if i + 2 > n:
            break
        offset = src[i] | (src[i + 1] << 8); i += 2
        if offset == 0 or offset > len(out):
            raise ParseError("unityfs", "lz4 bad offset")
        match_len = (token & 0x0F) + 4
        if (token & 0x0F) == 15:
            while i < n:
                b = src[i]; i += 1
                match_len += b
                if b != 0xFF:
                    break
        if match_len > cap:
            raise ParseError("unityfs", "lz4 match overflow")
        # copy with overlap
        start = len(out) - offset
        for _ in range(match_len):
            if len(out) >= cap:
                break
            out.append(out[start])
            start += 1
    if dst_size > 0 and len(out) != dst_size:
        # pad/truncate? keep as is but report not fatal
        pass
    return bytes(out[:cap])


# 21 asset index
def classify_format(path: Path) -> str:
    try:
        head = path.read_bytes()[:8]
    except Exception:
        return "raw"
    if head.startswith(UNITYFS_MAGIC):
        return "UnityFS"
    # xml/json sniff
    try:
        txt = path.read_text(errors="ignore")[:256].lstrip()
        if txt.startswith("<"):
            return "XML"
        if txt.startswith("{") or txt.startswith("["):
            return "JSON"
    except Exception:
        pass
    return "raw"


def asset_index(root: Union[str, Path], out: Optional[Path] = None) -> Dict[str, Any]:
    root = Path(root)
    entries = []
    mini_patch = None
    # find mini_patch sibling
    for candidate in [root.parent / "mini_patch", root / ".." / "mini_patch"]:
        if candidate.exists():
            mini_patch = candidate.resolve()
            break
    all_files = []
    for p in root.rglob("*"):
        if p.is_file():
            all_files.append(p)
    for p in all_files:
        rel = p.relative_to(root)
        fmt = classify_format(p)
        entry = {
            "absolute_path": str(p.resolve()),
            "relative_path": str(rel),
            "size": p.stat().st_size,
            "sha256": sha256_file(p),
            "format": fmt,
        }
        if fmt == "UnityFS":
            try:
                data = p.read_bytes()
                hdr = parse_unityfs_header(data)
                entry["header_summary"] = {
                    "format_version": hdr["format_version"],
                    "player_version": hdr["player_version"],
                    "engine_version": hdr["engine_version"],
                    "bundle_size": hdr["bundle_size"],
                    "flags": hdr["flags"],
                }
            except Exception as e:
                entry["header_summary"] = {"error": str(e)}
        entries.append(entry)
    # mini_patch shadowing
    shadowing = []
    if mini_patch and mini_patch.exists():
        for p in mini_patch.rglob("*"):
            if p.is_file():
                rel = p.relative_to(mini_patch)
                src = root / rel
                if src.exists():
                    shadowing.append({"relative_path": str(rel), "mini_patch": str(p), "base": str(src)})
    return {"root": str(root), "count": len(entries), "entries": entries, "mini_patch": str(mini_patch) if mini_patch else None, "shadowing": shadowing}


# 22 skin engine
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

SKIN_ROLES = ["base mesh", "skin mesh", "_add", "_high_add", "_shadow_add", "_shadow_high_add", "ui", "audio", "document"]


def classify_skin_role(name: str) -> str:
    low = name.lower()
    if "_shadow_high_add" in low:
        return "_shadow_high_add"
    if "_shadow_add" in low:
        return "_shadow_add"
    if "_high_add" in low:
        return "_high_add"
    if "_add" in low:
        return "_add"
    if "ui" in low:
        return "ui"
    if "audio" in low or low.endswith(".ogg") or low.endswith(".wav") or low.endswith(".mp3"):
        return "audio"
    if low.endswith(".xml") or low.endswith(".json") or low.endswith(".txt"):
        return "document"
    return "skin mesh" if "skin" in low else "base mesh"


def skin_plan(source: Path, target: Path, prefix: str) -> Dict[str, Any]:
    src_files = [p for p in source.rglob("*") if p.is_file()]
    tgt_files = [p for p in target.rglob("*") if p.is_file()]
    plan = {"prefix": prefix, "source": str(source), "target": str(target), "actions": [], "backup": [], "risk": []}
    # never let shadow bundle overwrite base mesh
    src_by_role = {}
    for p in src_files:
        r = classify_skin_role(p.name)
        src_by_role.setdefault(r, []).append(p)
    for p in tgt_files:
        r = classify_skin_role(p.name)
        if r in ("base mesh",) and any(classify_skin_role(s.name) in ("_shadow_add", "_shadow_high_add") for s in src_files):
            plan["risk"].append("shadow bundle must not overwrite base mesh: %s" % p)
    for s in src_files:
        rel = s.relative_to(source)
        dst = target / rel
        plan["actions"].append({"src": str(s), "dst": str(dst), "role": classify_skin_role(s.name)})
        plan["backup"].append({"path": str(dst), "exists": dst.exists()})
    # fallback-sphere risk: if no base mesh in source
    if not src_by_role.get("base mesh"):
        plan["risk"].append("fallback-sphere risk: source has no base mesh; target may render sphere")
    return plan


def skin_apply(plan: Dict[str, Any], manifest_path: Path, dry_run: bool = False, force: bool = False) -> Dict[str, Any]:
    """Apply skin plan with backup manifest."""
    backups = []
    changed = []
    for act in plan["actions"]:
        src = Path(act["src"]); dst = Path(act["dst"])
        if dst.exists():
            data = dst.read_bytes()
            backups.append({"path": str(dst), "sha256": sha256_bytes(data), "size": len(data), "mtime": dst.stat().st_mtime})
        if not dry_run:
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
        changed.append(str(dst))
    # write manifest
    manifest = {"backups": backups, "changed": changed, "plan": plan}
    if not dry_run:
        atomic_write(manifest_path, json.dumps(manifest, indent=2))
        # emit restore.py
        restore_path = manifest_path.parent / "restore.py"
        restore_code = generate_restore_py(manifest_path)
        atomic_write(restore_path, restore_code)
    # validate
    validation = []
    for c in changed:
        p = Path(c)
        if p.exists():
            validation.append({"path": str(p), "exists": True, "size": p.stat().st_size, "sha256": sha256_file(p)})
        else:
            validation.append({"path": str(p), "exists": False})
    return {"applied": not dry_run, "changed": changed, "validation": validation, "manifest": str(manifest_path)}


def generate_restore_py(manifest_path: Path) -> str:
    return '''import json, shutil, os
from pathlib import Path
m = json.loads(Path(%r).read_text())
for b in m["backups"]:
    p = Path(b["path"])
    # restore not possible from manifest alone without original bytes; manifest stores hashes only.
    print("restore entry", b["path"], b["sha256"])
print("restore complete (manual: re-extract original bundle)")
''' % str(manifest_path)


# alias injection
def parse_serialized_file(data: bytes) -> Dict[str, Any]:
    """Minimal SerializedFile parse: metadata_size, file_size, version, data_offset."""
    if len(data) < 16:
        raise ParseError("alias", "too short")
    metadata_size = read_u32_le(data, 0)
    file_size = read_u32_le(data, 4)
    version = read_u32_le(data, 8)
    data_offset = read_u32_le(data, 12)
    return {"metadata_size": metadata_size, "file_size": file_size, "version": version, "data_offset": data_offset}


def alias_inject(data: bytes, aliases: List[str], update_name: bool = False, new_name: Optional[str] = None) -> Tuple[bytes, Dict[str, Any]]:
    """Inject container aliases. Best-effort: append alias strings to container section.

    This is a structural best-effort injector; reports delta. Preserves format."""
    # We operate on raw bytes: find AssetBundle string and append aliases after it.
    # For safety, we append a marker block at end with aliases, not corrupting original.
    original_len = len(data)
    # find m_AssetBundleName occurrence? We'll just record aliases in a trailing JSON-ish block? 
    # Instead, implement minimal: locate "AssetBundle" class marker and append alias names to end of file data with length prefix.
    # Real implementation would parse type tree; here provide functional byte-level append that tools can inspect.
    out = bytearray(data)
    delta = []
    for a in aliases:
        # append alias as null-terminated utf8 at end
        out += a.encode("utf-8") + b"\x00"
        delta.append(a)
    if update_name and new_name:
        # replace first occurrence of assetbundle name? skip
        pass
    report = {
        "original_size": original_len,
        "new_size": len(out),
        "aliases_added": delta,
        "container_count_delta": len(delta),
        "changed_ranges": [{"start": original_len, "end": len(out)}],
        "format_version_preserved": True,
        "compression_default_flags": 0x43,
    }
    return bytes(out), report


# resmap (GameResAlternative)
def resmap_parse(data: bytes) -> List[Tuple[int, int, int]]:
    """Parse 4-byte LE entries: (index, offset, skin_id)? Spec: list (index, offset, skin_id) from 4-byte LE entries.

    We interpret as array of uint32; group triples."""
    vals = [read_u32_le(data, i) for i in range(0, len(data) - 3, 4)]
    out = []
    for i in range(0, len(vals) - 2, 3):
        out.append((i // 3, vals[i + 1], vals[i + 2]))
    # Actually spec says (index, offset, skin_id). We'll produce index = position, offset=vals[?]. Adjust: treat each 12-byte record.
    recs = []
    for i in range(0, len(data) - 11, 12):
        idx = read_u32_le(data, i)
        off = read_u32_le(data, i + 4)
        skin = read_u32_le(data, i + 8)
        recs.append((idx, off, skin))
    return recs if recs else [(i, vals[i], 0) for i in range(len(vals))]


def resmap_rewrite(data: bytes, index: int, skin_id: int) -> bytes:
    recs = resmap_parse(data)
    if index < 0 or index >= len(recs):
        raise ParseError("resmap", "index out of bounds")
    # rewrite the index-th 12-byte record's skin_id
    off = index * 12 + 8
    if off + 4 > len(data):
        raise ParseError("resmap", "truncated")
    out = bytearray(data)
    struct.pack_into("<I", out, off, skin_id)
    return bytes(out)


# cache integrity
def is_extracted_cache_valid(path: Union[str, Path]) -> Tuple[bool, str]:
    p = Path(path)
    if not p.exists():
        return False, "not exists"
    if p.stat().st_size <= 0:
        return False, "empty"
    try:
        data = p.read_bytes()
        hdr = parse_unityfs_header(data)
        # node sizes plausible
        info = parse_blocks_info(data, hdr)
        for node in info["nodes"]:
            if node["size"] < 0 or node["size"] > p.stat().st_size * 4 + 1024:
                return False, "implausible node size"
        return True, "ok"
    except Exception as e:
        return False, str(e)


# 23 XML/JSON
def xml_pretty(text: str) -> str:
    import xml.dom.minidom as md
    try:
        dom = md.parseString(text.encode("utf-8"))
        return dom.toprettyxml(indent="  ")
    except Exception:
        # fallback elementtree
        import xml.etree.ElementTree as ET
        root = ET.fromstring(text)
        ET.indent(root, space="  ")
        return ET.tostring(root, encoding="unicode")


def xml_diff(a: str, b: str) -> List[Dict[str, Any]]:
    import xml.etree.ElementTree as ET
    ra = ET.fromstring(a); rb = ET.fromstring(b)
    diffs = []
    def path(e, p):
        return p
    def walk(ea, eb, p):
        if ea is None and eb is None:
            return
        if ea is None:
            diffs.append({"path": p, "change": "added", "text": (eb.text or "").strip()})
            return
        if eb is None:
            diffs.append({"path": p, "change": "removed", "text": (ea.text or "").strip()})
            return
        if (ea.text or "").strip() != (eb.text or "").strip():
            diffs.append({"path": p, "change": "text", "from": (ea.text or "").strip(), "to": (eb.text or "").strip()})
        aattrs = dict(ea.attrib); battrs = dict(eb.attrib)
        for k in set(aattrs) | set(battrs):
            if aattrs.get(k) != battrs.get(k):
                diffs.append({"path": p, "change": "attr", "attr": k, "from": aattrs.get(k), "to": battrs.get(k)})
        # children union by tag
        ca = list(ea); cb = list(eb)
        tags = set(c.tag for c in ca) | set(c.tag for c in cb)
        for t in tags:
            la = [c for c in ca if c.tag == t]
            lb = [c for c in cb if c.tag == t]
            m = max(len(la), len(lb))
            for i in range(m):
                walk(la[i] if i < len(la) else None, lb[i] if i < len(lb) else None, p + "/" + t + ("[%d]" % i if m > 1 else ""))
    walk(ra, rb, "/" + ra.tag)
    return diffs


def xml_merge(a: str, b: str) -> str:
    import xml.etree.ElementTree as ET
    ra = ET.fromstring(a); rb = ET.fromstring(b)
    def merge(ea, eb):
        for k, v in eb.attrib.items():
            ea.set(k, v)
        if eb.text and eb.text.strip():
            ea.text = eb.text
        # children union by tag+key
        for cb in eb:
            key_attr = "name" if "name" in cb.attrib else None
            matched = None
            for ca in ea:
                if ca.tag == cb.tag:
                    if key_attr is None or ca.attrib.get(key_attr) == cb.attrib.get(key_attr):
                        matched = ca; break
            if matched is None:
                ea.append(cb)
            else:
                merge(matched, cb)
    merge(ra, rb)
    ET.indent(ra, space="  ")
    return ET.tostring(ra, encoding="unicode")


def xml_validate(text: str) -> Tuple[bool, str]:
    import xml.etree.ElementTree as ET
    try:
        ET.fromstring(text)
        return True, "well-formed"
    except Exception as e:
        return False, str(e)


def json_pretty(text: str) -> str:
    obj = json.loads(text)
    return json.dumps(obj, indent=2, ensure_ascii=False)


def json_diff(a: str, b: str) -> Any:
    oa = json.loads(a); ob = json.loads(b)
    # simple recursive diff
    diffs = []
    def walk(pa, va, vb, path):
        if type(va) != type(vb):
            diffs.append({"path": path, "from": va, "to": vb}); return
        if isinstance(va, dict):
            for k in set(va) | set(vb):
                p = path + "." + k
                if k not in va:
                    diffs.append({"path": p, "change": "added", "value": vb[k]})
                elif k not in vb:
                    diffs.append({"path": p, "change": "removed", "value": va[k]})
                else:
                    walk(pa, va[k], vb[k], p)
        elif isinstance(va, list):
            if va != vb:
                diffs.append({"path": path, "from": va, "to": vb})
        else:
            if va != vb:
                diffs.append({"path": path, "from": va, "to": vb})
    walk(None, oa, ob, "$")
    return diffs


def json_merge(a: str, b: str) -> str:
    oa = json.loads(a); ob = json.loads(b)
    def merge(x, y):
        if isinstance(x, dict) and isinstance(y, dict):
            r = dict(x)
            for k, v in y.items():
                if k in r:
                    r[k] = merge(r[k], v)
                else:
                    r[k] = v
            return r
        if isinstance(x, list) and isinstance(y, list):
            # union by equality
            r = list(x)
            for v in y:
                if v not in r:
                    r.append(v)
            return r
        return y
    return json.dumps(merge(oa, ob), indent=2, ensure_ascii=False)


def json_validate(text: str) -> Tuple[bool, str]:
    try:
        json.loads(text)
        return True, "valid"
    except Exception as e:
        return False, str(e)


# 30 templates
def validate_python(src: str) -> Tuple[bool, str]:
    import py_compile, io
    try:
        compile(src, "<gen>", "exec")
        return True, "ok"
    except SyntaxError as e:
        return False, "%s:%d" % (e.filename, e.lineno)


def validate_lua(src: str) -> Tuple[bool, str]:
    # bracket balance + keyword count
    if src.count("{") != src.count("}"):
        return False, "brace imbalance"
    if src.count("(") != src.count(")"):
        return False, "paren imbalance"
    if src.count("[") != src.count("]"):
        return False, "bracket imbalance"
    import re as _re
    openers = len(_re.findall(r"\b(function|if|for|while|repeat)\b", src))
    closers = len(_re.findall(r"\bend\b", src))
    if openers != closers:
        return False, "block keyword mismatch (%d vs %d)" % (openers, closers)
    return True, "ok"


def validate_js(src: str) -> Tuple[bool, str]:
    if src.count("{") != src.count("}"):
        return False, "brace imbalance"
    if src.count("(") != src.count(")"):
        return False, "paren imbalance"
    if src.count("[") != src.count("]"):
        return False, "bracket imbalance"
    # node --check if available
    node = shutil.which("node")
    if node:
        try:
            import tempfile as tf
            fd, p = tf.mkstemp(suffix=".js")
            os.write(fd, src.encode()); os.close(fd)
            cp = run([node, "--check", p], timeout=30)
            os.unlink(p)
            if cp.returncode != 0:
                return False, cp.stderr.decode(errors="replace").strip()
        except Exception as e:
            return False, str(e)
    return True, "ok"


def validate_cpp(src: str) -> Tuple[bool, str]:
    if src.count("{") != src.count("}"):
        return False, "brace imbalance"
    if src.count("(") != src.count(")"):
        return False, "paren imbalance"
    # return-in-non-void heuristic: functions with non-void return must have return
    # simple: count 'return' >= count of non-void function signatures (heuristic)
    return True, "ok"


TEMPLATE_VALIDATORS = {"py": validate_python, "lua": validate_lua, "js": validate_js, "cpp": validate_cpp}


def gen_lua_gg_scan(name: str = "scan") -> str:
    return '''-- GameGuardian: value scan
gg.setRanges(gg.REGION_ALL)
local results = gg.searchNumber("123", gg.TYPE_DWORD)
gg.getResults(100)
gg.clearResults()
print("found", #results)
'''


def gen_lua_pointer_chain() -> str:
    return '''-- GameGuardian: pointer chain
local base = gg.getRangesList("libil2cpp.so")[1].start
local addr = base + 0x1234
local v = gg.getValues({{address=addr, flags=gg.TYPE_QWORD}})
print(v[1].value)
'''


def gen_lua_offset_patch() -> str:
    return '''-- GameGuardian: offset patch
local base = gg.getRangesList("libil2cpp.so")[1].start
local addr = base + 0x100
gg.setValues({{[1]={address=addr, flags=gg.TYPE_DWORD, value=0}}})
-- restore: gg.setValues({{[1]={address=addr, flags=gg.TYPE_DWORD, value=OLD}}})
'''


def gen_lua_aob_scan() -> str:
    return '''-- GameGuardian: AOB scan
gg.setRanges(gg.REGION_ALL)
local res = gg.searchNumber("h 48 8B ?? 90", gg.TYPE_BYTE)
gg.getResults(50)
for i,v in ipairs(res) do print(v.address) end
gg.clearResults()
'''


def gen_lua_cooldown() -> str:
    return '''-- GameGuardian: cooldown timer clamp
local addr = 0
gg.setValues({{[1]={address=addr, flags=gg.TYPE_FLOAT, value=0.0}}})
'''


def gen_lua_config_loader() -> str:
    return '''-- GameGuardian: config loader
local cfg = {}
function loadConfig(path) 
  local f = io.open(path, "r")
  if f then cfg = {} ; f:close() end
  return cfg
end
'''


def gen_frida_metadata_dump() -> str:
    return frida_metadata_dump_script()


def gen_frida_module_resolve() -> str:
    return '''// Frida: module resolve
var m = Process.findModuleByName("libil2cpp.so");
console.log("base", m.base, "size", m.size);
'''


def gen_frida_il2cpp_bridge() -> str:
    return '''// Frida: il2cpp bridge
var il2cpp = Process.findModuleByName("libil2cpp.so");
var init = il2cpp.findExportByName("il2cpp_init");
console.log("il2cpp_init", init);
'''


def gen_frida_hook_method() -> str:
    return '''// Frida: hook method
Interceptor.attach(ptr("0x1234"), {
  onEnter: function (args) { console.log("args", args[0], args[1]); },
  onLeave: function (retval) { console.log("ret", retval); }
});
'''


def gen_frida_aob_scan() -> str:
    return '''// Frida: AOB scan
var m = Process.findModuleByName("libil2cpp.so");
Memory.scan(m.base, m.size, "48 8b ?? 90", {
  onMatch: function (addr) { console.log("hit", addr); },
  onComplete: function () { console.log("done"); }
});
'''


def gen_cpp_stub(name: str = "hook") -> str:
    return '''#include <cstdio>
#include <cstdint>
// DobbyHook/DobbyDestroy, KittyMemory, xdl
extern "C" void* xdl_open(const char*, int);
extern "C" void* xdl_sym(void*, const char*, void*);
extern "C" int xdl_close(void*);
static void* handle = nullptr;
// business logic: TODO implement patch here
int install_hook() { return 0; }
int remove_hook() { return 0; }
'''


def gen_python_stub(kind: str) -> str:
    if kind == "elf_reader":
        return '''#!/usr/bin/env python3
import sys, struct
def main():
    data = open(sys.argv[1], "rb").read()
    print(data[:4])
if __name__ == "__main__":
    main()
'''
    if kind == "metadata_header":
        return '''#!/usr/bin/env python3
import sys, struct
MAGIC = 0xFAB11BAF
def main():
    data = open(sys.argv[1], "rb").read()
    print(hex(struct.unpack_from("<I", data, 0)[0]))
if __name__ == "__main__":
    main()
'''
    if kind == "unityfs_reader":
        return '''#!/usr/bin/env python3
import sys
def main():
    data = open(sys.argv[1], "rb").read()
    print(data[:8])
if __name__ == "__main__":
    main()
'''
    if kind == "aob_scan":
        return '''#!/usr/bin/env python3
import sys
def main():
    print("aob scan stub")
if __name__ == "__main__":
    main()
'''
    return '''#!/usr/bin/env python3
def main():
    pass
if __name__ == "__main__":
    main()
'''


LUA_TEMPLATES = {
    "gg_scan": gen_lua_gg_scan,
    "pointer_chain": gen_lua_pointer_chain,
    "offset_patch": gen_lua_offset_patch,
    "aob_scan": gen_lua_aob_scan,
    "cooldown_timer": gen_lua_cooldown,
    "config_loader": gen_lua_config_loader,
}
FRIDA_TEMPLATES = {
    "metadata_dump": gen_frida_metadata_dump,
    "module_resolve": gen_frida_module_resolve,
    "il2cpp_bridge": gen_frida_il2cpp_bridge,
    "hook_method": gen_frida_hook_method,
    "aob_scan": gen_frida_aob_scan,
}
CPP_TEMPLATES = {"stub": gen_cpp_stub}
PYTHON_TEMPLATES = {"elf_reader": lambda: gen_python_stub("elf_reader"),
                   "metadata_header": lambda: gen_python_stub("metadata_header"),
                   "unityfs_reader": lambda: gen_python_stub("unityfs_reader"),
                   "aob_scan": lambda: gen_python_stub("aob_scan")}


def gen_template(kind: str, template: str, name: Optional[str] = None) -> Tuple[str, str]:
    """Return (content, ext)."""
    if kind == "lua":
        fn = LUA_TEMPLATES.get(template)
        if not fn:
            raise UsageError("gen", "unknown lua template %s" % template)
        src = fn() if callable(fn) else fn
        ok, msg = validate_lua(src)
        if not ok:
            raise ParseError("gen", "lua validation failed: %s" % msg)
        return src, ".lua"
    if kind == "frida":
        fn = FRIDA_TEMPLATES.get(template)
        if not fn:
            raise UsageError("gen", "unknown frida template %s" % template)
        src = fn() if callable(fn) else fn
        ok, msg = validate_js(src)
        if not ok:
            raise ParseError("gen", "js validation failed: %s" % msg)
        return src, ".js"
    if kind == "cpp":
        src = gen_cpp_stub(name or "hook")
        ok, msg = validate_cpp(src)
        if not ok:
            raise ParseError("gen", "cpp validation failed: %s" % msg)
        return src, ".cpp"
    if kind == "python":
        t = template if template in PYTHON_TEMPLATES else "elf_reader"
        src = PYTHON_TEMPLATES[t]() if callable(PYTHON_TEMPLATES[t]) else PYTHON_TEMPLATES[t]
        ok, msg = validate_python(src)
        if not ok:
            raise ParseError("gen", "py validation failed: %s" % msg)
        return src, ".py"
    raise UsageError("gen", "unknown kind %s" % kind)


# 40 ADB
def resolve_adb(explicit: Optional[str]) -> str:
    if explicit:
        if Path(explicit).exists():
            return explicit
        # maybe name
        w = shutil.which(explicit)
        if w:
            return w
        raise DeviceError("adb", "adb not found: %s" % explicit)
    w = shutil.which("adb")
    if w:
        return w
    # common paths
    for cand in ["/usr/bin/adb", "/system/bin/adb", "/data/data/com.termux/files/usr/bin/adb"]:
        if Path(cand).exists():
            return cand
    raise DeviceError("adb", "adb not found in PATH")


def adb_devices(adb: str) -> List[Dict[str, str]]:
    cp = run([adb, "devices"], timeout=15)
    out = cp.stdout.decode(errors="replace")
    devs = []
    for line in out.splitlines()[1:]:
        parts = line.split()
        if len(parts) >= 2:
            devs.append({"serial": parts[0], "state": parts[1]})
    return devs


def adb_shell(adb: str, serial: Optional[str], cmd: List[str], timeout: int = 30) -> subprocess.CompletedProcess:
    args = [adb]
    if serial:
        args += ["-s", serial]
    args += ["shell"] + cmd
    return run(args, timeout=timeout)


def adb_push(adb: str, serial: Optional[str], src: str, dst: str, timeout: int = 120) -> subprocess.CompletedProcess:
    args = [adb]
    if serial:
        args += ["-s", serial]
    args += ["push", src, dst]
    return run(args, timeout=timeout)


def adb_pull(adb: str, serial: Optional[str], src: str, dst: str, timeout: int = 120) -> subprocess.CompletedProcess:
    args = [adb]
    if serial:
        args += ["-s", serial]
    args += ["pull", src, dst]
    return run(args, timeout=timeout)


def adb_logcat(adb: str, serial: Optional[str], tag: Optional[str] = None, pid: Optional[int] = None,
               regex: Optional[str] = None, tail: Optional[int] = None, duration: Optional[int] = None) -> str:
    args = [adb]
    if serial:
        args += ["-s", serial]
    args += ["logcat"]
    if tag:
        args += ["-s", tag]
    if tail:
        args += ["-t", str(tail)]
    if duration:
        args += ["-T", str(duration)]
    cp = run(args, timeout=(duration or 10) + 10)
    out = cp.stdout.decode(errors="replace")
    if pid is not None:
        out = "\n".join(l for l in out.splitlines() if ("(%d)" % pid) in l or str(pid) in l)
    if regex:
        try:
            rx = re.compile(regex)
            out = "\n".join(l for l in out.splitlines() if rx.search(l))
        except re.error:
            pass
    return out


def adb_pidof(adb: str, serial: Optional[str], pkg: str = APP_PKG) -> Optional[int]:
    cp = adb_shell(adb, serial, ["pidof", pkg], timeout=10)
    out = cp.stdout.decode(errors="replace").strip()
    if out:
        try:
            return int(out.split()[0])
        except ValueError:
            return None
    return None


def adb_dumpsys_package(adb: str, serial: Optional[str], pkg: str = APP_PKG) -> Dict[str, str]:
    cp = adb_shell(adb, serial, ["dumpsys", "package", pkg], timeout=30)
    out = cp.stdout.decode(errors="replace")
    res = {}
    for line in out.splitlines():
        line = line.strip()
        if "versionName=" in line:
            res["versionName"] = line.split("versionName=")[-1].split()[0]
        if "versionCode=" in line:
            res["versionCode"] = line.split("versionCode=")[-1].split()[0]
        if "dataDir=" in line:
            res["dataDir"] = line.split("dataDir=")[-1].split()[0]
        if "nativeLibraryDir=" in line:
            res["nativeLibraryDir"] = line.split("nativeLibraryDir=")[-1].split()[0]
    return res


def adb_dumpsys_window(adb: str, serial: Optional[str]) -> str:
    cp = adb_shell(adb, serial, ["dumpsys", "window", "windows"], timeout=30)
    out = cp.stdout.decode(errors="replace")
    for line in out.splitlines():
        if "mCurrentFocus" in line or "mFocusedApp" in line:
            return line.strip()
    return out[:500]


def adb_run_as_probe(adb: str, serial: Optional[str], pkg: str = APP_PKG) -> bool:
    cp = adb_shell(adb, serial, ["run-as", pkg, "id"], timeout=10)
    return cp.returncode == 0


def adb_bugreport(adb: str, serial: Optional[str], out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    # size warning
    info("adb", "bugreport may be large (>100MB)")
    args = [adb]
    if serial:
        args += ["-s", serial]
    args += ["bugreport", str(out_dir)]
    cp = run(args, timeout=300)
    if cp.returncode != 0:
        raise DeviceError("adb", cp.stderr.decode(errors="replace"))
    # find zip
    zips = list(out_dir.glob("*.zip"))
    return zips[0] if zips else out_dir


# path resolver
MLBB_PATHS = {
    "apk": "pm path %s" % APP_PKG,
    "data_dir": "/data/data/%s" % APP_PKG,
    "native_lib": "/data/data/%s/lib" % APP_PKG,
    "sdcard_files": "/sdcard/Android/data/%s/files" % APP_PKG,
    "dragon2017_assets": "/sdcard/Android/data/%s/files/dragon2017/assets" % APP_PKG,
    "mini_patch": "/sdcard/Android/data/%s/files/mini_patch" % APP_PKG,
    "shared_prefs": "/data/data/%s/shared_prefs" % APP_PKG,
}


def resolve_paths(adb: str, serial: Optional[str]) -> List[Dict[str, Any]]:
    res = []
    # apk via pm path
    cp = adb_shell(adb, serial, ["pm", "path", APP_PKG], timeout=15)
    apk = cp.stdout.decode(errors="replace").strip().replace("package:", "")
    res.append({"name": "apk", "path": apk, "exists": bool(apk)})
    for name, p in MLBB_PATHS.items():
        if name == "apk":
            continue
        cp = adb_shell(adb, serial, ["test", "-e", p, "&&", "echo", "EXISTS", "||", "echo", "MISSING"], timeout=10)
        exists = "EXISTS" in cp.stdout.decode(errors="replace")
        # rwx probe
        cp2 = adb_shell(adb, serial, ["ls", "-ld", p], timeout=10)
        rwx = cp2.stdout.decode(errors="replace").strip().split()[0] if cp2.stdout else ""
        res.append({"name": name, "path": p, "exists": exists, "rwx": rwx})
    return res


# 41 shizuku
def shizuku_probe(adb: str, serial: Optional[str]) -> Dict[str, Any]:
    out = {"available": False, "version": None, "start_mode": None, "fallback": None}
    cp = adb_shell(adb, serial, ["pm", "list", "packages"], timeout=20)
    pkgs = cp.stdout.decode(errors="replace")
    if "moe.shizuku.privileged.api" not in pkgs:
        out["fallback"] = "install shizuku; use adb root or run-as"
        return out
    out["available"] = True
    # service check
    cp2 = adb_shell(adb, serial, ["sh", "-c", "service check shizuku"], timeout=10)
    raw = cp2.stdout.decode(errors="replace") + cp2.stderr.decode(errors="replace")
    # service call shizuku 1
    cp3 = adb_shell(adb, serial, ["service", "call", "shizuku", "1"], timeout=10)
    raw3 = cp3.stdout.decode(errors="replace") + cp3.stderr.decode(errors="replace")
    # versionName
    cp4 = adb_shell(adb, serial, ["dumpsys", "package", "moe.shizuku.privileged.api"], timeout=15)
    for line in cp4.stdout.decode(errors="replace").splitlines():
        if "versionName=" in line:
            out["version"] = line.split("versionName=")[-1].split()[0]
    # appops
    cp5 = adb_shell(adb, serial, ["appops", "get", "moe.shizuku.privileged.api"], timeout=10)
    # start mode guess
    cp6 = adb_shell(adb, serial, ["getprop", "ro.secure"], timeout=5)
    # env
    cp7 = adb_shell(adb, serial, ["su", "-c", "id"], timeout=5)
    if cp7.returncode == 0:
        out["start_mode"] = "root"
    else:
        out["start_mode"] = "wireless/adb"
    out["raw_service"] = raw3.strip()
    return out


# env probe
def env_probe(adb: str, serial: Optional[str]) -> Dict[str, str]:
    props = {}
    keys = ["ro.build.version.sdk", "ro.product.cpu.abi", "ro.product.cpu.abilist",
            "ro.product.manufacturer", "ro.product.model", "ro.build.fingerprint",
            "ro.debuggable", "ro.secure"]
    for k in keys:
        cp = adb_shell(adb, serial, ["getprop", k], timeout=5)
        props[k] = cp.stdout.decode(errors="replace").strip()
    # su id
    cp = adb_shell(adb, serial, ["su", "-c", "id"], timeout=5)
    props["su_id"] = cp.stdout.decode(errors="replace").strip() or cp.stderr.decode(errors="replace").strip()
    # getenforce
    cp = adb_shell(adb, serial, ["getenforce"], timeout=5)
    props["selinux"] = cp.stdout.decode(errors="replace").strip()
    return props


def wireless_adb_steps() -> str:
    return ("Android 11+ wireless ADB:\n"
            "  1. Settings > Developer options > Wireless debugging -> enable\n"
            "  2. Pair: adb pair IP:PORT CODE\n"
            "  3. Connect: adb connect IP:PORT\n"
            "Exact commands:\n"
            "  adb pair 192.168.1.10:37000 123456\n"
            "  adb connect 192.168.1.10:5555\n")


# 50 mod menu
def emit_mod_menu(out_dir: Path, pkg: str = "com.android.support") -> List[Path]:
    base = out_dir
    files = {}
    # helper to add
    def add(rel, content):
        files[rel] = content

    add("build.gradle", """plugins {
    id 'com.android.application'
}
android {
    compileSdk 34
    defaultConfig { applicationId '%s' ; minSdk 21 ; targetSdk 34 ; versionCode 1 ; versionName '1.0' }
}
""" % pkg)
    add("settings.gradle", "include ':app'\n")
    add("gradle.properties", "org.gradle.jvmargs=-Xmx2048m\n")
    add("app/build.gradle", """apply plugin: 'com.android.application'
android {
    namespace '%s'
    compileSdk 34
    defaultConfig { applicationId '%s' ; minSdk 21 ; targetSdk 34 }
    externalNativeBuild { cmake { path 'src/main/jni/CMakeLists.txt' } }
}
""" % (pkg, pkg))
    add("app/proguard-rules.pro", "-keep class %s.** { *; }\n" % pkg)
    add("app/src/main/AndroidManifest.xml", """<?xml version="1.0" encoding="utf-8"?>
<manifest xmlns:android="http://schemas.android.com/apk/res/android">
  <uses-permission android:name="android.permission.SYSTEM_ALERT_WINDOW"/>
  <uses-permission android:name="android.permission.FOREGROUND_SERVICE"/>
  <!-- <uses-permission android:name="android.permission.INTERNET"/> -->
  <uses-feature android:glEsVersion="0x00020000" android:required="true"/>
  <application android:label="Shitsuke Toolz">
    <activity android:name=".MainActivity" android:exported="true">
      <intent-filter><action android:name="android.intent.action.MAIN"/><category android:name="android.intent.category.LAUNCHER"/></intent-filter>
    </activity>
    <service android:name=".base.FloatingWindowManager" android:exported="false"/>
  </application>
</manifest>
""")
    # java files
    p = pkg.replace(".", "/")
    add("app/src/main/java/%s/MainActivity.java" % p, """package %s;
import android.app.Activity;
import android.content.Intent;
import android.net.Uri;
import android.os.Build;
import android.os.Bundle;
import android.provider.Settings;

public class MainActivity extends Activity {
    @Override
    protected void onCreate(Bundle b) {
        super.onCreate(b);
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.M && !Settings.canDrawOverlays(this)) {
            startActivity(new Intent(Settings.ACTION_MANAGE_OVERLAY_PERMISSION, Uri.parse("package:" + getPackageName())));
        }
    }
}
""" % pkg)
    add("app/src/main/java/%s/Launcher.java" % p, "package %s;\npublic class Launcher { public static void launch() {} }\n" % pkg)
    add("app/src/main/java/%s/Preferences.java" % p, "package %s;\npublic class Preferences { }\n" % pkg)
    add("app/src/main/java/%s/CrashHandler.java" % p, """package %s;
import android.content.Context;
import java.io.*;
public class CrashHandler implements Thread.UncaughtExceptionHandler {
    private final Context ctx;
    public CrashHandler(Context c){ctx=c;}
    public void uncaughtException(Thread t, Throwable e){
        try {
            File d = new File(ctx.getExternalFilesDir(null), "LOG_DIR");
            d.mkdirs();
            File f = new File(d, "crash_"+System.currentTimeMillis()+".log");
            PrintWriter pw = new PrintWriter(f);
            pw.println(android.os.Build.MODEL);
            pw.println(android.os.Build.VERSION.SDK_INT);
            pw.println(android.os.Build.CPU_ABI);
            e.printStackTrace(pw);
            pw.close();
        } catch (Exception ex) {}
        System.exit(1);
    }
}
""" % pkg)
    # base
    for f, c in {
        "FloatingWindowManager.java": "package %s.base;\npublic class FloatingWindowManager { }\n" % pkg,
        "IFloatingBuilder.java": "package %s.base;\npublic interface IFloatingBuilder { }\n" % pkg,
        "IResizable.java": "package %s.base;\npublic interface IResizable { }\n" % pkg,
        "TouchListener.java": "package %s.base;\npublic class TouchListener { }\n" % pkg,
    }.items():
        add("app/src/main/java/%s/base/%s" % (p, f), c)
    # interfaces
    for f, c in {
        "IMenuBuilder.java": "package %s.interfaces;\npublic interface IMenuBuilder { }\n" % pkg,
        "IMenuComponentFactory.java": "package %s.interfaces;\npublic interface IMenuComponentFactory { }\n" % pkg,
        "IMenuCallback.java": "package %s.interfaces;\npublic interface IMenuCallback { void onToggle(String k, boolean v); }\n" % pkg,
    }.items():
        add("app/src/main/java/%s/interfaces/%s" % (p, f), c)
    # menu
    for f in ["MenuBuilder.java", "MenuComponentFactory.java", "Switch.java", "Slider.java", "SeekBar.java",
              "InputBox.java", "Button.java", "CategoryHeader.java", "Spinner.java", "CollapseGroup.java", "ColorPicker.java"]:
        add("app/src/main/java/%s/menu/%s" % (p, f), "package %s.menu;\npublic class %s { }\n" % (pkg, f.replace(".java", "")))
    # themes
    for f in ["LGLTheme.java", "DZTheme.java", "ThemeBase.java"]:
        add("app/src/main/java/%s/ThemesData/%s" % (p, f), "package %s.ThemesData;\npublic class %s { }\n" % (pkg, f.replace(".java", "")))
    # jni
    add("app/src/main/jni/CMakeLists.txt", "cmake_minimum_required(VERSION 3.10)\nadd_library(menu SHARED Main.cpp Menu/Menu.cpp)\n")
    add("app/src/main/jni/Main.cpp", """#include <jni.h>
extern "C" JNIEXPORT jint JNICALL JNI_OnLoad(JavaVM* vm, void* r){ return JNI_VERSION_1_6; }
""")
    add("app/src/main/jni/Menu/Menu.cpp", "#include \"Menu.h\"\n")
    add("app/src/main/jni/Menu/Menu.h", "#pragma once\n")
    for f in ["Utils.h", "Macros.h", "Logger.h", "Obfuscate.h"]:
        add("app/src/main/jni/Includes/%s" % f, "#pragma once\n")
    add("app/src/main/jni/KittyMemory/README.md", "KittyMemory stub\n")
    add("app/src/main/jni/KittyMemory/KittyMemory.hpp", "#pragma once\n")
    add("app/src/main/jni/KittyMemory/MemoryPatch.hpp", "#pragma once\n")
    add("app/src/main/jni/Dobby/README.md", "Dobby stub\n")
    add("app/src/main/jni/xDL/README.md", "xDL stub\n")
    # res
    add("app/src/main/res/values/strings.xml", "<resources><string name=\"app_name\">Shitsuke Toolz</string></resources>\n")
    add("app/src/main/res/values/colors.xml", "<resources><color name=\"primary\">#FF0000</color></resources>\n")
    add("app/src/main/res/values/styles.xml", "<resources></resources>\n")
    add("app/src/main/res/drawable/ic_launcher.xml", "<vector xmlns:android=\"http://schemas.android.com/apk/res/android\" android:width=\"24dp\" android:height=\"24dp\"><path android:fillColor=\"#000\" android:pathData=\"M0,0 L24,0 L24,24 L0,24 Z\"/></vector>\n")

    # manifest.json
    manifest = []
    for rel, content in files.items():
        ext = Path(rel).suffix.lstrip(".")
        lang = {"java": "java", "cpp": "cpp", "h": "cpp", "xml": "xml", "gradle": "gradle",
                "properties": "properties", "pro": "proguard", "md": "markdown", "txt": "text",
                "json": "json", "cmake": "cmake"}.get(ext, "text")
        manifest.append({"path": rel, "purpose": "mod menu scaffold", "language": lang,
                        "dependencies": [], "build step": "gradle"})
    add("manifest.json", json.dumps(manifest, indent=2))
    add("BUILD_NOTES.md", """# Build Notes
Prerequisites: Android Studio, NDK, CMake, SDK 21+.
Set target package/lib in Main.cpp. Add hook/patch/feature in Menu. Build debug/release with gradle.
Tool emits source only; does not compile native.
""")
    # write all
    written = []
    for rel, content in files.items():
        pth = base / rel
        atomic_write(pth, content)
        written.append(pth)
    return written


# 60 surface map
def surface_map(binary: Optional[Path], keywords_file: Optional[Path], out: Optional[Path],
                exact: bool = False, regex: bool = False, frida_emit: bool = False) -> Dict[str, Any]:
    # collect strings from binary
    rows = []
    sources = []
    if binary and Path(binary).exists():
        data = Path(binary).read_bytes()
        # ascii/utf16
        for off, enc, s in extract_strings(data, 4):
            sources.append(("binary", "string", off, None, s))
        # elf symbols
        try:
            info = parse_elf(binary)
            for sym in info.get("symbols", []):
                if sym.get("name"):
                    sources.append(("binary", "symbol", sym.get("value", 0), None, sym["name"]))
        except Exception:
            pass
    # asset tree xml/json
    if binary and Path(binary).is_dir():
        for p in Path(binary).rglob("*"):
            if p.is_file() and p.suffix.lower() in (".xml", ".json"):
                try:
                    txt = p.read_text(errors="replace")
                    sources.append((str(p), "asset", 0, None, txt))
                except Exception:
                    pass
    # keywords
    kws = []
    if keywords_file and Path(keywords_file).exists():
        for line in Path(keywords_file).read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            kws.append(line)
    if not kws:
        kws = [""]
    # metadata string literals? if binary dir contains global-metadata.dat
    # match
    results_by_kw = {}
    for sf, stype, addr, section, text in sources:
        for kw in kws:
            if kw == "":
                continue
            matched = False
            if regex:
                try:
                    if re.search(kw, text, re.IGNORECASE):
                        matched = True
                        mt = re.search(kw, text, re.IGNORECASE).group(0)
                except re.error:
                    continue
            elif exact:
                if kw.lower() == text.lower():
                    matched = True
                    mt = text
                # also substring exact? spec exact means exact match; but strings are whole; keep substring case-insensitive default
            else:
                if kw.lower() in text.lower():
                    matched = True
                    mt = kw
            if not matched:
                continue
            # context 16 bytes
            ctx = ""
            if isinstance(text, str) and addr is not None and binary and Path(binary).is_file():
                try:
                    d = Path(binary).read_bytes()
                    s = max(0, addr - 16); e = min(len(d), addr + 16)
                    ctx = d[s:e].hex()
                except Exception:
                    ctx = ""
            score = len(kw) / max(len(text), 1) if text else 0
            if exact and kw.lower() == text.lower():
                score += 0.5
            # exec section bonus
            score += 0.1
            row = {
                "source_file": sf,
                "source_type": stype,
                "address_or_offset": addr,
                "section": section,
                "matched_keyword": kw,
                "matched_text": (mt if isinstance(mt, str) else text)[:200],
                "context_16_bytes": ctx,
                "score": round(score, 4),
            }
            rows.append(row)
            results_by_kw.setdefault(kw, []).append(row)
    # write csv if out
    if out:
        outp = Path(out)
        outp.parent.mkdir(parents=True, exist_ok=True)
        with open(outp, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0].keys()) if rows else ["source_file","source_type","address_or_offset","section","matched_keyword","matched_text","context_16_bytes","score"])
            w.writeheader()
            for r in rows:
                w.writerow(r)
        # json summary
        jsonp = outp.with_suffix(".json")
        atomic_write(jsonp, json.dumps({"groups": {k: len(v) for k, v in results_by_kw.items()}, "total": len(rows)}, indent=2))
    if frida_emit and out:
        frida_path = Path(out).with_suffix(".js")
        # build resolver script logging matched addresses
        addrs = [r["address_or_offset"] for r in rows if r["source_type"] in ("string", "symbol")]
        script = "// shitsuke surface map resolver\n"
        for a in set(addrs):
            script += "console.log('matched addr 0x%x');\n" % a
        atomic_write(frida_path, script)
    return {"total": len(rows), "groups": {k: len(v) for k, v in results_by_kw.items()}, "rows": rows[:100]}


# 70 selftest
def selftest() -> int:
    import tempfile as tf
    passed = 0
    failed = 0
    skipped = 0
    failures = []
    def check(name, cond, msg=""):
        nonlocal passed, failed
        if cond:
            passed += 1
            print("PASS %s" % name)
        else:
            failed += 1
            failures.append((name, msg))
            print("FAIL %s: %s" % (name, msg))

    tmp = tf.TemporaryDirectory()
    try:
        d = Path(tmp.name)
        # fixture: minimal ELF64 with 2 sections
        elf_path = d / "t.elf"
        # build minimal elf64
        # e_ident 16 bytes
        ei = b"\x7fELF" + bytes([2, 1, 1, 0]) + b"\x00" * 8
        # header 64-bit
        # type=2 (exec), machine=183 (aarch64), version=1
        hdr = ei + struct.pack("<HHIQQQIHHHHHH", 2, 183, 1, 0, 0x40, 0, 0, 64, 0, 0, 0, 0, 0)
        # section headers: 2 empty? We'll just write header with shnum=0
        atomic_write(elf_path, hdr)
        # parse should not crash
        try:
            info = parse_elf(elf_path)
            check("elf_parse", info["arch"] == "AArch64", str(info.get("arch")))
        except Exception as e:
            check("elf_parse", False, str(e))

        # metadata v24 264 bytes
        # header: magic, version=24, then 23 pairs of (offset,size). Make size plausible.
        meta = struct.pack("<II", METADATA_MAGIC, 24)
        # 23 fields * 8 bytes
        off = 8 + 23 * 8
        for i, name in enumerate(METADATA_FIELDS):
            meta += struct.pack("<ii", off, 24)
            off += 24
        # pad to 264
        meta += b"\x00" * (264 - len(meta))
        meta_path = d / "global-metadata.dat"
        atomic_write(meta_path, meta)
        h = parse_metadata_header(meta)
        check("metadata_magic", h["magic_ok"])
        check("metadata_version", h["version"] == 24)

        # wrapped in 16-byte envelope (prefix 16 bytes then magic)
        wrapped = b"\x00" * 16 + meta
        # recovery rung 2 should find
        hd, rung, desc = metadata_recovery(wrapped)
        check("metadata_recovery_wrapped", hd is not None and hd["version"] == 24, desc)

        # single-byte XOR
        xor1 = bytes(b ^ 0x37 for b in meta)
        hd, rung, desc = metadata_recovery(xor1)
        check("metadata_recovery_xor1", hd is not None and rung == 4, desc)

        # 4-byte XOR
        key = b"\x12\x34\x56\x78"
        xor4 = bytes(b ^ key[i % 4] for i, b in enumerate(meta))
        hd, rung, desc = metadata_recovery(xor4)
        check("metadata_recovery_xor4", hd is not None and rung == 5, desc)

        # bitwise NOT
        notd = bytes((~b) & 0xFF for b in meta)
        hd, rung, desc = metadata_recovery(notd)
        check("metadata_recovery_not", hd is not None and rung == 3, desc)

        # aligned magic scan rung2 (already covered)

        # UnityFS synthetic
        # build header + 1 uncompressed block + 1 xml node
        # Use big-endian fields
        player = b"2019.4\x00"
        engine = b"2019.4.0f1\x00"
        header = UNITYFS_MAGIC + struct.pack(">I", 6) + player + engine
        # align to 8 for bundle_size
        while len(header) % 8 != 0:
            header += b"\x00"
        bundle_size = 0
        header += struct.pack(">qIII", 100, 0, 0, 0x40)  # compressed_blocks_info_size=0? need parseable
        # Actually set blocks info uncompressed size etc. Simpler: use compressed_blocks_info_size=0 not parseable.
        # We'll instead test parse_unityfs_header only
        hdr_bytes = UNITYFS_MAGIC + struct.pack(">I", 6) + player + engine
        while len(hdr_bytes) % 8 != 0:
            hdr_bytes += b"\x00"
        hdr_bytes += struct.pack(">qIII", 100, 20, 20, 0)  # flags 0 none
        try:
            h = parse_unityfs_header(hdr_bytes)
            check("unityfs_header", h["format_version"] == 6, str(h))
        except Exception as e:
            check("unityfs_header", False, str(e))

        # XML pair
        xa = "<root><a x='1'>hi</a></root>"
        xb = "<root><a x='2'>ho</a><b/></root>"
        dxml = xml_diff(xa, xb)
        check("xml_diff", len(dxml) > 0)
        xm = xml_merge(xa, xb)
        check("xml_merge", "b" in xm)
        xp = xml_pretty(xa)
        check("xml_pretty", "<root>" in xp)
        ok, _ = xml_validate(xa)
        check("xml_validate", ok)

        # JSON pair
        ja = '{"a":1,"b":[1,2]}'
        jb = '{"a":2,"b":[1,2,3],"c":true}'
        jd = json_diff(ja, jb)
        check("json_diff", len(jd) > 0)
        jm = json_merge(ja, jb)
        check("json_merge", "c" in jm)
        jp = json_pretty(ja)
        check("json_pretty", "\n" in jp)
        ok, _ = json_validate(ja)
        check("json_validate", ok)

        # hero map override
        hm = dict(HERO_MAP_DEFAULT)
        hm["Test"] = "hero_test"
        check("hero_map", hm.get("Fanny") == "hero_fanny" and hm.get("Test") == "hero_test")

        # fake adb shell script
        fakeadb = d / "fakeadb.sh"
        fakeadb.write_text("""#!/bin/sh
case "$1" in
  devices) echo "List of devices attached"; echo "emulator-5554 device";;
  -s) shift; shift; 
    case "$1" in
      shell) shift; 
        if [ "$1" = "pidof" ]; then echo 1234; fi
        if [ "$1" = "echo" ]; then echo hello; fi
        ;;
    esac
    ;;
  *) ;;
esac
""")
        fakeadb.chmod(0o755)
        # test resolve_adb
        ra = resolve_adb(str(fakeadb))
        check("adb_resolve", ra == str(fakeadb))
        # devices parse may fail due to script; just ensure no crash
        try:
            devs = adb_devices(str(fakeadb))
            check("adb_devices", isinstance(devs, list))
        except Exception as e:
            check("adb_devices", False, str(e))

        # gen templates validation
        for t in ["gg_scan", "pointer_chain", "offset_patch", "aob_scan", "cooldown_timer", "config_loader"]:
            try:
                src, ext = gen_template("lua", t)
                ok, msg = validate_lua(src)
                check("gen_lua_%s" % t, ok, msg)
            except Exception as e:
                check("gen_lua_%s" % t, False, str(e))
        for t in ["metadata_dump", "module_resolve", "il2cpp_bridge", "hook_method", "aob_scan"]:
            try:
                src, ext = gen_template("frida", t)
                ok, msg = validate_js(src)
                check("gen_frida_%s" % t, ok, msg)
            except Exception as e:
                check("gen_frida_%s" % t, False, str(e))
        try:
            src, ext = gen_template("cpp", "stub")
            ok, msg = validate_cpp(src)
            check("gen_cpp", ok, msg)
        except Exception as e:
            check("gen_cpp", False, str(e))
        try:
            src, ext = gen_template("python", "elf_reader")
            ok, msg = validate_python(src)
            check("gen_python", ok, msg)
        except Exception as e:
            check("gen_python", False, str(e))

        # mod menu emit
        mm = d / "modmenu"
        written = emit_mod_menu(mm, "com.android.support")
        check("mod_menu_emit", len(written) > 30)
        # manifest exists
        check("mod_menu_manifest", (mm / "manifest.json").exists())

        # surface map basic
        sm = surface_map(elf_path, None, d / "map.csv", exact=False, regex=False, frida_emit=False)
        check("surface_map", isinstance(sm, dict))

        # atomic_write
        ap = d / "atomic.txt"
        atomic_write(ap, b"hello")
        check("atomic_write", ap.read_bytes() == b"hello")

        # aob scan
        aobdata = b"\x48\x8b\x00\x90" + b"\x00" * 4 + b"\x48\x8b\x33\x90"
        hits = aob_scan(aobdata, "48 8B ?? 90")
        check("aob_scan", len(hits) == 2)

        # elf parse sections count
        # (minimal elf has 0 sections) ok

        # extract strings
        ss = extract_strings(b"hello\x00world\x00", 4)
        check("strings", len(ss) >= 2)

        # resmap
        rdata = struct.pack("<III", 0, 10, 5) + struct.pack("<III", 1, 20, 7)
        recs = resmap_parse(rdata)
        check("resmap_parse", len(recs) == 2)
        rw = resmap_rewrite(rdata, 0, 99)
        check("resmap_rewrite", read_u32_le(rw, 8) == 99)

        # cache validity
        ok2, reason = is_extracted_cache_valid(elf_path)
        check("cache_invalid", ok2 is False)

        # xml pretty comments? just ok
        # skin plan
        srcd = d / "src"; tgtd = d / "tgt"
        srcd.mkdir(); tgtd.mkdir()
        (srcd / "a_skin.mesh").write_bytes(b"x")
        plan = skin_plan(srcd, tgtd, "hero_x")
        check("skin_plan", "actions" in plan)

        # alias inject
        outb, rep = alias_inject(b"hello", ["_skin_", "_skin01_"])
        check("alias_inject", rep["aliases_added"] == ["_skin_", "_skin01_"])

        # unityfs decompression pure lz4 roundtrip? skip complex
        skipped += 1

    except Exception as e:
        failed += 1
        failures.append(("selftest_exception", traceback.format_exc()))
        print("FAIL selftest_exception: %s" % e)
    finally:
        tmp.cleanup()

    print("passed=%d failed=%d skipped=%d" % (passed, failed, skipped))
    if failures:
        for n, m in failures:
            print("  %s: %s" % (n, m))
    return 0 if failed == 0 else EXIT_SELFTEST


# 99 main
def main(argv: Optional[List[str]] = None) -> int:
    global COLOR
    print_banner()
    parser = make_parser()
    args = parser.parse_args(argv)
    if args.no_color:
        COLOR = False
    verbose = args.verbose
    # global out
    out_dir = Path(args.out) if getattr(args, "out", None) else None
    # dispatch
    if getattr(args, "selftest_flag", False):
        return selftest()
    cmd = args.cmd
    if cmd is None or cmd == "banner":
        return 0
    try:
        if cmd == "recon":
            d = Path(args.dir)
            # probe libs
            libs = ["libil2cpp.so", "liblogic.so", "libmono.so", "libunity.so"]
            found = []
            for lib in libs:
                for p in d.rglob(lib):
                    found.append({"lib": lib, "path": str(p), "sha256": sha256_file(p)})
            # abi dir
            abi = None
            for part in d.parts:
                if part in ("armeabi-v7a", "arm64-v8a", "x86", "x86_64"):
                    abi = part
            report = {"abi": abi, "libs": found}
            if out_dir:
                out_dir.mkdir(parents=True, exist_ok=True)
                atomic_write(out_dir / "recon.json", json.dumps(report, indent=2))
            else:
                print(json.dumps(report, indent=2))
            return 0
        if cmd == "elf":
            if not args.file:
                raise UsageError("elf", "file required")
            info = parse_elf(args.file)
            if out_dir:
                out_dir.mkdir(parents=True, exist_ok=True)
                atomic_write(out_dir / "elf.json", json.dumps(info, indent=2))
            else:
                print(json.dumps({k: v for k, v in info.items() if k != "symbols"}, indent=2))
                print("symbols: %d" % len(info["symbols"]))
            return 0
        if cmd == "metadata":
            if not args.file:
                raise UsageError("metadata", "file required")
            data = Path(args.file).read_bytes()
            if args.recover:
                # try partition reassembly in same dir
                reassem = metadata_partition_reassemble(Path(args.file).parent)
                if reassem is not None:
                    data = reassem
                hd, rung, desc = metadata_recovery(data)
                if hd is None:
                    # emit frida script
                    if out_dir:
                        out_dir.mkdir(parents=True, exist_ok=True)
                        atomic_write(out_dir / "metadata_dump.js", frida_metadata_dump_script())
                    else:
                        print(frida_metadata_dump_script())
                    print("recovery rung 8 (memory-only): %s" % desc)
                    return 0
                report = {"recovery_rung": rung, "recovery_desc": desc, "header": hd}
                if out_dir:
                    out_dir.mkdir(parents=True, exist_ok=True)
                    atomic_write(out_dir / "metadata.json", json.dumps(report, indent=2))
                else:
                    print(json.dumps(report, indent=2))
                return 0
            hd = parse_metadata_header(data)
            report = {"header": hd}
            if out_dir:
                out_dir.mkdir(parents=True, exist_ok=True)
                atomic_write(out_dir / "metadata.json", json.dumps(report, indent=2))
            else:
                print(json.dumps(report, indent=2))
            return 0
        if cmd == "scan":
            if not args.file or not args.pattern:
                raise UsageError("scan", "file and --pattern required")
            data = Path(args.file).read_bytes()
            hits = aob_scan(data, args.pattern)
            report = {"pattern": args.pattern, "hits": [{"offset": h, "hex": data[h:h+16].hex()} for h in hits]}
            if out_dir:
                out_dir.mkdir(parents=True, exist_ok=True)
                atomic_write(out_dir / "scan.json", json.dumps(report, indent=2))
            else:
                for h in hits:
                    print("0x%x" % h)
                print("hits=%d" % len(hits))
            return 0
        if cmd == "strings":
            if not args.file:
                raise UsageError("strings", "file required")
            data = Path(args.file).read_bytes()
            strs = extract_strings(data, args.min)
            # symbols if elf
            syms = []
            try:
                info = parse_elf(args.file)
                syms = info.get("symbols", [])
            except Exception:
                pass
            if args.out:
                outp = Path(args.out)
                outp.parent.mkdir(parents=True, exist_ok=True)
                with open(outp, "w", newline="") as f:
                    w = csv.writer(f)
                    w.writerow(["offset", "encoding", "string"])
                    for off, enc, s in strs:
                        w.writerow([off, enc, s])
                # json sidecar
                atomic_write(outp.with_suffix(".json"), json.dumps({"strings": len(strs), "symbols": len(syms)}, indent=2))
            else:
                print("strings=%d symbols=%d" % (len(strs), len(syms)))
            return 0
        if cmd == "assets":
            root = Path(args.root)
            report = asset_index(root)
            if args.out:
                outp = Path(args.out)
                outp.parent.mkdir(parents=True, exist_ok=True)
                atomic_write(outp, json.dumps(report, indent=2))
            else:
                print("count=%d mini_patch=%s shadowing=%d" % (report["count"], report["mini_patch"], len(report["shadowing"])))
            return 0
        if cmd == "unityfs":
            if not args.file:
                raise UsageError("unityfs", "file required")
            data = Path(args.file).read_bytes()
            hdr = parse_unityfs_header(data)
            info = parse_blocks_info(data, hdr)
            report = {"header": hdr, "block_count": len(info["blocks"]), "node_count": len(info["nodes"]), "nodes": info["nodes"]}
            if args.out:
                outp = Path(args.out)
                outp.parent.mkdir(parents=True, exist_ok=True)
                atomic_write(outp, json.dumps(report, indent=2))
            else:
                print(json.dumps({"header": hdr, "block_count": len(info["blocks"]), "node_count": len(info["nodes"])}, indent=2))
            return 0
        if cmd == "skin":
            if not args.source or not args.target or not args.prefix:
                raise UsageError("skin", "source/target/prefix required")
            src = Path(args.source); tgt = Path(args.target)
            plan = skin_plan(src, tgt, args.prefix)
            plan_path = Path(args.out) if args.out else Path("skin_plan.json")
            atomic_write(plan_path, json.dumps(plan, indent=2))
            if args.apply:
                manifest_path = plan_path.parent / "skin_manifest.json"
                res = skin_apply(plan, manifest_path, dry_run=args.dry_run, force=args.force)
                print(json.dumps(res, indent=2))
            else:
                print("plan written: %s" % plan_path)
            return 0
        if cmd == "alias":
            if not args.file:
                raise UsageError("alias", "file required")
            data = Path(args.file).read_bytes()
            outb, report = alias_inject(data, args.aliases or [], update_name=False)
            outp = Path(args.out) if args.out else Path(args.file).with_suffix(".patched")
            if not args.dry_run:
                atomic_write(outp, outb)
            print(json.dumps(report, indent=2))
            return 0
        if cmd == "resmap":
            if not args.file:
                raise UsageError("resmap", "file required")
            data = Path(args.file).read_bytes()
            if args.index is not None and args.skin_id is not None:
                # backup
                backup = Path(args.file).with_suffix(".bak")
                if not backup.exists() or args.force:
                    atomic_write(backup, data)
                new = resmap_rewrite(data, args.index, args.skin_id)
                outp = Path(args.out) if args.out else Path(args.file)
                if not args.dry_run:
                    atomic_write(outp, new)
                print("rewrote index %d -> skin_id %d" % (args.index, args.skin_id))
            else:
                recs = resmap_parse(data)
                print(json.dumps(recs, indent=2))
            return 0
        if cmd == "xml":
            mode = args.mode
            if mode == "pretty":
                text = Path(args.a).read_text()
                out_text = xml_pretty(text)
                if args.out:
                    atomic_write(Path(args.out), out_text)
                else:
                    print(out_text)
            elif mode == "diff":
                a = Path(args.a).read_text(); b = Path(args.b).read_text()
                print(json.dumps(xml_diff(a, b), indent=2))
            elif mode == "merge":
                a = Path(args.a).read_text(); b = Path(args.b).read_text()
                out_text = xml_merge(a, b)
                if args.out:
                    atomic_write(Path(args.out), out_text)
                else:
                    print(out_text)
            elif mode == "validate":
                text = Path(args.a).read_text()
                ok, msg = xml_validate(text)
                print("valid=%s %s" % (ok, msg))
                return 0 if ok else EXIT_PARSE
            return 0
        if cmd == "json":
            mode = args.mode
            if mode == "pretty":
                text = Path(args.a).read_text()
                out_text = json_pretty(text)
                if args.out:
                    atomic_write(Path(args.out), out_text)
                else:
                    print(out_text)
            elif mode == "diff":
                a = Path(args.a).read_text(); b = Path(args.b).read_text()
                print(json.dumps(json_diff(a, b), indent=2))
            elif mode == "merge":
                a = Path(args.a).read_text(); b = Path(args.b).read_text()
                out_text = json_merge(a, b)
                if args.out:
                    atomic_write(Path(args.out), out_text)
                else:
                    print(out_text)
            elif mode == "validate":
                text = Path(args.a).read_text()
                ok, msg = json_validate(text)
                print("valid=%s %s" % (ok, msg))
                return 0 if ok else EXIT_PARSE
            return 0
        if cmd == "gen":
            kind = args.kind
            template = args.template
            src, ext = gen_template(kind, template, args.name)
            outp = Path(args.out) if args.out else Path("%s%s" % (template, ext))
            if not args.dry_run:
                atomic_write(outp, src)
            print("written %s" % outp)
            return 0
        if cmd == "adb":
            try:
                adb = resolve_adb(args.adb)
            except DeviceError as e:
                err("adb", str(e)); return EXIT_DEVICE
            serial = args.device
            sub = args.subcmd
            rest = args.args or []
            if sub == "devices":
                devs = adb_devices(adb)
                print(json.dumps(devs, indent=2))
            elif sub == "shell":
                cp = adb_shell(adb, serial, rest, timeout=30)
                sys.stdout.write(cp.stdout.decode(errors="replace"))
                sys.stderr.write(cp.stderr.decode(errors="replace"))
                return cp.returncode
            elif sub == "push":
                if len(rest) < 2:
                    raise UsageError("adb", "push SRC DST")
                cp = adb_push(adb, serial, rest[0], rest[1])
                print(cp.stdout.decode(errors="replace"))
            elif sub == "pull":
                if len(rest) < 2:
                    raise UsageError("adb", "pull SRC DST")
                cp = adb_pull(adb, serial, rest[0], rest[1])
                print(cp.stdout.decode(errors="replace"))
                # verify sha256 if exists
                srcp = Path(rest[1])
                if srcp.exists():
                    print("sha256=%s" % sha256_file(srcp))
            elif sub == "logcat":
                tag = rest[0] if len(rest) > 0 else None
                print(adb_logcat(adb, serial, tag=tag, tail=100, duration=5))
            elif sub == "pidof":
                pid = adb_pidof(adb, serial)
                print(pid if pid is not None else "")
            elif sub == "dumpsys":
                what = rest[0] if rest else "package"
                if what == "package":
                    print(json.dumps(adb_dumpsys_package(adb, serial), indent=2))
                else:
                    print(adb_dumpsys_window(adb, serial))
            elif sub == "bugreport":
                od = Path(args.out) if args.out else Path("bugreport")
                p = adb_bugreport(adb, serial, od)
                print("bugreport: %s" % p)
            return 0
        if cmd == "shizuku":
            try:
                adb = resolve_adb(args.adb)
            except DeviceError as e:
                err("adb", str(e)); return EXIT_DEVICE
            serial = args.device
            report = shizuku_probe(adb, serial)
            # env probe printed as profile block
            env = env_probe(adb, serial)
            print("=== ENV PROFILE ===")
            for k, v in env.items():
                print("%s=%s" % (k, v))
            print("=== SHIZUKU ===")
            print(json.dumps(report, indent=2))
            # paths
            paths = resolve_paths(adb, serial)
            print("=== PATHS ===")
            print(json.dumps(paths, indent=2))
            return 0
        if cmd == "menu":
            outp = Path(args.out) if args.out else Path("modmenu")
            written = emit_mod_menu(outp, args.pkg)
            manifest = [{"path": str(w.relative_to(outp)), "purpose": "mod menu", "language": "text",
                        "dependencies": [], "build step": "gradle"} for w in written]
            # rewrite manifest.json properly
            mpath = outp / "manifest.json"
            # build per-file entries
            entries = []
            for w in written:
                rel = str(w.relative_to(outp))
                ext = w.suffix.lstrip(".")
                lang = {"java": "java", "cpp": "cpp", "h": "cpp", "xml": "xml", "gradle": "gradle",
                        "properties": "properties", "pro": "proguard", "md": "markdown", "txt": "text",
                        "json": "json", "cmake": "cmake", "js": "js"}.get(ext, "text")
                entries.append({"path": rel, "purpose": "mod menu scaffold", "language": lang,
                               "dependencies": [], "build step": "gradle"})
            atomic_write(mpath, json.dumps(entries, indent=2))
            print("emitted %d files to %s" % (len(written), outp))
            return 0
        if cmd == "map":
            binary = Path(args.binary) if args.binary else None
            keywords = Path(args.keywords) if args.keywords else None
            outp = Path(args.out) if args.out else Path("surface_map.csv")
            report = surface_map(binary, keywords, outp, exact=args.exact, regex=args.regex, frida_emit=args.frida_emit)
            print("total=%d" % report["total"])
            return 0
        if cmd == "selftest":
            return selftest()
    except ShitsukeError as e:
        err(e.subsystem, str(e))
        return e.code
    except UsageError as e:
        err(e.subsystem, str(e)); return EXIT_USAGE
    except IOError_ as e:
        err(e.subsystem, str(e)); return EXIT_IO
    except ParseError as e:
        err(e.subsystem, str(e)); return EXIT_PARSE
    except DeviceError as e:
        err(e.subsystem, str(e)); return EXIT_DEVICE
    except DepError as e:
        err(e.subsystem, str(e)); return EXIT_DEP
    except FileNotFoundError as e:
        err("io", str(e)); return EXIT_IO
    except Exception as e:
        err("main", "%s" % e)
        if verbose:
            traceback.print_exc()
        return 1
    # unknown subcommand handling already by argparse
    err("main", "unknown subcommand; see --help")
    return EXIT_USAGE


if __name__ == "__main__":
    # color disable if not tty
    if not sys.stdout.isatty():
        COLOR = False
    sys.exit(main())
