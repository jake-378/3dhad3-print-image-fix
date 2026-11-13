# 3D Home Architect Deluxe 3.0: "Print Image" fix for Windows 10/11

A 2-byte binary patch, a Python patcher, and a reverse-engineering write-up for a bug that breaks **3D View → Print Image** in 3D Home Architect Deluxe 3.0 (Broderbund, late 1990s) on modern Windows.

## Background

This program had been running for years on a Windows XP machine, where everything worked, including printing the 3D view. When that machine crashed, we had to move the program to newer computers running Windows 11.

The program itself ran fine on Windows 11, but on some computers **3D View → Print Image** did nothing:

- The taskbar flickered briefly
- No print dialog appeared
- No print job was created (Microsoft Print to PDF failed too)
- No error message
- Normal 2D printing still worked, and the 3D view rendered correctly

The exact same program folder printed 3D images on one Windows 10 PC, but failed on a Windows 10 VM and on Windows 11. An old support thread from around 2012 described the same problem on Windows 7; the only official advice was to go back to Windows XP/2000.

The usual fixes didn't help: compatibility modes, high-DPI settings, legacy DirectX/D3DRM DLLs, DDrawCompat, and DxWnd. So we reverse engineered the executable with Ghidra and x32dbg, found the bug, fixed it with a 2-byte patch, wrote a patcher, and documented the whole process.

## The bug

When the desktop runs in 32-bit color (which modern Windows always reports), the program leaves a local variable uninitialized and passes stack garbage to `GetDIBits` as the image's bit depth. The image conversion fails, and the Print Image routine quietly exits before it ever shows the print dialog.

See [WRITEUP.md](WRITEUP.md) for the full investigation.

## Quick start

1. Close 3D Home Architect.
2. Copy `patcher.py` into the folder that contains `3DHOMEV3.EXE`.
3. Run:

```text
python patcher.py
```

Requires Python 3.8+. No third-party packages.

## Commands

| Command | What it does |
|---|---|
| `python patcher.py` | Creates `3DHOMEV3.EXE.bak` (only if one doesn't exist yet), then patches the EXE |
| `python patcher.py --check` | Shows whether the EXE is patched and whether a backup exists |
| `python patcher.py --restore` | Copies `3DHOMEV3.EXE.bak` back over the EXE |
| `python patcher.py path\to\3DHOMEV3.EXE` | Uses a specific EXE path (works with `--check` and `--restore` too) |

The script checks the bytes at the patch site before writing anything. If the EXE isn't the expected version, it refuses to patch.

## What the patch changes

| | Value |
|---|---|
| Virtual address | `0x0050FE93` |
| File offset | `0x10F293` |
| Original bytes | `7F 06` (`JG +6`) |
| Patched bytes | `90 90` (`NOP NOP`) |

With the jump removed, the program's existing "clamp color depth to 24-bit" instruction always runs, so 32-bit displays get a valid 24-bit image.

## Tested on

- Windows 11 Pro (build 26200), 32-bit desktop color
- A real printer and Microsoft Print to PDF

## Tools used

- [Ghidra](https://ghidra-sre.org/) for static analysis and decompilation
- [x32dbg](https://x64dbg.com/) for live debugging of the 32-bit process
- Sysinternals `strings` and API Monitor
- Python for the patcher

## Disclaimer

This repo doesn't include any of the original program's files. You need your own copy of 3D Home Architect Deluxe 3.0. The patcher only modifies your local copy. Keep the backup.
