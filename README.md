# ROCK 4 SE Waveshare 3.5" ILI9486 DRM / MIPI-DBI

Hardware-tested Linux DRM/MIPI-DBI driver setup for the **Waveshare 3.5-inch RPi LCD (B)** with the **Radxa ROCK 4 SE (RK3399)**.

> **Status: BETA / experimental.** This is a hardware-tested working snapshot taken from a live ROCK 4 SE system. It is shared for experimentation, reproduction, and further development. The included kernel modules match the tested kernel `6.1.115-8-rk2501` and are not generic drop-in modules for other kernels. **Do not expect every feature or configuration to work unchanged on another board, LCD revision, kernel, OS image, or SPI setup. Users may need to troubleshoot and adapt the Device Tree, kernel modules, initialization sequence, timings, GPIOs, or surrounding graphics stack.**

> **AI-assisted development:** AI tools were used to help analyze, modify, debug, and document parts of this driver and its supporting configuration. The resulting code was tested on the hardware configuration described in this repository, but AI assistance does not imply that the code is universally correct or production-ready.

> **Goal:** Expose the Waveshare ILI9486 through Linux DRM/KMS so graphics applications and compositors can use a modern display path. The LCD driver itself does not provide GPU acceleration; GPU rendering remains the responsibility of the graphics stack/application.

