// SPDX-License-Identifier: GPL-2.0+
/*
 * DRM driver for Ilitek ILI9486 panels (Waveshare 3.5" RPi LCD)
 *
 * Copyright 2020 Kamlesh Gurudasani <kamlesh.gurudasani@gmail.com>
 */

#include <linux/backlight.h>
#include <linux/delay.h>
#include <linux/gpio/consumer.h>
#include <linux/module.h>
#include <linux/property.h>
#include <linux/spi/spi.h>

#include <video/mipi_display.h>

#include <drm/drm_atomic_helper.h>
#include <drm/drm_drv.h>
#include <drm/drm_fb_helper.h>
#include <drm/drm_gem_atomic_helper.h>
#include <drm/drm_gem_dma_helper.h>
#include <drm/drm_managed.h>
#include <drm/drm_mipi_dbi.h>
#include <drm/drm_modeset_helper.h>

#define ILI9486_ITFCTR1         0xb0
#define ILI9486_PWCTRL1         0xc2
#define ILI9486_VMCTRL1         0xc5
#define ILI9486_PGAMCTRL        0xe0
#define ILI9486_NGAMCTRL        0xe1
#define ILI9486_DGAMCTRL        0xe2
#define ILI9486_MADCTL_BGR      BIT(3)
#define ILI9486_MADCTL_MV       BIT(5)
#define ILI9486_MADCTL_MX       BIT(6)
#define ILI9486_MADCTL_MY       BIT(7)

/*
 * The PiScreen/waveshare rpi-lcd-35 has a SPI to 16-bit parallel bus converter
 * in front of the display controller. This means that 8-bit values have to be
 * transferred as 16-bit.
 */
static int waveshare_command(struct mipi_dbi *mipi, u8 *cmd, u8 *par,
			     size_t num)
{
	struct spi_device *spi = mipi->spi;
	unsigned int bpw = 8;
	void *data = par;
	u32 speed_hz;
	int i, ret;
	__be16 *buf;

	if (*cmd != MIPI_DCS_WRITE_MEMORY_START)
		pr_info("ili9486_cmd: 0x%02X num=%zu\n", *cmd, num);

	buf = kmalloc(32 * sizeof(u16), GFP_KERNEL);
	if (!buf)
		return -ENOMEM;

	/*
	 * 16-bit command needs byte swapping before being transferred
	 * as 8-bit on the SPI bus.
	 */
	buf[0] = cpu_to_be16(*cmd);
	gpiod_set_value_cansleep(mipi->dc, 0);
	speed_hz = mipi_dbi_spi_cmd_max_speed(spi, 2);
	ret = mipi_dbi_spi_transfer(spi, speed_hz, 8, buf, 2);
	if (ret || !num)
		goto free;

	/* 8-bit configuration data, not 16-bit pixel data */
	if (num <= 32) {
		for (i = 0; i < num; i++)
			buf[i] = cpu_to_be16(par[i]);
		num *= 2;
		data = buf;
	}

	gpiod_set_value_cansleep(mipi->dc, 1);
	speed_hz = mipi_dbi_spi_cmd_max_speed(spi, num);
	{
		size_t max_chunk = 16384;
		const u8 *p = data;
		size_t left = num;

		while (left > 0) {
			size_t sz = min(left, max_chunk);
			ret = mipi_dbi_spi_transfer(spi, speed_hz, bpw, p, sz);
			if (ret)
				break;
			p += sz;
			left -= sz;
		}
	}
 free:
	kfree(buf);

	return ret;
}

static void waveshare_enable(struct drm_simple_display_pipe *pipe,
			     struct drm_crtc_state *crtc_state,
			     struct drm_plane_state *plane_state)
{
	struct mipi_dbi_dev *dbidev = drm_to_mipi_dbi_dev(pipe->crtc.dev);
	struct mipi_dbi *dbi = &dbidev->dbi;
	u8 addr_mode;
	int idx;

	if (!drm_dev_enter(pipe->crtc.dev, &idx))
		return;

	pr_info("ili9486: starting Waveshare 3.5 LCD init sequence\n");

