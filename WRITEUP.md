# Write-up: why "Print Image" silently failed

## The problem

3D Home Architect Deluxe 3.0 is a 32-bit Windows program from the late 1990s. On the original Windows XP machine, **3D View → Print Image** printed the current 3D view. After that machine crashed and the program was moved to newer computers, Print Image stopped working on a Windows 10 VM and on Windows 11. Clicking it only made the taskbar flicker: no print dialog, no print job, no error. 2D printing worked, and the 3D view rendered correctly. The same program folder still worked on one Windows 10 PC.

## What didn't help

We tried these first, and none of them changed anything:

- Compatibility modes (Windows XP SP3, Windows 98/ME) and high-DPI overrides
- Legacy DirectX 5.2 / D3DRM DLLs placed next to the EXE
- DDrawCompat (it loaded, but Print Image made no relevant DirectDraw calls)
- DxWnd GDI options
- Patching the `PrintDlg` flags (`0x5004` → `0x0104`)

The flags patch was a red herring. As it turned out, execution never got as far as `PrintDlg`.

## Static analysis (Ghidra)

`strings` showed the EXE imports normal GDI printing APIs (`PrintDlgA`, `StartDocA`, `StartPage`, `GetDIBits`, `StretchDIBits`), so the feature is native printing, not a call out to an external tool.

Following the "Print Image" string led to the handler `FUN_0050FEF0`, which runs for menu command ID `0x72`. Its intended flow:

1. `FUN_0050FD79`: capture the 3D view and convert it to a DIB (device-independent bitmap)
2. If that returns NULL, **exit silently**
3. `FUN_004FEE2A`: show the print dialog (`PrintDlgA`) and get a printer DC
4. `StartDocA` → `StartPage` → `StretchDIBits` → `EndPage` → `EndDoc`

Step 2 matches the symptom exactly: no dialog and no error.

## A contradiction worth resolving

An early debugging session suggested `FUN_0050FD79` returned a non-zero value (`0x167`), yet the call to the print dialog at `0x0050FF30` never ran. The static code made that impossible: a non-zero return has to reach `0x0050FF30`.

Instead of guessing, we checked the live process against Ghidra:

- The module base in the debugger matched Ghidra (`0x00400000`)
- The live bytes at the call site matched Ghidra byte for byte

Single-stepping showed the real answer: `FUN_0050FD79` returned **0**. The earlier `0x167` reading was a wrong observation. With that corrected, everything was consistent: NULL image → early exit → no dialog.

## Finding the failure (x32dbg)

Breakpoints along the image pipeline narrowed it down:

| Step | Result |
|---|---|
| Screen capture (`FUN_00538339`) | Succeeded: valid `HBITMAP` (`0x3D05147E`) |
| Display depth, `BITSPIXEL × PLANES` | `32` |
| Bit depth passed to the DIB converter (`FUN_00537F0B`) | `0xF39C` (garbage) |
| `GetDIBits` | Failed (returned 0) |
| `FUN_0050FD79` return value | NULL |

`0xF39C` isn't a valid bit depth, so the question became where that value came from.

## Root cause

`FUN_0050FD79` asks the display for its color depth and maps it to a supported DIB bit count. Reconstructed as C:

```c
int depth = GetDeviceCaps(hdc, BITSPIXEL) * GetDeviceCaps(hdc, PLANES);
short bitCount;              /* never initialized */

if      (depth <= 1)  bitCount = 1;
else if (depth <= 4)  bitCount = 4;
else if (depth <= 8)  bitCount = 8;
else if (depth <= 24) bitCount = 24;
/* depth == 32: nothing assigns bitCount */
```

The assembly for the last step:

```text
0050FE8C  MOVSX ECX, word [EBP-1Ch]     ; depth
0050FE90  CMP   ECX, 18h                ; compare with 24
0050FE93  JG    0050FE9B                ; depth > 24: skip the store
0050FE95  MOV   word [EBP-18h], 18h     ; bitCount = 24
0050FE9B  ...                           ; bitCount used as biBitCount
```

In the late 1990s, many systems ran 16- or 24-bit color, where this code works. Modern Windows reports 32-bit color, so `bitCount` keeps whatever happened to be on the stack. The converter builds a `BITMAPINFOHEADER` with that value, `GetDIBits` rejects it, and Print Image gives up without telling the user.

## The fix

Replace the `JG` at `0x0050FE93` (`7F 06`) with two `NOP`s (`90 90`). Now any depth that reaches this point is clamped to 24 bits by an instruction that was already there.

Why this fix:

- **Smallest possible change.** Two bytes, no code caves, no new logic.
- **24-bit is a safe target.** `GetDIBits` and printer drivers handle 24-bit DIBs well, and the print path already scales the image with `StretchDIBits`.
- **Easy to verify and undo.** The patcher checks the original bytes before writing and keeps a backup.

We tested it as a live memory patch in x32dbg first. Execution reached `0x0050FF30`, the print dialog appeared, and a real print job completed. Then we applied the same 2 bytes to the file on disk.

## Open questions

- **Why did one Windows 10 PC work?** Not confirmed, because that machine is no longer available. The value comes from uninitialized stack memory, so whatever earlier code left there decides the outcome; a leftover value that happens to be a valid bit count would work. A display or compatibility setting that reports 24-bit color or less would also avoid the bug.

## Takeaways

- A silent failure usually means a guard clause somewhere. Finding the `if (result == NULL) return;` narrowed the search a lot.
- When a debugger observation contradicts the static code, re-check the observation before building theories on it.
- Uninitialized variables can hide for decades if the input that triggers them doesn't show up until later. Here, that input was a 32-bit desktop.