> ☕ **Support the project:** [PayPal.Me/AQUIFKHAN](https://www.paypal.com/paypalme/AQUIFKHAN)

## Tested configuration

| Item | Tested value |
|---|---|
| Board | Radxa ROCK 4 SE |
| SoC | Rockchip RK3399 |
| OS | Debian GNU/Linux 12 (Bookworm) |
| Kernel | `6.1.115-8-rk2501` |
| Architecture | arm64 |
| LCD | Waveshare 3.5-inch RPi LCD (B) |
| Controller | ILI9486 |
| Logical display | 480 × 320 landscape |
| Native panel mode | 320 × 480 |
| Tested rotation | 90° in the included DTS |
| Tested SPI rate | 32 MHz maximum tested stable point |
| SPI signal limit | Above 32 MHz, signal degradation was observed on the tested display/interface; higher rates are not considered supported by this snapshot |
| Panel interface | Waveshare board with SPI-to-parallel/shift-register interface |
| Pixel format | RGB565 |
| Interface | SPI + MIPI-DBI |

## Hardware / SPI limitation

This driver was tested specifically with the **Waveshare 3.5-inch RPi LCD (B)** using the display board's SPI-to-parallel/shift-register interface. On the tested ROCK 4 SE setup, **32 MHz SPI is the highest rate that was considered stable**. Above 32 MHz, signal degradation was observed and display communication became unreliable.

Therefore, the repository should not be interpreted as proving that the LCD, its interface hardware, or the driver supports higher SPI frequencies. Cable quality, board revision, power, signal integrity, kernel SPI configuration, and other hardware factors can change the result.

## Compatibility / troubleshooting expectation

This project is **not a plug-and-play universal ILI9486 driver**. The known-good snapshot is tied to a specific ROCK 4 SE, Waveshare LCD revision, kernel, Device Tree configuration, GPIO wiring, and SPI timing. Other users may need to troubleshoot or modify the configuration before the display works correctly.

Possible differences include:

- LCD revision or controller configuration
- SPI signal integrity and maximum reliable clock rate
- GPIO numbering or reset/DC polarity
- Device Tree layout and bootloader configuration
- Kernel version and DRM/MIPI-DBI APIs
- Panel initialization, gamma, inversion, rotation, and pixel-format settings
- Other SPI devices sharing the controller
- DRM/KMS, fbdev emulation, compositor, or application configuration

A working result on one system should therefore be treated as a **reference configuration**, not a guarantee for another system.

## Repository contents

- `ili9486.c` — Waveshare-specific ILI9486 DRM/TinyDRM driver modification.
- `drm_mipi_dbi.c` — modified DRM MIPI-DBI helper used by the tested kernel.
- `35b1-mipidbi.dts` / `.dtbo` — tested Device Tree configuration.
- `drm_mipi_dbi.ko` and `ili9486.ko` — prebuilt modules for the exact tested kernel.
- `rk3399-rock-4se-mipidbi.dtb` — merged DTB captured from the tested system.
- `driver_gui.py` — optional local web management tool.
- `brightness_overlay.py` / `brightness-cli` — optional X11 software brightness overlay.
- `ROCK4SE_MIPIDBI_AND_DRIVER_GUI_GUIDE.md` — detailed setup and troubleshooting guide.

## Important source review notes

The driver files are intentionally preserved as the **known-working snapshot**. Static review found several areas that should be treated as follow-up engineering work before calling the driver production-ready:

1. The custom `waveshare_command()` differs from upstream by not using the SPI bus lock around the command/data transaction. Upstream's Waveshare path does use `spi_bus_lock()` / `spi_bus_unlock()`. This matters if another SPI device can share the controller.
2. The differential-update implementation updates its shadow buffer before confirming every SPI write succeeded. A failed transfer can therefore leave the software shadow ahead of the physical LCD.
3. `skip_nth` blanks pixels in the transmitted buffer; it does **not** reduce the number of SPI bytes transferred. It should not be described as a bandwidth-halving feature.
4. The differential shadow/staging buffers are global to the module rather than per display device, so the implementation is intended for the tested single-panel configuration.

These points are documented rather than silently changed because the included `.ko` files are the exact binaries from the known-working snapshot.

## Security note for `driver_gui.py`

The original live-system copy contained commands that supplied a local password to `sudo`. That password is **not included in this public repository**. The packaged GUI uses non-interactive `sudo -n` for privileged actions and binds to `127.0.0.1` by default.

The GUI can edit driver source, rebuild modules, modify Device Tree files, restart services, and reboot the machine. Treat it as an **administrative tool**, not as a general-purpose public web application. For remote use, prefer an SSH tunnel. If you intentionally expose it on a trusted LAN, set `DRIVER_GUI_HOST=0.0.0.0` and provide your own authentication/firewall controls.

## Build

The included `Makefile` targets the tested kernel by default:

```bash
make
```

or explicitly:

```bash
make KDIR=/lib/modules/$(uname -r)/build
```

Do not expect the included `.ko` files to load on a different kernel. Their recorded vermagic is:

```text
6.1.115-8-rk2501 SMP mod_unload modversions aarch64
```

## Device Tree

The tested overlay uses:

- `waveshare,rpi-lcd-35`
- SPI transfer limit: 32 MHz
- reset: GPIO4_D5 / physical pin 22
- D/C: GPIO4_D4 / physical pin 18
- rotation: 90°
- RGB565

The DTS also assigns a 64 MHz SPI clock parent. That is a clock-source setting; the tested SPI transfer rate remains 32 MHz.

## Attribution

`ili9486.c` is derived from the Linux kernel ILI9486 TinyDRM driver, including the upstream Waveshare-specific SPI-to-16-bit-parallel handling. `drm_mipi_dbi.c` is derived from the Linux DRM MIPI-DBI helper and contains ROCK 4 SE-specific modifications.

See `UPSTREAM.md` and the SPDX identifiers in the source files for licensing/attribution information.

## Documentation

See [`ROCK4SE_MIPIDBI_AND_DRIVER_GUI_GUIDE.md`](ROCK4SE_MIPIDBI_AND_DRIVER_GUI_GUIDE.md) for installation, Device Tree setup, GUI usage, brightness overlay, troubleshooting, and tuning.

## Support

If this project helped you, you can support continued development:

[![Support via PayPal](https://img.shields.io/badge/Support-PayPal-blue?logo=paypal)](https://www.paypal.com/paypalme/AQUIFKHAN)
