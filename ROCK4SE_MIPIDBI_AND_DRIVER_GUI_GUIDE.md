# Comprehensive Guide: Setup MIPI-DBI DRM Driver & Use `driver_gui.py` on Radxa ROCK 4 SE

> **Public repository note:** The GUI is an administrative tool. The public version does not embed the original system password and binds to localhost by default. Do not expose it to an untrusted network without adding authentication/firewalling and carefully configuring privileged commands.

**Target Hardware:** Radxa ROCK 4 SE (Rockchip RK3399)  
**Target Operating System:** Debian 12 (Bookworm) / Armbian / Ubuntu  
**Target Kernel:** Linux 6.1.115-8-rk2501 (arm64)  
**Display:** Waveshare 3.5" (B) ILI9486 SPI LCD (480×320 16-bpp RGB565)  
**Project status:** Beta / experimental; hardware-tested on the specific ROCK 4 SE configuration documented here. AI tools were used to assist with driver modification, debugging, and documentation. The resulting snapshot is not guaranteed to work unchanged on other hardware or kernels.  
**SPI limit observed:** 32 MHz stable on the tested setup; above 32 MHz, signal degradation was observed.  

---

## 📋 Table of Contents
1. [System Overview & Architecture](#1-system-overview--architecture)
2. [Hardware Pinout & 40-Pin Header Wiring](#2-hardware-pinout--40-pin-header-wiring)
3. [Root Causes Solved (Why Stock Kernels Show White Screen)](#3-root-causes-solved)
4. [Step-by-Step: Setup MIPI-DBI DRM Driver on ROCK 4 SE](#4-step-by-step-setup-mipi-dbi-drm-driver)
5. [Step-by-Step: How to Use `driver_gui.py` Web Dashboard](#5-step-by-step-how-to-use-driver_guipy)
6. [Differential Display Engine & Performance Tuning](#6-differential-display-engine--performance-tuning)
7. [Software Brightness Control (`brightness_overlay.py` & `brightness-cli`)](#7-software-brightness-control)
8. [Troubleshooting & Verification Commands](#8-troubleshooting--verification-commands)

---

## 1. System Overview & Architecture

The LCD driver does not itself provide GPU acceleration. It exposes the panel through Linux DRM/KMS so applications and compositors that render through the GPU/DRM stack can use the LCD through a modern display path. A fbdev-emulation node may also be created for legacy applications.

This setup replaces `fbtft` with a native Linux **DRM / KMS** stack:
- **Core DRM Layer:** Modified `drm_mipi_dbi.ko` with DMA chunking and high-performance differential updates.
- **Panel Driver:** Modified `ili9486.ko` with Waveshare IPS panel initialization, color calibration, and dynamic sysfs parameters.
- **Created Nodes:**
  - A DRM device under `/dev/dri/card*` for the SPI panel (the exact card number is not guaranteed)
  - A fbdev-emulation node such as `/dev/fb1` may be present (the exact node number is not guaranteed)
- **Web Dashboard:** `driver_gui.py` running on port `5000` providing browser-based real-time parameter tuning, driver recompilation, and framebuffer live preview.

---

## 2. Hardware Pinout & 40-Pin Header Wiring

The Waveshare 3.5" (B) display plugs directly onto the 40-pin GPIO header of the ROCK 4 SE:

| Pin # | Pin Name | RK3399 Pin | Kernel Descriptor | Signal Direction | Description |
|:---:|:---|:---|:---|:---:|:---|
| **1** | 3.3V | - | - | Power | 3.3V Logic Supply |
| **2, 4** | 5V | - | - | Power | 5V Main Power |
| **6, 9** | GND | - | - | Power | Ground |
| **18** | GPIO4_D4 | GPIO 156 | `dc-gpios` (`ACTIVE_HIGH`) | ROCK 4 → LCD | Data / Command select line (Low = Cmd, High = Data) |
| **19** | SPI1_TXD | GPIO1_B2 | `spi0.0` MOSI | ROCK 4 → LCD | SPI Data Out (to CPLD shift registers) |
| **21** | SPI1_RXD | GPIO1_B1 | `spi0.0` MISO | LCD → ROCK 4 | SPI Data In (Touch / MISO) |
| **22** | GPIO4_D5 | GPIO 157 | `reset-gpios` (`ACTIVE_LOW`) | ROCK 4 → LCD | Hardware Reset line (Active LOW = 0V) |
| **23** | SPI1_CLK | GPIO1_B0 | SPI clock | ROCK 4 → LCD | The tested panel configuration uses 32 MHz SPI. The DTS assigns a 64 MHz clock source/parent; that is not the same as a 64 MHz SPI transfer rate. |
| **24** | SPI1_CS0 | GPIO1_A7 | `spi0.0` CS0 | ROCK 4 → LCD | Display Chip Select 0 |
| **26** | SPI1_CS1 | GPIO1_B3 | `spi0.1` CS1 | ROCK 4 → Touch | Touch controller (ADS7846) Chip Select 1 |

> **Caution:** Always power down the ROCK 4 SE before inserting or removing the display. Ensure Pin 1 of the display header matches Pin 1 of the ROCK 4 SE.

---

## 3. Root Causes Solved

If you attempt to run upstream kernel drivers (`ili9486.ko` + `drm_mipi_dbi.ko`) on a ROCK 4 SE, the screen stays solid white. Our modified drivers resolve all four underlying faults:

1. **Hardware Reset Inversion Fix:** Upstream `mipi_dbi_hw_reset()` clamped `reset-gpios` permanently to 0V (LOW). The display controller was frozen in reset. Our driver correctly pulses 0V for 20ms and releases to 3.3V (HIGH) with a 120ms settling delay.
2. **PL330 DMA Buffer Overflow Fix:** 307 KB unchunked frame transfers exceed the RK3399 PL330 DMA controller's 256-byte microcode buffer limit (`mcbufsz 289/256`), aborting all transfers (`Bad Desc`). Our driver splits transfers into safe **16 KB chunks**.
3. **Command 0x20 & Timings:** The Waveshare 3.5" (B) is a normally-white IPS panel. Without Command `0x20` (`MIPI_DCS_EXIT_INVERT_MODE`) and specific Power Control 3 (`0xC2`) / VCOM (`0xC5`) values, the panel remains an unpolarized white screen.
4. **CPLD 16-Bit Word Byte-Swapping:** A CPLD shift register sits between SPI and the ILI9486 bus. The driver enforces 16-bit word byte-swapping (`bpw = 16`) and an 18-bit to 16-bit format switch (`0x3A 0x66` → delay → `0x3A 0x55`) to eliminate psychedelic/jumbled colors.

---

## 4. Step-by-Step: Setup MIPI-DBI DRM Driver

### Step 1: Install Build Tools & Kernel Headers
Log into the ROCK 4 SE (replace `<ROCK4SE_IP>` with your own address) and install necessary packages:
```bash
sudo apt-get update
sudo apt-get install -y build-essential linux-headers-$(uname -r) \
                        device-tree-compiler python3 python3-gi \
                        python3-cairo gir1.2-gtk-3.0 xcompmgr
```

### Step 2: Build the Kernel Modules
In `/home/radxa/drm_build/` (or from our repository `drivers/`):
```bash
cd /home/radxa/drm_build

# Clean and compile
make clean
make -j2

# Install kernel modules to extra/
sudo mkdir -p /lib/modules/$(uname -r)/extra
sudo cp -f drm_mipi_dbi.ko ili9486.ko /lib/modules/$(uname -r)/extra/
sudo depmod -a
```

### Step 3: Compile the Device Tree Overlay (`35b1-mipidbi.dts`)
The overlay configures `spi1`, the reset/DC GPIOs, the `waveshare,rpi-lcd-35` compatible string, and a tested 32 MHz SPI transfer rate. The assigned SPI clock parent is 64 MHz.
```bash
# Compile DTS to DTBO
sudo dtc -@ -I dts -O dtb -o /boot/dtbo/35b1-mipidbi.dtbo /home/radxa/35b1-mipidbi.dts
```

### Step 4: Merge DTBO with the Rock 4 SE Base DTB
```bash
# Merge overlay onto base DTB to create ready-to-boot merged DTB
sudo fdtoverlay -i /usr/lib/linux-image-$(uname -r)/rockchip/rk3399-rock-4se.dtb \
                -o /boot/dtbo/rk3399-rock-4se-mipidbi.dtb \
                /boot/dtbo/35b1-mipidbi.dtbo
```

### Step 5: Configure Bootloader (`/boot/extlinux/extlinux.conf`)
Open `/boot/extlinux/extlinux.conf` and ensure `fdtoverlays` or `fdt` points to the MIPI-DBI DTB:
```
label l0
    menu label Debian GNU/Linux 12 (bookworm) 6.1.115-8-rk2501
    linux /boot/vmlinuz-6.1.115-8-rk2501
    initrd /boot/initrd.img-6.1.115-8-rk2501
    fdtdir /usr/lib/linux-image-6.1.115-8-rk2501/
    fdtoverlays /boot/dtbo/35b1-mipidbi.dtbo
    append root=UUID=<ROOT_UUID> video=HDMI-A-1:1280x720@60e console=ttyFIQ0,1500000n8 quiet splash loglevel=4 rw earlycon consoleblank=0 console=tty1 coherent_pool=2M
```

### Step 6: Configure Persistent Boot Modules & Options
Add modules to `/etc/modules` so they load automatically at boot:
```bash
sudo sh -c 'grep -q "drm_mipi_dbi" /etc/modules || echo "drm_mipi_dbi" >> /etc/modules'
sudo sh -c 'grep -q "ili9486" /etc/modules || echo "ili9486" >> /etc/modules'
```

Create `/etc/modprobe.d/ili9486.conf` with optimized default parameters:
```bash
sudo sh -c 'echo "options ili9486 diff_enable=1 diff_mode=1 diff_tile=128 merge_threshold=64 skip_nth=1 skip_even_rows=0" > /etc/modprobe.d/ili9486.conf'
```

### Step 7: Reboot and Verify
```bash
sudo reboot
```
After reboot, verify the driver nodes:
```bash
# Check loaded modules
lsmod | grep -E "ili9486|drm_mipi_dbi"

# Check DRM cards and framebuffer
ls -l /dev/dri/card* /dev/fb*

# Verify dmesg for successful panel registration
dmesg | grep -i ili9486
```
You should see a DRM card for the SPI display and, on systems with fbdev emulation enabled, a framebuffer node. Do not assume the card or framebuffer number is always `1`.

---

## 5. Step-by-Step: How to Use `driver_gui.py`

`driver_gui.py` uses only Python standard-library modules, but its optional privileged actions depend on system tools (`sudo`, `make`, `dtc`, `modprobe`, etc.). The public version binds to `127.0.0.1` by default; use an SSH tunnel for remote access or explicitly configure a trusted LAN bind address.

### 5.1 Starting and Managing the Web Service
The tool is registered as a systemd service (`driver-gui.service`) on the ROCK 4 SE:

```bash
# Check service status
sudo systemctl status driver-gui.service

# Restart service
sudo systemctl restart driver-gui.service

# Stop service
sudo systemctl stop driver-gui.service

# Run manually in foreground for testing
python3 /home/radxa/driver_gui.py
```

### 5.2 Accessing the Web Dashboard
From any browser on your network, open:
```
http://127.0.0.1:5000
```

### 5.3 Complete Feature Walkthrough

#### ⚡ 1. Differential Display Settings (Instant Performance Boost)
- **Differential Updates Toggle:** Turn ON to activate partial updates.
- **Diff Mode:**
  - `Mode 1: Scanline Span Merging`: Scans damaged rows, bridges small gaps, and merges adjacent spans. Local testing showed substantially higher update rates for small UI changes; the exact FPS depends on workload and should not be treated as a benchmark guarantee.
  - `Mode 2: Bounding Box (Dirty Rectangle)`: Sends a single rectangular bounding box around all changes. Ideal for video playback.
  - `Mode 3: Tile-Based Grid`: Divides screen into dirty tiles.
- **Span Gap Limit (`diff_tile`):** Max gap (in pixels) between changes merged into a single span (default: `128`).
- **Merge Threshold (`merge_threshold`):** Vertical tolerance in pixels for merging adjacent rows (default: `64`).
- **Apply Button:** Click **"Apply Diffing Settings"** to push parameters **live** into `/sys/module/ili9486/parameters/` and persist to `/etc/modprobe.d/ili9486.conf`.

#### 🎮 2. Frame Throttling & Scanline / Interlaced Modes
- **Skip Drawing Every Nth Pixel (`skip_nth`):**
  - `1`: Process every single pixel (normal, default).
  - `2`: Replaces every 2nd pixel with black in the transmitted buffer. This does **not** halve SPI transfer size; it is an experimental visual-degradation mode, not a bandwidth-saving mode.
- **Scanline & Interlaced Mode (`skip_even_rows`):**
  - `0 - Normal (All Rows)`: Standard complete display.
  - `1 - Skip Even Rows`: Sends only odd rows (1, 3, 5...), reducing the number of row transfers.
  - `2 - Skip Odd Rows`: Draws only even rows.
  - `3 - Interlaced Mode`: Alternates row parity between updates. This can reduce transfer work, but the visual result and effective motion rate depend on the application and update cadence.
  - `4 - Black Scanlines`: Leaves alternating rows black for an authentic retro CRT arcade look.

#### 🔄 3. Display Orientation & Rotation
- Choose between **0° (Portrait)**, **90° (Landscape)**, **180°**, or **270° (Inverted Landscape)**.
- Clicking **"Set Rotation"** updates `rotation = <...>` in the local DTS and recompiles the overlay. Reboot may be required before the new rotation is active.

#### 🎨 4. Inversion & Color Channel Ordering
- **Invert Colors Toggle:** Switches between Command `0x20` (`EXIT_INVERT_MODE`) and `0x21` (`ENTER_INVERT_MODE`). Useful if colors appear photographic-negative.
- **RGB / BGR Format:** The current tested snapshot keeps BGR enabled in MADCTL. The GUI control is intentionally disabled because runtime source rewriting for this option is not implemented in this snapshot.

#### ☀️ 5. Gamma & Software Brightness Calibration
- **Brightness (0–255):** Sends Command `0x51` directly to the display controller.
- **Gamma Pos / Neg:** Direct hex tuning for positive (`0xE0`) and negative (`0xE1`) gamma curves.

#### 📷 6. Live Framebuffer Capture & Preview
- The dashboard can preview a framebuffer when the expected `/dev/fb*` node and capture support are available; framebuffer numbering is system-dependent.
- Verify UI rendering without having to look at the physical screen.

#### 🔨 7. One-Click Hot-Recompile & Module Reload
- Modify driver initialization sequences or commands in the built-in code editor.
- Click **"Compile & Reload Driver"**: The server automatically runs `make`, stops display managers, unloads the modules, installs the newly compiled `.ko`, reloads them, and restarts the GUI without rebooting!

---

## 6. Differential Display Engine & Performance Tuning

### Direct CLI Tuning via Sysfs (No Browser Needed)
You can tune the driver directly from the command line:

```bash
# Enable differential updates
echo 1 | sudo tee /sys/module/ili9486/parameters/diff_enable

# Set Mode 1 (fbcp span merging)
echo 1 | sudo tee /sys/module/ili9486/parameters/diff_mode

# Set span bridge limit (128 px)
echo 128 | sudo tee /sys/module/ili9486/parameters/diff_tile

# Set vertical merge tolerance (64 px)
echo 64 | sudo tee /sys/module/ili9486/parameters/merge_threshold

# Set interlaced mode (3 = interlaced, 0 = normal)
echo 0 | sudo tee /sys/module/ili9486/parameters/skip_even_rows

# Set frame skip throttle (1 = all frames, 2 = half rate)
echo 1 | sudo tee /sys/module/ili9486/parameters/skip_nth
```

### Performance Comparison:
| Mode / Setting | Typical Transfer Size | UI Responsiveness | Use Case |
|:---|:---:|:---:|:---|
| **Stock Full-Frame DRM** | 307 KB / frame | Workload-dependent | Baseline comparison |
| **Mode 1 (span diff)** | Workload-dependent | Workload-dependent | Small UI damage / localized updates |
| **Mode 1 + Skip Even Rows** | Workload-dependent | Workload-dependent | Reduced row transfer work |
| **Mode 1 + Interlaced (3)** | Workload-dependent | Workload-dependent | Reduced row transfer work |
| **Mode 2 (Bounding Box)** | Workload-dependent | Workload-dependent | Localized changes / animation |

---

## 7. Software Brightness Control

The Waveshare 3.5" (B) lacks hardware PWM backlight dimming pins. We provide a **software dimmer overlay**:

### 7.1 Architecture:
- **Fullscreen Dimmer Overlay:** Transparent black X11 composite window with `cairo.Region()` empty input shape mask. The dimmer window is configured as click-through; behavior depends on the X11 compositor/window-manager environment.
- **Floating Touch Badge:** Compact corner badge (`☀️ 75%`). Tapping expands a touch slider with quick presets (`100%`, `75%`, `50%`, `25%`, `10%`). Auto-collapses after 5s.

### 7.2 Service Management:
```bash
sudo systemctl status brightness-overlay.service
sudo systemctl restart brightness-overlay.service
```

### 7.3 CLI Control (`brightness-cli`):
```bash
# Query current brightness
brightness-cli get

# Set brightness to 60%
brightness-cli set 60

# Step up or down by 10%
brightness-cli up 10
brightness-cli down 10

# Toggle touch panel on screen
brightness-cli toggle
```

---

## 8. Troubleshooting & Verification Commands

### 1. Screen stays solid white on boot:
- Check that the modified `drm_mipi_dbi.ko` is loaded:
  ```bash
  /sbin/modinfo ili9486 | grep filename
  ```
  Ensure it points to `/lib/modules/.../extra/ili9486.ko`.
- Check kernel log for PL330 DMA errors:
  ```bash
  dmesg | grep -i pl330
  ```
  If you see `Bad Desc`, the driver chunking fix is not active.

### 2. Colors are inverted (looks like a photo negative):
- In `http://127.0.0.1:5000`, use the inversion control in the GUI when running the local management tool, or edit the driver source and rebuild it.

### 3. Web Dashboard does not load:
- Check if `driver-gui.service` is active:
  ```bash
  sudo systemctl status driver-gui.service
  ```
- Verify port 5000 is listening:
  ```bash
  ss -tulpn | grep 5000
  ```

### 4. Restarting the Xorg desktop on the LCD:
```bash
# Restart nodm display manager
sudo systemctl restart nodm
```

## Public-repository safety notes

The public repository version of `driver_gui.py` intentionally does not contain the password from the original live machine. It uses non-interactive `sudo -n` for privileged operations and listens on `127.0.0.1` by default.

For remote access, use an SSH tunnel:

```bash
ssh -L 5000:127.0.0.1:5000 radxa@<ROCK4SE_IP>
```

Then open `http://127.0.0.1:5000` on the client machine.

If you choose to expose the GUI on a trusted LAN, set `DRIVER_GUI_HOST=0.0.0.0` in the service environment and add authentication/firewalling appropriate to your environment. Do not expose the administrative GUI directly to the public Internet.

The optional brightness overlay requires the GTK3/GDK/Cairo Python bindings installed by the package command near the beginning of this guide.
