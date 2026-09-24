# Upstream / Original Source

The driver code in this repository is derived from the Linux kernel's DRM/MIPI-DBI
and TinyDRM ILI9486 implementation.

When publishing this repository, the recommended upstream reference is the Linux kernel
tree matching the kernel version used to build the included modules.

The most important source files are:

- `drivers/gpu/drm/tiny/ili9486.c`
- `drivers/gpu/drm/drm_mipi_dbi.c`

This repository contains a hardware-specific working modification rather than an
independent implementation of the ILI9486 protocol.

Because the exact upstream revision should match the kernel source used for the
modules, users should compare these files against the corresponding source in their
kernel tree when porting the driver to another kernel.
