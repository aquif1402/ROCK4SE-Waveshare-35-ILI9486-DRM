with open("/home/radxa/drm_build/drm_mipi_dbi.c", "r") as f:
    code = f.read()

# 1. Place declarations right before mipi_dbi_fb_dirty
old_marker = '''static void mipi_dbi_fb_dirty(struct drm_framebuffer *fb, struct drm_rect *rect)'''

new_decl = '''static DEFINE_MUTEX(mipi_dbi_diff_lock);
static unsigned int mipi_dbi_diff_updates;
static unsigned int mipi_dbi_skip_even_rows;
module_param_named(skip_even_rows, mipi_dbi_skip_even_rows, uint, 0644);
MODULE_PARM_DESC(skip_even_rows, "Skip drawing even rows (0=all rows, 1=skip even, 2=skip odd, 3=interlaced, 4=black scanlines)");

void mipi_dbi_skip_even_rows_fn(bool enable)
{
	mutex_lock(&mipi_dbi_diff_lock);
	mipi_dbi_skip_even_rows = enable ? 1 : 0;
	mutex_unlock(&mipi_dbi_diff_lock);
}
EXPORT_SYMBOL(mipi_dbi_skip_even_rows_fn);

void mipi_dbi_set_skip_even_rows(unsigned int mode)
{
	mutex_lock(&mipi_dbi_diff_lock);
	mipi_dbi_skip_even_rows = mode;
	mutex_unlock(&mipi_dbi_diff_lock);
}
EXPORT_SYMBOL(mipi_dbi_set_skip_even_rows);

unsigned int mipi_dbi_get_skip_even_rows(void)
{
	return mipi_dbi_skip_even_rows;
}
EXPORT_SYMBOL(mipi_dbi_get_skip_even_rows);

static inline bool mipi_dbi_should_skip_row(unsigned int y, unsigned int mode, unsigned int frame)
{
	if (!mode)
		return false;
	if (mode == 1) /* Skip even rows: only draw odd rows (1, 3, 5...) */
		return (y % 2 == 0);
	if (mode == 2) /* Skip odd rows: only draw even rows (0, 2, 4...) */
		return (y % 2 != 0);
	if (mode == 3) /* Interlaced: alternate parity each frame */
		return ((y % 2) == (frame % 2));
	return false;
}

static void mipi_dbi_fb_dirty(struct drm_framebuffer *fb, struct drm_rect *rect)'''

assert old_marker in code, "old_marker not found"
code = code.replace(old_marker, new_decl, 1)

# 2. Patch mipi_dbi_fb_dirty window & command call
old_dirty = '''	mipi_dbi_set_window_address(dbidev, rect->x1, rect->x2 - 1, rect->y1,
				    rect->y2 - 1);

	ret = mipi_dbi_command_buf(dbi, MIPI_DCS_WRITE_MEMORY_START, tr,
				   width * height * 2);'''

new_dirty = '''	if (mipi_dbi_skip_even_rows != 0 && mipi_dbi_skip_even_rows != 4) {
		unsigned int r;
		for (r = 0; r < height; r++) {
			unsigned int y = rect->y1 + r;
			if (mipi_dbi_should_skip_row(y, mipi_dbi_skip_even_rows, mipi_dbi_diff_updates))
				continue;
			const u16 *src_r = ((const u16 *)tr) + r * width;
			mipi_dbi_set_window_address(dbidev, rect->x1, rect->x2 - 1, y, y);
			mipi_dbi_command_buf(dbi, MIPI_DCS_WRITE_MEMORY_START, (u8 *)src_r, width * 2);
		}
		ret = 0;
	} else {
		mipi_dbi_set_window_address(dbidev, rect->x1, rect->x2 - 1, rect->y1,
					    rect->y2 - 1);
		ret = mipi_dbi_command_buf(dbi, MIPI_DCS_WRITE_MEMORY_START, (u8 *)tr,
					   width * height * 2);
	}'''

assert old_dirty in code, "old_dirty not found"
code = code.replace(old_dirty, new_dirty, 1)

# 3. Clean up the duplicate lock/diff_updates declaration below
old_lock_decl = '''static DEFINE_MUTEX(mipi_dbi_diff_lock);
static u8 *mipi_dbi_diff_shadow;
static size_t mipi_dbi_diff_shadow_size;
static u8 *mipi_dbi_diff_staging;
static size_t mipi_dbi_diff_staging_size;
static unsigned int mipi_dbi_diff_updates;'''

