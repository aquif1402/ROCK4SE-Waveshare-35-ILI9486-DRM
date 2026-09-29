#!/usr/bin/env python3
"""
Rock 4 SE Opacity-Adjustable Black Overlay for Software Brightness Control
Antigravity SBC Utility - Radxa ROCK 4 SE

Clean Two-Window Architecture:
1. Fullscreen Dimmer Overlay (Window 1):
   - Pure black window with _NET_WM_WINDOW_OPACITY (set_opacity).
   - Empty input shape mask (input_shape_combine_region(cairo.Region())):
     NEVER intercepts mouse clicks or touches. 100% click-through across the whole screen.
2. Floating Touch Control Widget (Window 2):
   - Standalone floating popup positioned cleanly above the Matchbox panel.
   - Collapsed: Small floating badge (☀️ XX%) in the bottom-right corner.
   - Expanded: Touch slider, +/- 5% buttons, quick presets (100%, 75%, 50%, 25%, 10%).
   - Auto-collapses after 5s of inactivity.
3. Socket IPC Server & Systemd Service:
   - CLI control via brightness-cli.
   - Remote web control via port 5000 (driver_gui.py).
   - Starts on boot with persistent brightness setting.
"""

import os
import sys
import json
import time
import socket
import threading
import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gtk, Gdk, GLib
import cairo

# Configuration
CONFIG_PATH = os.path.expanduser("~/.config/brightness-overlay.json")
SOCKET_PATH = "/tmp/brightness_overlay.sock"
DEFAULT_BRIGHTNESS = 75
MIN_BRIGHTNESS = 10
MAX_BRIGHTNESS = 100
MAX_OVERLAY_OPACITY = 0.88
AUTO_COLLAPSE_SEC = 5

CSS_STYLE = b"""
#dimmer-window {
    background-color: #000000;
}
#ctrl-window {
    background-color: #1e293b;
    border: 2px solid #475569;
    border-radius: 8px;
    padding: 3px;
}
#badge-btn {
    background: #0f172a;
    color: #00e676;
    border: 1px solid #334155;
    border-radius: 6px;
    font-weight: bold;
    font-size: 11px;
    padding: 3px 6px;
}
#badge-btn:hover, #badge-btn:active {
    background: #1e293b;
    border-color: #00e676;
}
.ctrl-btn {
    background: #334155;
    color: #ffffff;
    border: 1px solid #475569;
    border-radius: 4px;
    font-weight: bold;
    font-size: 11px;
    padding: 3px 8px;
}
.ctrl-btn:hover, .ctrl-btn:active {
    background: #475569;
}
.preset-btn {
    background: #1e293b;
    color: #e2e8f0;
    border: 1px solid #334155;
    border-radius: 4px;
    font-size: 10px;
    padding: 3px 4px;
}
.preset-btn:hover, .preset-btn:active {
    background: #38bdf8;
    color: #0f172a;
    font-weight: bold;
}
#title-label {
    color: #94a3b8;
    font-size: 10px;
    font-weight: bold;
}
#val-label {
    color: #00e676;
    font-size: 13px;
    font-weight: bold;
}
scale trough {
    background-color: #0f172a;
    border: 1px solid #334155;
    border-radius: 4px;
    min-height: 12px;
}
scale highlight {
    background-color: #00e676;
    border-radius: 4px;
}
"""