	/* Proper Hardware Reset:
	 * For ACTIVE_LOW gpio:
	 * set(1) -> physical 0V (assert reset)
	 * set(0) -> physical 3.3V (release reset, RUNNING)
	 */
	if (dbi->reset) {
		pr_info("ili9486: asserting hardware reset (pin LOW 0V)\n");
		gpiod_set_value_cansleep(dbi->reset, 1);
		msleep(20);
		pr_info("ili9486: releasing hardware reset (pin HIGH 3.3V)\n");
		gpiod_set_value_cansleep(dbi->reset, 0);
		msleep(120);
	}

	/* 0x10000b0 0x00 - Interface Mode Control */
	mipi_dbi_command(dbi, 0xB0, 0x00);

	/* 0x1000011 - Sleep Out */
	mipi_dbi_command(dbi, MIPI_DCS_EXIT_SLEEP_MODE);

	/* 0x100003a 0x66 - Pixel format 18-bit */
	mipi_dbi_command(dbi, MIPI_DCS_SET_PIXEL_FORMAT, 0x66);

	/* 0x20000ff - delay 255ms */
	msleep(250);

	/* 0x1000020 - Display Inversion OFF (Command 0x20) */
	pr_info("ili9486: executing Command 0x20 (MIPI_DCS_EXIT_INVERT_MODE)\n");
	mipi_dbi_command(dbi, MIPI_DCS_EXIT_INVERT_MODE);

	/* 0x100003a 0x55 - Pixel format 16-bit RGB565 */
	mipi_dbi_command(dbi, MIPI_DCS_SET_PIXEL_FORMAT, 0x55);

	/* 0x10000c2 - Power Control 3 (9 parameters from working DTS) */
	mipi_dbi_command(dbi, 0xC2, 0x33, 0x0F, 0x0F, 0x0F, 0x0F, 0x0F, 0x0F, 0x0F, 0x0F);

	/* 0x10000b6 - Display Function Control */
	mipi_dbi_command(dbi, 0xB6, 0x01, 0x01, 0x3B);

	/* 0x10000c5 - VCOM Control */
	mipi_dbi_command(dbi, 0xC5, 0x00, 0x1E, 0x80);

	/* 0x10000b1 - Frame Rate Control */
	mipi_dbi_command(dbi, 0xB1, 0xB0);

	/* Gamma Control */
	mipi_dbi_command(dbi, 0xE0,
			 0x00, 0x13, 0x18, 0x04, 0x0F, 0x06, 0x3A, 0x56,
			 0x4D, 0x03, 0x0A, 0x06, 0x30, 0x3E, 0x0F);
	mipi_dbi_command(dbi, 0xE1,
			 0x00, 0x13, 0x18, 0x01, 0x11, 0x06, 0x38, 0x34,
			 0x4D, 0x06, 0x0D, 0x0B, 0x31, 0x37, 0x0F);

	/* 0x1000011 - Sleep Out */
	mipi_dbi_command(dbi, MIPI_DCS_EXIT_SLEEP_MODE);
	msleep(250);

	/* 0x1000029 - Display ON */
	mipi_dbi_command(dbi, MIPI_DCS_SET_DISPLAY_ON);
	msleep(50);

	/* Address Mode */
	switch (dbidev->rotation) {
	case 0:
		addr_mode = 0x40 | ILI9486_MADCTL_BGR; /* MX | BGR */
		break;
	case 90:
		addr_mode = 0x20 | ILI9486_MADCTL_BGR; /* MV | BGR */
		break;
	case 180:
		addr_mode = 0x80 | ILI9486_MADCTL_BGR; /* MY | BGR */
		break;
	case 270:
	default:
		addr_mode = 0x28; /* MV | BGR (matches 0x1000036 0x28 in 35b1.dts) */
		break;
	}
	mipi_dbi_command(dbi, MIPI_DCS_SET_ADDRESS_MODE, addr_mode);

	pr_info("ili9486: Waveshare 3.5 LCD init sequence completed successfully\n");

	mipi_dbi_enable_flush(dbidev, crtc_state, plane_state);
	drm_dev_exit(idx);
}

static const struct drm_simple_display_pipe_funcs waveshare_pipe_funcs = {
	.mode_valid = mipi_dbi_pipe_mode_valid,
	.enable = waveshare_enable,
	.disable = mipi_dbi_pipe_disable,
	.update = mipi_dbi_pipe_update,
};

/* Native physical panel resolution is 320x480. Rotation 270 makes it 480x320 landscape */
static const struct drm_display_mode waveshare_mode = {
	DRM_SIMPLE_MODE(320, 480, 49, 73),
};