new_lock_decl = '''static u8 *mipi_dbi_diff_shadow;
static size_t mipi_dbi_diff_shadow_size;
static u8 *mipi_dbi_diff_staging;
static size_t mipi_dbi_diff_staging_size;'''

assert old_lock_decl in code, "old_lock_decl not found"
code = code.replace(old_lock_decl, new_lock_decl, 1)

# 4. Patch Mode 4 black scanlines right after mipi_dbi_buf_copy
old_copy = '''	/* Convert damage region from FB into dbidev->tx_buf in a single pass */
	ret = mipi_dbi_buf_copy(dbidev->tx_buf, fb, &damage, dbidev->dbi.swap_bytes);
	if (ret)
		goto out_exit;'''

new_copy = '''	/* Convert damage region from FB into dbidev->tx_buf in a single pass */
	ret = mipi_dbi_buf_copy(dbidev->tx_buf, fb, &damage, dbidev->dbi.swap_bytes);
	if (ret)
		goto out_exit;

	/* Mode 4: Software Black scanlines filter */
	if (mipi_dbi_skip_even_rows == 4) {
		unsigned int r;
		for (r = 0; r < d_height; r++) {
			unsigned int y = damage.y1 + r;
			if (y % 2 == 0) {
				u16 *row_ptr = ((u16 *)dbidev->tx_buf) + r * d_width;
				memset(row_ptr, 0, d_width * sizeof(u16));
			}
		}
	}'''

assert old_copy in code, "old_copy not found"
code = code.replace(old_copy, new_copy, 1)

# 5. Patch Mode 0
old_mode0 = '''	/*
	 * MODE 0: Disabled - send entire damage rect directly
	 */
	if (diff_mode == 0) {
		mipi_dbi_set_window_address(dbidev, damage.x1, damage.x2 - 1,
					    damage.y1, damage.y2 - 1);
		mipi_dbi_command_buf(&dbidev->dbi, MIPI_DCS_WRITE_MEMORY_START,
				    (u8 *)dbidev->tx_buf, d_width * d_height * 2);
		goto out_exit;
	}'''

new_mode0 = '''	/*
	 * MODE 0: Disabled - send entire damage rect directly
	 */
	if (diff_mode == 0) {
		if (mipi_dbi_skip_even_rows == 0 || mipi_dbi_skip_even_rows == 4) {
			mipi_dbi_set_window_address(dbidev, damage.x1, damage.x2 - 1,
						    damage.y1, damage.y2 - 1);
			mipi_dbi_command_buf(&dbidev->dbi, MIPI_DCS_WRITE_MEMORY_START,
					    (u8 *)dbidev->tx_buf, d_width * d_height * 2);
		} else {
			unsigned int r;
			for (r = 0; r < d_height; r++) {
				unsigned int y = damage.y1 + r;
				if (mipi_dbi_should_skip_row(y, mipi_dbi_skip_even_rows, mipi_dbi_diff_updates))
					continue;
				const u16 *src_r = ((const u16 *)dbidev->tx_buf) + r * d_width;
				mipi_dbi_set_window_address(dbidev, damage.x1, damage.x2 - 1, y, y);
				mipi_dbi_command_buf(&dbidev->dbi, MIPI_DCS_WRITE_MEMORY_START,
						    (u8 *)src_r, d_width * 2);
			}
		}
		goto out_exit;
	}'''

assert old_mode0 in code, "old_mode0 not found"
code = code.replace(old_mode0, new_mode0, 1)

# 6. Patch Mode 2 scanning & sending
old_mode2_scan = '''		for (r = 0; r < d_height; r++) {
			unsigned int y = damage.y1 + r;
			const u16 *tx_row = ((const u16 *)dbidev->tx_buf) + r * d_width;
			const u16 *shd_row = ((const u16 *)mipi_dbi_diff_shadow) + y * fb->width + damage.x1;

			if (!memcmp(tx_row, shd_row, d_width * sizeof(u16)))
				continue;'''

new_mode2_scan = '''		for (r = 0; r < d_height; r++) {
			unsigned int y = damage.y1 + r;
			const u16 *tx_row = ((const u16 *)dbidev->tx_buf) + r * d_width;
			const u16 *shd_row = ((const u16 *)mipi_dbi_diff_shadow) + y * fb->width + damage.x1;

			if (mipi_dbi_should_skip_row(y, mipi_dbi_skip_even_rows, mipi_dbi_diff_updates))
				continue;

			if (!memcmp(tx_row, shd_row, d_width * sizeof(u16)))
				continue;'''