class BrightnessOverlaySystem:
    def __init__(self):
        self.brightness = self.load_config()
        self.opacity = self.calc_opacity(self.brightness)
        self.expanded = False
        self.ui_visible = True
        self.last_activity = time.time()
        self.updating_slider = False

        # Load CSS style
        screen = Gdk.Screen.get_default()
        css_provider = Gtk.CssProvider()
        css_provider.load_from_data(CSS_STYLE)
        Gtk.StyleContext.add_provider_for_screen(
            screen, css_provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )

        # Detect screen geometry
        display = Gdk.Display.get_default()
        monitor = display.get_primary_monitor() or (display.get_monitor(0) if display.get_n_monitors() > 0 else None)
        if monitor:
            geom = monitor.get_geometry()
            self.screen_w = geom.width
            self.screen_h = geom.height
        else:
            self.screen_w = 480
            self.screen_h = 320

        # Matchbox panel height is typically 20-22px at bottom.
        self.panel_offset_bottom = 24

        # Geometry for Collapsed Badge (Window 2)
        self.badge_w = 78
        self.badge_h = 32
        self.badge_x = self.screen_w - self.badge_w - 6
        self.badge_y = self.screen_h - self.badge_h - self.panel_offset_bottom

        # Geometry for Expanded Panel (Window 2)
        self.panel_w = min(414, self.screen_w - 16)
        self.panel_h = 104
        self.panel_x = (self.screen_w - self.panel_w) // 2
        self.panel_y = self.screen_h - self.panel_h - self.panel_offset_bottom

        # ==========================================
        # 1. Fullscreen Dimmer Overlay (Window 1)
        # ==========================================
        self.overlay_win = Gtk.Window(type=Gtk.WindowType.POPUP)
        self.overlay_win.set_title("BrightnessDimmerOverlay")
        self.overlay_win.set_name("dimmer-window")
        self.overlay_win.set_default_size(self.screen_w, self.screen_h)
        self.overlay_win.move(0, 0)
        self.overlay_win.set_keep_above(True)
        self.overlay_win.set_opacity(self.opacity)
        self.overlay_win.show_all()

        # Set empty input mask: 100% click-through everywhere on the overlay!
        self.overlay_win.input_shape_combine_region(cairo.Region())

        # ==========================================
        # 2. Floating Touch Control Widget (Window 2)
        # ==========================================
        self.ctrl_win = Gtk.Window(type=Gtk.WindowType.POPUP)
        self.ctrl_win.set_title("BrightnessControlWidget")
        self.ctrl_win.set_name("ctrl-window")
        self.ctrl_win.set_keep_above(True)

        # Build Badge widget
        self.badge_btn = Gtk.Button(label=f"☀️ {self.brightness}%")
        self.badge_btn.set_name("badge-btn")
        self.badge_btn.set_size_request(self.badge_w, self.badge_h)
        self.badge_btn.connect("clicked", self.on_badge_clicked)

        # Build Expanded Panel widget
        self.panel_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        self.panel_box.set_size_request(self.panel_w, self.panel_h)
        self.build_panel_contents()

        # Start collapsed with badge
        self.ctrl_win.add(self.badge_btn)
        self.ctrl_win.resize(1, 1)
        self.ctrl_win.move(self.badge_x, self.badge_y)
        self.ctrl_win.show_all()

        # Periodic check to ensure windows stay on top of desktop
        GLib.timeout_add_seconds(2, self.ensure_stacked_on_top)

        # Inactivity auto-collapse timer
        GLib.timeout_add_seconds(1, self.check_inactivity)

        # Start IPC socket server
        self.start_socket_server()

    def build_panel_contents(self):
        # Row 1: Header (Title, Value %, Close button)
        row1 = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)

        lbl_title = Gtk.Label(label="Brightness Control")
        lbl_title.set_name("title-label")
        row1.pack_start(lbl_title, False, False, 0)

        self.val_label = Gtk.Label(label=f"{self.brightness}%")
        self.val_label.set_name("val-label")
        row1.pack_start(self.val_label, False, False, 8)

        btn_close = Gtk.Button(label="✕")
        btn_close.get_style_context().add_class("ctrl-btn")
        btn_close.connect("clicked", lambda b: self.collapse_panel())
        row1.pack_end(btn_close, False, False, 0)

        self.panel_box.pack_start(row1, False, False, 0)

        # Row 2: Minus, Slider, Plus
        row2 = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)

        btn_minus = Gtk.Button(label="−5%")
        btn_minus.get_style_context().add_class("ctrl-btn")
        btn_minus.connect("clicked", lambda b: self.step_brightness(-5))
        row2.pack_start(btn_minus, False, False, 0)

        self.slider = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, MIN_BRIGHTNESS, MAX_BRIGHTNESS, 1)
        self.slider.set_draw_value(False)
        self.slider.set_value(self.brightness)
        self.slider.connect("value-changed", self.on_slider_changed)
        row2.pack_start(self.slider, True, True, 0)

        btn_plus = Gtk.Button(label="+5%")
        btn_plus.get_style_context().add_class("ctrl-btn")
        btn_plus.connect("clicked", lambda b: self.step_brightness(5))
        row2.pack_start(btn_plus, False, False, 0)

        self.panel_box.pack_start(row2, False, False, 0)

        # Row 3: Presets
        row3 = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        presets = [("Max 100%", 100), ("75%", 75), ("Half 50%", 50), ("25%", 25), ("Min 10%", 10)]
        for label, val in presets:
            p_btn = Gtk.Button(label=label)
            p_btn.get_style_context().add_class("preset-btn")
            p_btn.connect("clicked", lambda b, v=val: self.set_brightness(v))
            row3.pack_start(p_btn, True, True, 0)

        self.panel_box.pack_start(row3, False, False, 0)

    def load_config(self):
        try:
            if os.path.exists(CONFIG_PATH):
                with open(CONFIG_PATH, "r") as f:
                    data = json.load(f)
                    val = int(data.get("brightness", DEFAULT_BRIGHTNESS))
                    return max(MIN_BRIGHTNESS, min(MAX_BRIGHTNESS, val))
        except Exception as e:
            print(f"[Overlay] Config load error: {e}", file=sys.stderr)
        return DEFAULT_BRIGHTNESS

    def save_config(self):
        try:
            os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
            with open(CONFIG_PATH, "w") as f:
                json.dump({"brightness": self.brightness, "opacity": round(self.opacity, 3)}, f, indent=2)
        except Exception as e:
            print(f"[Overlay] Config save error: {e}", file=sys.stderr)

    def calc_opacity(self, brightness):
        b = max(MIN_BRIGHTNESS, min(MAX_BRIGHTNESS, brightness))
        ratio = (100 - b) / (100 - MIN_BRIGHTNESS)
        return ratio * MAX_OVERLAY_OPACITY

    def set_brightness(self, val, save=True):
        self.last_activity = time.time()
        self.brightness = max(MIN_BRIGHTNESS, min(MAX_BRIGHTNESS, int(val)))
        self.opacity = self.calc_opacity(self.brightness)

        # Update labels & slider
        self.badge_btn.set_label(f"☀️ {self.brightness}%")
        self.val_label.set_label(f"{self.brightness}%")
        if not self.updating_slider and hasattr(self, "slider"):
            self.updating_slider = True
            self.slider.set_value(self.brightness)
            self.updating_slider = False

        if save:
            self.save_config()

        # Update overlay opacity (sets _NET_WM_WINDOW_OPACITY)
        self.overlay_win.set_opacity(self.opacity)
        # Re-assert empty input shape
        self.overlay_win.input_shape_combine_region(cairo.Region())

    def step_brightness(self, delta):
        self.set_brightness(self.brightness + delta)

    def on_slider_changed(self, scale):
        if not self.updating_slider:
            self.last_activity = time.time()
            val = int(scale.get_value())
            self.set_brightness(val)

    def on_badge_clicked(self, btn):
        self.expand_panel()

    def expand_panel(self):
        self.expanded = True
        self.ui_visible = True
        self.last_activity = time.time()
        
        # Swap child to expanded panel
        if self.badge_btn in self.ctrl_win.get_children():
            self.ctrl_win.remove(self.badge_btn)
        if self.panel_box not in self.ctrl_win.get_children():
            self.ctrl_win.add(self.panel_box)
            
        self.ctrl_win.move(self.panel_x, self.panel_y)
        self.ctrl_win.show_all()
        self.ensure_stacked_on_top()

    def collapse_panel(self):
        self.expanded = False
        self.last_activity = time.time()
        
        # Swap child to badge button
        if self.panel_box in self.ctrl_win.get_children():
            self.ctrl_win.remove(self.panel_box)
        if self.badge_btn not in self.ctrl_win.get_children():
            self.ctrl_win.add(self.badge_btn)
            
        self.ctrl_win.resize(1, 1)
        self.ctrl_win.move(self.badge_x, self.badge_y)
        self.ctrl_win.show_all()
        self.ensure_stacked_on_top()

    def hide_ui(self):
        self.ui_visible = False
        self.expanded = False
        self.ctrl_win.hide()

    def show_ui(self):
        self.ui_visible = True
        self.collapse_panel()
        self.ctrl_win.show_all()
        self.ensure_stacked_on_top()

    def toggle_ui(self):
        if not self.ui_visible:
            self.show_ui()
        elif self.expanded:
            self.collapse_panel()
        else:
            self.expand_panel()

    def check_inactivity(self):
        if self.expanded and (time.time() - self.last_activity > AUTO_COLLAPSE_SEC):
            self.collapse_panel()
        return True

    def ensure_stacked_on_top(self):
        try:
            if self.overlay_win and self.overlay_win.get_window():
                self.overlay_win.get_window().raise_()
            if self.ui_visible and self.ctrl_win and self.ctrl_win.get_window():
                self.ctrl_win.get_window().raise_()
        except Exception:
            pass
        return True

    # --- Socket IPC Server ---
    def start_socket_server(self):
        if os.path.exists(SOCKET_PATH):
            try:
                os.unlink(SOCKET_PATH)
            except OSError:
                pass

        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.bind(SOCKET_PATH)
        os.chmod(SOCKET_PATH, 0o666)
        self.sock.listen(5)

        t = threading.Thread(target=self.socket_worker, daemon=True)
        t.start()

    def socket_worker(self):
        while True:
            try:
                conn, _ = self.sock.accept()
                data = conn.recv(1024).decode("utf-8").strip()
                if not data:
                    conn.close()
                    continue

                parts = data.split()
                cmd = parts[0].upper()
                resp = {}

                if cmd == "GET":
                    resp = {
                        "status": "ok",
                        "brightness": self.brightness,
                        "opacity": round(self.opacity, 3),
                        "expanded": self.expanded,
                        "ui_visible": self.ui_visible
                    }
                elif cmd == "SET" and len(parts) > 1:
                    try:
                        val = int(parts[1])
                        GLib.idle_add(self.set_brightness, val)
                        resp = {"status": "ok", "brightness": max(MIN_BRIGHTNESS, min(MAX_BRIGHTNESS, val))}
                    except ValueError:
                        resp = {"status": "error", "message": "Invalid value"}
                elif cmd == "UP":
                    step = int(parts[1]) if len(parts) > 1 else 5
                    new_val = min(MAX_BRIGHTNESS, self.brightness + step)
                    GLib.idle_add(self.set_brightness, new_val)
                    resp = {"status": "ok", "brightness": new_val}
                elif cmd == "DOWN":
                    step = int(parts[1]) if len(parts) > 1 else 5
                    new_val = max(MIN_BRIGHTNESS, self.brightness - step)
                    GLib.idle_add(self.set_brightness, new_val)
                    resp = {"status": "ok", "brightness": new_val}
                elif cmd == "TOGGLE_UI":
                    GLib.idle_add(self.toggle_ui)
                    resp = {"status": "ok", "action": "toggled"}
                elif cmd == "SHOW_UI":
                    GLib.idle_add(self.show_ui)
                    resp = {"status": "ok", "ui_visible": True}
                elif cmd == "HIDE_UI":
                    GLib.idle_add(self.hide_ui)
                    resp = {"status": "ok", "ui_visible": False}
                else:
                    resp = {"status": "error", "message": f"Unknown command {cmd}"}

                conn.sendall((json.dumps(resp) + "\n").encode("utf-8"))
                conn.close()
            except Exception as e:
                print(f"[Overlay] Socket worker error: {e}", file=sys.stderr)


def main():
    app = BrightnessOverlaySystem()
    try:
        Gtk.main()
    finally:
        if os.path.exists(SOCKET_PATH):
            try:
                os.unlink(SOCKET_PATH)
            except OSError:
                pass

if __name__ == "__main__":
    main()
