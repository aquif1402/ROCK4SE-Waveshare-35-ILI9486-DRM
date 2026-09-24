# ROCK 4 SE Waveshare 3.5" ILI9486 DRM / MIPI-DBI

Hardware-tested Linux DRM/MIPI-DBI driver setup for the **Waveshare 3.5-inch RPi LCD (B)** with the **Radxa ROCK 4 SE (RK3399)**.

This repository contains a working snapshot taken from a live ROCK 4 SE system. The driver code is a modification of the Linux kernel's ILI9486 TinyDRM/MIPI-DBI implementation, adapted for the Waveshare board's SPI-to-16-bit-parallel interface and the tested ROCK 4 SE configuration.

> **Status:** Hardware-tested working backup. This repository targets the exact kernel/configuration described below and should not be treated as a drop-in driver for arbitrary ILI9486 panels or kernel versions.
>
> 
> ☕ **Support the project:** [PayPal.Me/AQUIFKHAN](https://www.paypal.com/paypalme/AQUIFKHAN)
>
> 
## Tested configuration

| Item | Tested value |
|---|---|
| Board | Radxa ROCK 4 SE |
| SoC | Rockchip RK3399 |
| OS | Debian GNU/Linux 12 (Bookworm) |
| Kernel | `6.1.115-8-rk2501` |
| Architecture | arm64 |
| LCD | Waveshare 3.5inch RPi LCD (B) |
| Controller | ILI9486 |
| LCD resolution | 480 × 320 |
| DRM mode | 320 × 480 with rotation for landscape |
| SPI | 32 MHz tested |
| Pixel format | RGB565 |
| Interface | SPI + MIPI-DBI |

## What is modified

### `drivers/ili9486.c`

The ILI9486 driver is based on the Linux kernel TinyDRM ILI9486 driver and has been adapted for the tested Waveshare display.

The Waveshare board uses an SPI-to-16-bit-parallel converter. Consequently, command/data transfers need to be handled differently from a conventional direct 8-bit SPI ILI9486 connection.

The tested initialization sequence includes:

- Waveshare-specific hardware reset handling
- Interface configuration
- Sleep-out / display-on sequence
- 18-bit initialization followed by RGB565 operation
- Display inversion control
- Power-control settings
- VCOM configuration
- Frame-rate configuration
- Positive/negative gamma tables
- Rotation/address-mode configuration

### `drivers/drm_mipi_dbi.c`

This is a modified copy of the Linux DRM MIPI-DBI helper used by the tested kernel environment.

The working snapshot contains changes related to:

- ROCK 4 SE/RK3399 SPI transfer handling
- 16 KiB transfer chunking
- Differential display update support present in this working snapshot
- Display update optimization used during testing

Because `drm_mipi_dbi.c` is a kernel DRM subsystem source file, this repository is **kernel-version dependent**. The included `.ko` modules were built for the exact kernel listed above.

## Device tree

`dtb/35b1-mipidbi.dtbo` is the tested overlay.

The tested configuration uses:

- Compatible: `waveshare,rpi-lcd-35`
- SPI maximum frequency: 32 MHz
- Rotation: 270°
- LCD reset GPIO: GPIO4_D5 / physical pin 22
- LCD D/C GPIO: GPIO4_D4 / physical pin 18
- Active-low reset configuration

The repository also contains:

- `rk3399-rock-4se-base.dtb` — stock base DTB used as the reference
- `rk3399-rock-4se-mipidbi.dtb` — merged DTB from the tested working system

The prebuilt DTBs/DTBO should be considered **tested binaries**, not universal DT files for every ROCK 4 SE software image.

## Directory layout

```text
.
├── README.md
├── LICENSE
├── NOTICE
├── UPSTREAM.md
├── config/
│   └── extlinux.conf
├── drivers/
│   ├── drm_mipi_dbi.c
│   ├── drm_mipi_dbi.ko
│   ├── ili9486.c
│   └── ili9486.ko
└── dtb/
    ├── 35b1-mipidbi.dtbo
    ├── rk3399-rock-4se-base.dtb
    └── rk3399-rock-4se-mipidbi.dtb
```

## Installation

**Back up your current boot configuration and DTB before changing anything.**

The safest approach is to use the files as a reference for reproducing the working configuration rather than blindly replacing files on another system.

At a high level:

1. Verify the running kernel:

```bash
uname -a
uname -r
```

2. Confirm that the system matches the tested ROCK 4 SE configuration.

3. Install/load the matching `drm_mipi_dbi.ko` and `ili9486.ko` modules.

4. Install the tested Device Tree configuration appropriate for your boot setup.

5. Reboot.

6. Verify DRM and SPI/LCD initialization with:

```bash
dmesg | grep -Ei 'ili9486|mipi|drm|spi'
ls -l /dev/dri/
```

### Important

Do not mix the included `.ko` files with a substantially different kernel. Kernel modules must match the kernel build/API they were compiled against.

## Building from source

The source files in this repository are intended to be used with the corresponding Linux kernel source tree and configuration.

For reproducible builds, use the exact tested kernel:

```text
Linux 6.1.115-8-rk2501
```

and the corresponding ROCK 4 SE kernel configuration and headers.

The prebuilt modules are provided for convenience; they are not a replacement for building against your own kernel.

## Performance / transfer-size note

During testing on the ROCK 4 SE, large SPI transfers produced DMA-related failures. The working driver limits individual SPI data transfers to 16 KiB.

This should be understood as a **tested configuration value for the ROCK 4 SE setup**, not as a universal ILI9486 or Linux SPI limitation.

## Known limitations

- The included modules are tied to the tested kernel version.
- The initialization sequence is tuned for the tested Waveshare 3.5-inch LCD.
- Other ILI9486 panels may require different initialization, gamma, timing, GPIO, or rotation settings.
- The prebuilt DTB/DTBO files should not be assumed to work unchanged on other Radxa OS releases.
- This repository contains a modified DRM MIPI-DBI core helper; future kernel changes may require porting the modifications.

## Original Linux driver / attribution

This project is derived from the Linux kernel DRM TinyDRM/MIPI-DBI ILI9486 implementation.

The original source and its copyright/license notices remain in the source files. See [`UPSTREAM.md`](UPSTREAM.md) for attribution and guidance on comparing this snapshot with the corresponding Linux kernel sources.

## Support the project

If this work helped you get the Waveshare 3.5-inch ILI9486 working with DRM/MIPI-DBI on the ROCK 4 SE, you can support continued development:

[![Support via PayPal](https://img.shields.io/badge/Support-PayPal-blue?logo=paypal)](https://www.paypal.com/paypalme/AQUIFKHAN)

## Contributing

Issues and pull requests are welcome.

When reporting a problem, include:

```bash
uname -a
cat /etc/os-release
dmesg | grep -Ei 'ili9486|mipi|drm|spi'
```

and describe:

- ROCK 4 SE model/revision
- LCD model
- kernel version
- SPI frequency
- DT overlay/configuration
- whether the stock driver or modified driver was used

## License

The driver sources use the GPL license identifiers included in the original source files. See [`LICENSE`](LICENSE).