DEFINE_DRM_GEM_DMA_FOPS(ili9486_fops);

static const struct drm_driver ili9486_driver = {
	.driver_features	= DRIVER_GEM | DRIVER_MODESET | DRIVER_ATOMIC,
	.fops			= &ili9486_fops,
	DRM_GEM_DMA_DRIVER_OPS_VMAP,
	.debugfs_init		= mipi_dbi_debugfs_init,
	.name			= "ili9486",
	.desc			= "Ilitek ILI9486",
	.date			= "20200118",
	.major			= 1,
	.minor			= 0,
};

static const struct of_device_id ili9486_of_match[] = {
	{ .compatible = "waveshare,rpi-lcd-35" },
	{ .compatible = "ozzmaker,piscreen" },
	{},
};
MODULE_DEVICE_TABLE(of, ili9486_of_match);

static const struct spi_device_id ili9486_id[] = {
	{ "ili9486", 0 },
	{ "rpi-lcd-35", 0 },
	{ "piscreen", 0 },
	{ }
};
MODULE_DEVICE_TABLE(spi, ili9486_id);

static int ili9486_probe(struct spi_device *spi)
{
	struct device *dev = &spi->dev;
	struct mipi_dbi_dev *dbidev;
	struct drm_device *drm;
	struct mipi_dbi *dbi;
	struct gpio_desc *dc;
	u32 rotation = 0;
	int ret;

	dbidev = devm_drm_dev_alloc(dev, &ili9486_driver,
				    struct mipi_dbi_dev, drm);
	if (IS_ERR(dbidev))
		return PTR_ERR(dbidev);

	dbi = &dbidev->dbi;
	drm = &dbidev->drm;

	/* Get reset GPIO initialized to INACTIVE (physical 3.3V HIGH) */
	dbi->reset = devm_gpiod_get(dev, "reset", GPIOD_OUT_LOW);
	if (IS_ERR(dbi->reset))
		return dev_err_probe(dev, PTR_ERR(dbi->reset), "Failed to get GPIO 'reset'\n");

	/* Initial hardware reset pulse at probe: assert (0V) then release (3.3V) */
	gpiod_set_value_cansleep(dbi->reset, 1);
	msleep(20);
	gpiod_set_value_cansleep(dbi->reset, 0);
	msleep(120);

	dc = devm_gpiod_get(dev, "dc", GPIOD_OUT_LOW);
	if (IS_ERR(dc))
		return dev_err_probe(dev, PTR_ERR(dc), "Failed to get GPIO 'dc'\n");

	dbidev->backlight = devm_of_find_backlight(dev);
	if (IS_ERR(dbidev->backlight))
		return PTR_ERR(dbidev->backlight);

	device_property_read_u32(dev, "rotation", &rotation);

	ret = mipi_dbi_spi_init(spi, dbi, dc);
	if (ret)
		return ret;

	dbi->command = waveshare_command;
	dbi->read_commands = NULL;

	ret = mipi_dbi_dev_init(dbidev, &waveshare_pipe_funcs,
				&waveshare_mode, rotation);
	if (ret)
		return ret;

	drm_mode_config_reset(drm);

	ret = drm_dev_register(drm, 0);
	if (ret)
		return ret;

	spi_set_drvdata(spi, drm);

	drm_fbdev_generic_setup(drm, 0);

	return 0;
}

static void ili9486_remove(struct spi_device *spi)
{
	struct drm_device *drm = spi_get_drvdata(spi);

	drm_dev_unplug(drm);
	drm_atomic_helper_shutdown(drm);
}

static void ili9486_shutdown(struct spi_device *spi)
{
	drm_atomic_helper_shutdown(spi_get_drvdata(spi));
}

static struct spi_driver ili9486_spi_driver = {
	.driver = {
		.name = "ili9486",
		.of_match_table = ili9486_of_match,
	},
	.id_table = ili9486_id,
	.probe = ili9486_probe,
	.remove = ili9486_remove,
	.shutdown = ili9486_shutdown,
};
module_spi_driver(ili9486_spi_driver);

MODULE_DESCRIPTION("Ilitek ILI9486 DRM driver (Waveshare 3.5 LCD)");
MODULE_AUTHOR("Kamlesh Gurudasani <kamlesh.gurudasani@gmail.com>");
MODULE_LICENSE("GPL");