assert old_mode2_scan in code, "old_mode2_scan not found"
code = code.replace(old_mode2_scan, new_mode2_scan, 1)

old_mode2_send = '''			for (row = 0; row < bh; row++) {
				unsigned int sy = (bbox_min_y + row) - damage.y1;
				unsigned int sx = bbox_min_x - damage.x1;
				const u16 *src_r = ((const u16 *)dbidev->tx_buf) + sy * d_width + sx;
				u16 *dst_r = ((u16 *)mipi_dbi_diff_staging) + row * bw;
				u16 *shd_r = ((u16 *)mipi_dbi_diff_shadow) + (bbox_min_y + row) * fb->width + bbox_min_x;

				memcpy(dst_r, src_r, bw * sizeof(u16));
				memcpy(shd_r, src_r, bw * sizeof(u16));
			}

			mipi_dbi_set_window_address(dbidev, bbox_min_x, bbox_max_x - 1,
						    bbox_min_y, bbox_max_y - 1);
			mipi_dbi_command_buf(&dbidev->dbi, MIPI_DCS_WRITE_MEMORY_START,
					    mipi_dbi_diff_staging, bw * bh * 2);
		}
		goto out_exit;'''

new_mode2_send = '''			if (mipi_dbi_skip_even_rows != 0 && mipi_dbi_skip_even_rows != 4) {
				for (row = 0; row < bh; row++) {
					unsigned int cur_y = bbox_min_y + row;
					if (mipi_dbi_should_skip_row(cur_y, mipi_dbi_skip_even_rows, mipi_dbi_diff_updates))
						continue;

					unsigned int sy = cur_y - damage.y1;
					unsigned int sx = bbox_min_x - damage.x1;
					const u16 *src_r = ((const u16 *)dbidev->tx_buf) + sy * d_width + sx;
					u16 *dst_r = (u16 *)mipi_dbi_diff_staging;
					u16 *shd_r = ((u16 *)mipi_dbi_diff_shadow) + cur_y * fb->width + bbox_min_x;

					memcpy(dst_r, src_r, bw * sizeof(u16));
					memcpy(shd_r, src_r, bw * sizeof(u16));

					mipi_dbi_set_window_address(dbidev, bbox_min_x, bbox_max_x - 1, cur_y, cur_y);
					mipi_dbi_command_buf(&dbidev->dbi, MIPI_DCS_WRITE_MEMORY_START, (u8 *)dst_r, bw * 2);
				}
			} else {
				for (row = 0; row < bh; row++) {
					unsigned int sy = (bbox_min_y + row) - damage.y1;
					unsigned int sx = bbox_min_x - damage.x1;
					const u16 *src_r = ((const u16 *)dbidev->tx_buf) + sy * d_width + sx;
					u16 *dst_r = ((u16 *)mipi_dbi_diff_staging) + row * bw;
					u16 *shd_r = ((u16 *)mipi_dbi_diff_shadow) + (bbox_min_y + row) * fb->width + bbox_min_x;

					memcpy(dst_r, src_r, bw * sizeof(u16));
					memcpy(shd_r, src_r, bw * sizeof(u16));
				}

				mipi_dbi_set_window_address(dbidev, bbox_min_x, bbox_max_x - 1,
							    bbox_min_y, bbox_max_y - 1);
				mipi_dbi_command_buf(&dbidev->dbi, MIPI_DCS_WRITE_MEMORY_START,
						    (u8 *)mipi_dbi_diff_staging, bw * bh * 2);
			}
		}
		goto out_exit;'''

assert old_mode2_send in code, "old_mode2_send not found"
code = code.replace(old_mode2_send, new_mode2_send, 1)

# 7. Patch Mode 1 scanning
old_mode1_scan = '''		for (r = 0; r < d_height; r++) {
			unsigned int y = damage.y1 + r;
			const u16 *tx_row = ((const u16 *)dbidev->tx_buf) + r * d_width;
			const u16 *shd_row = ((const u16 *)mipi_dbi_diff_shadow) + y * fb->width + damage.x1;

			if (!memcmp(tx_row, shd_row, d_width * sizeof(u16)))
				continue;'''

new_mode1_scan = '''		for (r = 0; r < d_height; r++) {
			unsigned int y = damage.y1 + r;
			const u16 *tx_row = ((const u16 *)dbidev->tx_buf) + r * d_width;
			const u16 *shd_row = ((const u16 *)mipi_dbi_diff_shadow) + y * fb->width + damage.x1;

			if (mipi_dbi_should_skip_row(y, mipi_dbi_skip_even_rows, mipi_dbi_diff_updates))
				continue;

			if (!memcmp(tx_row, shd_row, d_width * sizeof(u16)))
				continue;'''

