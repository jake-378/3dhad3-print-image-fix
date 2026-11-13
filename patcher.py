#!/usr/bin/env python3
"""
Patch 3D Home Architect Deluxe 3.0 (3DHOMEV3.EXE) so "3D View -> Print Image"
works on modern Windows with 32-bit desktop color depth.

Drop this file next to an untouched 3DHOMEV3.EXE and run:

  python patcher.py

On first patch it creates 3DHOMEV3.EXE.bak (only if missing), then patches.
--restore copies the .bak back over the EXE.

Bug:
  When BITSPIXEL*PLANES > 24, the app skipped writing the DIB bit-count and
  passed stack garbage into GetDIBits. Print Image then failed silently.

Fix:
  At VA 0x0050FE93, replace JG (7F 06) with NOP NOP (90 90) so the existing
  clamp-to-24 instruction always runs.

Usage:
  python patcher.py              # backup once (if needed), then patch
  python patcher.py --check      # show whether already patched
  python patcher.py --restore    # restore EXE from .bak
  python patcher.py path\\to\\3DHOMEV3.EXE
"""

from __future__ import annotations

import argparse
import struct
import sys
from pathlib import Path

PATCH_VA = 0x0050FE93
# cmp ecx, 18h ; jg +6
UNPATCHED = bytes.fromhex("83F9187F06")
# cmp ecx, 18h ; nop ; nop
PATCHED = bytes.fromhex("83F9189090")


def pe_image_base(data: bytes) -> int:
    e_lfanew = struct.unpack_from("<I", data, 0x3C)[0]
    opt = e_lfanew + 24
    magic = struct.unpack_from("<H", data, opt)[0]
    if magic == 0x10B:  # PE32
        return struct.unpack_from("<I", data, opt + 28)[0]
    if magic == 0x20B:  # PE32+
        return struct.unpack_from("<Q", data, opt + 24)[0]
    raise ValueError(f"Unsupported optional header magic: {magic:#x}")


def rva_to_file_offset(data: bytes, rva: int) -> int:
    e_lfanew = struct.unpack_from("<I", data, 0x3C)[0]
    coff = e_lfanew + 4
    num_sections = struct.unpack_from("<H", data, coff + 2)[0]
    size_opt = struct.unpack_from("<H", data, coff + 16)[0]
    sec_off = coff + 20 + size_opt

    for i in range(num_sections):
        s = sec_off + i * 40
        vsize, vaddr, rawsize, rawptr = struct.unpack_from("<IIII", data, s + 8)
        span = max(vsize, rawsize)
        if vaddr <= rva < vaddr + span:
            return rawptr + (rva - vaddr)
    raise ValueError(f"RVA {rva:#x} not found in any section")


def patch_offset_and_context(data: bytes) -> tuple[int, bytes]:
    """Return file offset of the 2-byte site, and 5-byte context (cmp + site)."""
    image_base = pe_image_base(data)
    rva = PATCH_VA - image_base
    file_off = rva_to_file_offset(data, rva)
    return file_off, data[file_off - 3 : file_off + 2]


def status_for(context: bytes) -> str:
    if context == PATCHED:
        return "patched"
    if context == UNPATCHED:
        return "unpatched"
    return "unexpected"


def default_exe() -> Path:
    return Path(__file__).resolve().parent / "3DHOMEV3.EXE"


def backup_path(exe: Path) -> Path:
    return exe.with_suffix(exe.suffix + ".bak")


def read_exe(exe: Path) -> bytearray:
    try:
        return bytearray(exe.read_bytes())
    except PermissionError:
        print(
            f"ERROR: cannot read {exe} (is it running?). Close the program and try again.",
            file=sys.stderr,
        )
        raise SystemExit(1)


def write_exe(exe: Path, data: bytes) -> None:
    try:
        exe.write_bytes(data)
    except PermissionError:
        print(
            f"ERROR: cannot write {exe} (is it running?). Close the program and try again.",
            file=sys.stderr,
        )
        raise SystemExit(1)


def cmd_check(exe: Path) -> int:
    data = read_exe(exe)
    _, context = patch_offset_and_context(data)
    state = status_for(context)
    bak = backup_path(exe)
    print(f"File:   {exe}")
    print(f"Status: {state}")
    print(f"Bytes:  {context.hex()}")
    print(f"Backup: {'yes' if bak.exists() else 'no'} ({bak.name})")
    if state == "unexpected":
        print(f"Need:   {UNPATCHED.hex()} (stock) or {PATCHED.hex()} (patched)")
        return 2
    return 0


def cmd_patch(exe: Path) -> int:
    if not exe.exists():
        print(f"ERROR: file not found: {exe}", file=sys.stderr)
        print("Put patcher.py in the same folder as 3DHOMEV3.EXE, or pass the EXE path.", file=sys.stderr)
        return 1

    data = read_exe(exe)
    file_off, context = patch_offset_and_context(data)

    if context == PATCHED:
        print(f"Already patched: {exe}")
        return 0
    if context != UNPATCHED:
        print(f"ERROR: unexpected bytes at patch site: {context.hex()}", file=sys.stderr)
        print(f"Expected stock EXE bytes: {UNPATCHED.hex()}", file=sys.stderr)
        return 2

    bak = backup_path(exe)
    if not bak.exists():
        write_exe(bak, bytes(data))
        print(f"Backup created: {bak.name}")

    data[file_off] = 0x90
    data[file_off + 1] = 0x90
    write_exe(exe, data)

    _, after = patch_offset_and_context(exe.read_bytes())
    print(f"Patched: {exe}")
    print(f"Before:  {context.hex()}")
    print(f"After:   {after.hex()}")
    print("3D View -> Print Image should work on 32-bit displays.")
    return 0


def cmd_restore(exe: Path) -> int:
    bak = backup_path(exe)
    if not bak.exists():
        print(f"ERROR: backup not found: {bak}", file=sys.stderr)
        print("Run patcher.py once on a stock EXE first so a .bak is created.", file=sys.stderr)
        return 1
    if not exe.exists():
        print(f"ERROR: file not found: {exe}", file=sys.stderr)
        return 1

    write_exe(exe, bak.read_bytes())
    print(f"Restored: {exe}")
    print(f"From:     {bak.name}")
    return cmd_check(exe)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Patch 3DHOMEV3.EXE so 3D Print Image works on 32-bit displays."
    )
    parser.add_argument(
        "exe",
        nargs="?",
        type=Path,
        default=None,
        help="Path to 3DHOMEV3.EXE (default: same folder as this script)",
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--check", action="store_true", help="Check patch status only")
    group.add_argument("--restore", action="store_true", help="Restore EXE from .bak")
    args = parser.parse_args(argv)

    exe = (args.exe or default_exe()).resolve()
    if args.check:
        return cmd_check(exe)
    if args.restore:
        return cmd_restore(exe)
    return cmd_patch(exe)


if __name__ == "__main__":
    raise SystemExit(main())