assert old_mode1_scan in code, "old_mode1_scan not found"
code = code.replace(old_mode1_scan, new_mode1_scan, 1)

# 8. Patch Mode 1 send_bbox fallback
old_mode1_bbox = '''send_bbox:
		{
			unsigned int bw = bbox_max_x - bbox_min_x;
			unsigned int bh = bbox_max_y - bbox_min_y;
			unsigned int row;

			for (row = 0; row < bh; row++) {
				unsigned int sy = (bbox_min_y + row) - damage.y1;
				unsigned int sx = bbox_min_x - damage.x1;
				const u16 *src_r = ((const u16 *)dbidev->tx_buf) + sy * d_width + sx;
				u16 *dst_r = ((u16 *)mipi_dbi_diff_staging) + row * bw;
				u16 *shd_r = ((u16 *)mipi_dbi_diff_shadow) + (bbox_min_y + row) * fb->width + bbox_min_x;

				memcpy(dst_r, src_r, bw * sizeof(u16));
				memcpy(shd_r, src_r, bw * sizeof(u16));
			}

			mipi_dbi_set_window_address(dbidev, bbox_min_x, bbox_max_x - 1,
						    bbox_min_y, bbox_max_y - 1);
			mipi_dbi_command_buf(&dbidev->dbi, MIPI_DCS_WRITE_MEMORY_START,
					    mipi_dbi_diff_staging, bw * bh * 2);
		}'''

new_mode1_bbox = '''send_bbox:
		{
			unsigned int bw = bbox_max_x - bbox_min_x;
			unsigned int bh = bbox_max_y - bbox_min_y;
			unsigned int row;

			if (mipi_dbi_skip_even_rows != 0 && mipi_dbi_skip_even_rows != 4) {
				for (row = 0; row < bh; row++) {
					unsigned int cur_y = bbox_min_y + row;
					if (mipi_dbi_should_skip_row(cur_y, mipi_dbi_skip_even_rows, mipi_dbi_diff_updates))
						continue;

					unsigned int sy = cur_y - damage.y1;
					unsigned int sx = bbox_min_x - damage.x1;
					const u16 *src_r = ((const u16 *)dbidev->tx_buf) + sy * d_width + sx;
					u16 *dst_r = (u16 *)mipi_dbi_diff_staging;
					u16 *shd_r = ((u16 *)mipi_dbi_diff_shadow) + cur_y * fb->width + bbox_min_x;

					memcpy(dst_r, src_r, bw * sizeof(u16));
					memcpy(shd_r, src_r, bw * sizeof(u16));

					mipi_dbi_set_window_address(dbidev, bbox_min_x, bbox_max_x - 1, cur_y, cur_y);
					mipi_dbi_command_buf(&dbidev->dbi, MIPI_DCS_WRITE_MEMORY_START, (u8 *)dst_r, bw * 2);
				}
			} else {
				for (row = 0; row < bh; row++) {
					unsigned int sy = (bbox_min_y + row) - damage.y1;
					unsigned int sx = bbox_min_x - damage.x1;
					const u16 *src_r = ((const u16 *)dbidev->tx_buf) + sy * d_width + sx;
					u16 *dst_r = ((u16 *)mipi_dbi_diff_staging) + row * bw;
					u16 *shd_r = ((u16 *)mipi_dbi_diff_shadow) + (bbox_min_y + row) * fb->width + bbox_min_x;

					memcpy(dst_r, src_r, bw * sizeof(u16));
					memcpy(shd_r, src_r, bw * sizeof(u16));
				}

				mipi_dbi_set_window_address(dbidev, bbox_min_x, bbox_max_x - 1,
							    bbox_min_y, bbox_max_y - 1);
				mipi_dbi_command_buf(&dbidev->dbi, MIPI_DCS_WRITE_MEMORY_START,
						    (u8 *)mipi_dbi_diff_staging, bw * bh * 2);
			}
		}'''

assert old_mode1_bbox in code, "old_mode1_bbox not found"
code = code.replace(old_mode1_bbox, new_mode1_bbox, 1)

with open("/home/radxa/drm_build/drm_mipi_dbi.c", "w") as f:
    f.write(code)

print("drm_mipi_dbi.c patched successfully")
