#!/usr/bin/env python3
"""
ILI9486 Driver & Device Tree Web Management Utility
Antigravity SBC Display Tool - Radxa ROCK 4 SE

Runs a zero-dependency HTTP server on port 5000 providing an interactive GUI
to view/edit driver init sequences, toggle inversion & RGB/BGR, compile kernel modules,
update DTBO overlays, and view live system logs over SSH/LAN.
"""

import http.server
import socketserver
import json
import subprocess
import os
import re
import sys
from datetime import datetime
from urllib.parse import parse_qs, urlparse

PORT = 5000
HOST = os.environ.get("DRIVER_GUI_HOST", "127.0.0.1")
DRIVER_SRC = "/home/radxa/drm_build/ili9486.c"
DTS_SRC = "/home/radxa/35b1-mipidbi.dts"
DTBO_TARGET = "/boot/dtbo/35b1-mipidbi.dtbo"
MERGED_DTB = "/boot/dtbo/rk3399-rock-4se-mipidbi.dtb"

DIFF_SYSFS = "/sys/module/ili9486/parameters"
MODPROBE_CONF = "/etc/modprobe.d/ili9486.conf"
DIFF_DEFAULTS = {
    "diff_enable": 1,
    "diff_mode": 1,
    "diff_tile": 16,
    "merge_threshold": 4,
    "skip_nth": 1,
    "skip_even_rows": 0
}

def run_cmd(cmd, shell=True):
    try:
        res = subprocess.run(cmd, shell=shell, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=60)
        return res.returncode, res.stdout
    except Exception as e:
        return -1, str(e)

HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>ILI9486 Driver & Init Sequence Controller</title>
    <style>
        :root {
            --bg-color: #0f172a;
            --card-bg: #1e293b;
            --card-border: #334155;
            --text-main: #f8fafc;
            --text-sub: #94a3b8;
            --accent: #38bdf8;
            --accent-hover: #0284c7;
            --danger: #ef4444;
            --success: #22c55e;
            --warning: #f59e0b;
        }
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body {
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
            background-color: var(--bg-color);
            color: var(--text-main);
            padding: 20px;
            line-height: 1.5;
        }
        .container { max-width: 1000px; margin: 0 auto; }
        header {
            border-bottom: 2px solid var(--card-border);
            padding-bottom: 15px;
            margin-bottom: 20px;
            display: flex;
            justify-content: space-between;
            align-items: center;
        }
        h1 { font-size: 1.5rem; color: var(--accent); }
        .subtitle { color: var(--text-sub); font-size: 0.875rem; }
        .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); gap: 20px; margin-bottom: 20px; }
        .card {
            background: var(--card-bg);
            border: 1px solid var(--card-border);
            border-radius: 8px;
            padding: 15px 20px;
        }
        .card h2 { font-size: 1.1rem; margin-bottom: 12px; color: var(--accent); border-bottom: 1px solid var(--card-border); padding-bottom: 6px; }
        .status-row { display: flex; justify-content: space-between; margin-bottom: 8px; font-size: 0.9rem; }
        .badge {
            padding: 2px 8px;
            border-radius: 4px;
            font-size: 0.75rem;
            font-weight: bold;
            background: #475569;
        }
        .badge.active { background: var(--success); color: #000; }
        .badge.warning { background: var(--warning); color: #000; }
        .btn-group { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 10px; }
        button, input[type="submit"] {
            background-color: var(--card-border);
            color: var(--text-main);
            border: 1px solid #475569;
            padding: 8px 14px;
            border-radius: 6px;
            cursor: pointer;
            font-size: 0.875rem;
            font-weight: 500;
            transition: all 0.2s ease;
        }
        button:hover { background-color: var(--accent); color: #000; }
        button.primary { background-color: var(--accent); color: #0f172a; font-weight: 600; }
        button.primary:hover { background-color: var(--accent-hover); color: #fff; }
        button.danger { background-color: var(--danger); color: #fff; }
        button.danger:hover { background-color: #dc2626; }
        textarea {
            width: 100%;
            height: 250px;
            background: #020617;
            color: #38bdf8;
            border: 1px solid var(--card-border);
            border-radius: 6px;
            padding: 10px;
            font-family: "Courier New", Courier, monospace;
            font-size: 0.85rem;
            resize: vertical;
        }
        .gamma-canvas {
            display: block;
            width: 100%;
            height: 180px;
            background: #020617;
            border: 1px solid var(--card-border);
            border-radius: 6px;
            margin: 6px 0;
            cursor: crosshair;
        }
        .log-box {
            background: #020617;
            color: #a3e635;
            border: 1px solid var(--card-border);
            border-radius: 6px;
            padding: 12px;
            font-family: monospace;
            font-size: 0.8rem;
            height: 220px;
            overflow-y: auto;
            white-space: pre-wrap;
        }
        .toast {
            padding: 10px 15px;
            border-radius: 6px;
            margin-bottom: 15px;
            display: none;
        }
        .toast.success { background: #15803d; color: #fff; display: block; }
        .toast.error { background: #b91c1c; color: #fff; display: block; }
    </style>
</head>
<body>
    <div class="container">
        <header>
            <div>
                <h1>ILI9486 DRM / Overlay Controller</h1>
                <div class="subtitle">Radxa ROCK 4 SE &bull; Waveshare 3.5" (B) LCD</div>
            </div>
            <div>
                <button onclick="fetchStatus()" class="primary">Refresh Status</button>
            </div>
        </header>

        <div id="toast" class="toast"></div>

        <div class="grid">
            <div class="card">
                <h2>System Status</h2>
                <div class="status-row">
                    <span>Kernel Module (ili9486):</span>
                    <span id="mod-status" class="badge">Checking...</span>
                </div>
                <div class="status-row">
                    <span>Display Device (/dev/dri/card1):</span>
                    <span id="dri-status" class="badge">Checking...</span>
                </div>
                <div class="status-row">
                    <span>Active Display Manager (nodm):</span>
                    <span id="nodm-status" class="badge">Checking...</span>
                </div>
                <div class="status-row">
                    <span>SPI Controller Clock:</span>
                    <span id="spi-clk" style="font-weight: bold; color: var(--accent);">Checking...</span>
                </div>
            </div>

            <div class="card">
                <h2>Quick Display Toggles</h2>
                <div style="margin-bottom: 10px;">
                    <strong>Inversion Mode:</strong>
                    <div class="btn-group">
                        <button onclick="setInversion(false)">Inversion OFF (0x20)</button>
                        <button onclick="setInversion(true)">Inversion ON (0x21)</button>
                    </div>
                </div>
                <div style="margin-bottom: 10px;">
                    <strong>Color Channel Mode:</strong>
                    <div class="btn-group">
                        <button onclick="setChannel('RGB')">RGB Mode (BGR=0)</button>
                        <button onclick="setChannel('BGR')">BGR Mode (BGR=1)</button>
                    </div>
                </div>
                <div>
                    <strong>Display Rotation:</strong>
                    <div class="btn-group">
                        <button onclick="setRotation(0)">0&deg;</button>
                        <button onclick="setRotation(90)">90&deg; (Landscape)</button>
                        <button onclick="setRotation(180)">180&deg;</button>
                        <button onclick="setRotation(270)">270&deg;</button>
                    </div>
                </div>
            </div>
        </div>

        <div class="card" style="margin-bottom: 20px;">
            <h2>Screen Brightness Overlay (Software Dimmer)</h2>
            <p class="subtitle" style="margin-bottom: 12px;">Real-time opacity-adjustable black overlay for display brightness control. Starts automatically on boot via systemd.</p>
            <div style="display:flex; align-items:center; gap:15px; margin-bottom:12px;">
                <input type="range" id="overlay-brightness" min="10" max="100" value="75" oninput="onOverlaySliderInput(this.value)" onchange="setOverlayBrightness(this.value)" style="flex:1;">
                <span id="overlay-bright-val" style="font-size:1.3rem; font-weight:bold; color:var(--success); min-width:60px;">75%</span>
            </div>
            <div class="btn-group">
                <button onclick="setOverlayBrightness(100)">Max 100%</button>
                <button onclick="setOverlayBrightness(75)">75%</button>
                <button onclick="setOverlayBrightness(50)">50%</button>
                <button onclick="setOverlayBrightness(25)">25%</button>
                <button onclick="setOverlayBrightness(10)">Night 10%</button>
                <button onclick="toggleOverlayUI()">Toggle On-Screen UI</button>
            </div>
        </div>

        <div class="card">
            <h2>Advanced Adjustments</h2>
            <div style="margin-bottom: 10px;">
                <label style="display:block; margin-bottom:5px;"><strong>Brightness (0x51):</strong> <span id="bright-val">255</span></label>
                <input type="range" id="brightness" min="0" max="255" value="255" onchange="updateBrightness()" style="width:100%;">
            </div>
            <div style="margin-bottom: 10px;">
                <label style="display:block; margin-bottom:5px;"><strong>Positive Gamma (0xE0):</strong></label>
                <canvas id="gamma-pos-curve" class="gamma-canvas" height="180"></canvas>
                <input type="text" id="gamma-pos" value="0x00, 0x13, 0x18, 0x04, 0x0F, 0x06, 0x3A, 0x56, 0x4D, 0x03, 0x0A, 0x06, 0x30, 0x3E, 0x0F" style="width:100%; padding:5px; background:#020617; color:#38bdf8; border:1px solid #334155; border-radius:4px;">
            </div>
            <div style="margin-bottom: 10px;">
                <label style="display:block; margin-bottom:5px;"><strong>Negative Gamma (0xE1):</strong></label>
                <canvas id="gamma-neg-curve" class="gamma-canvas" height="180"></canvas>
                <input type="text" id="gamma-neg" value="0x00, 0x13, 0x18, 0x01, 0x11, 0x06, 0x38, 0x34, 0x4D, 0x06, 0x0D, 0x0B, 0x31, 0x37, 0x0F" style="width:100%; padding:5px; background:#020617; color:#38bdf8; border:1px solid #334155; border-radius:4px;">
            </div>
            <button onclick="applyGamma()" class="primary">Apply Advanced Settings</button>
        </div>

        <div class="card">
            <h2>Differential RGB565 Updates (Live sysfs & fbcp diffing)</h2>
            <p class="subtitle" style="margin-bottom: 12px;">High-performance fbcp-style scanline span merging & dirty rect diffing. Changes take effect <strong>INSTANTLY</strong> on the running display via sysfs without restarting Xorg or rebooting.</p>
            
            <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 15px; margin-bottom: 12px;">
                <div>
                    <label style="display:block; margin-bottom: 5px;"><strong>Diffing Status:</strong></label>
                    <label style="display:inline-flex; align-items:center; cursor:pointer; margin-top:4px;">
                        <input type="checkbox" id="diff-enable" style="width:20px; height:20px; margin-right:8px;">
                        <span id="diff-enable-label" style="font-weight:bold;">Enabled</span>
                    </label>
                </div>
                <div>
                    <label for="diff-mode" style="display:block; margin-bottom: 5px;"><strong>Diff Algorithm Mode:</strong></label>
                    <select id="diff-mode" style="width:100%; padding:6px; background:#020617; color:#f8fafc; border:1px solid #334155; border-radius:4px;">
                        <option value="1">Mode 1: fbcp Scanline Span Merging (Highest FPS - Recommended)</option>
                        <option value="2">Mode 2: Single Bounding Box (Fast CPU, larger SPI)</option>
                        <option value="3">Mode 3: Dirty Tile Grid (Classic 16x16)</option>
                        <option value="0">Mode 0: Disabled (Full Frame Updates)</option>
                    </select>
                </div>
            </div>

            <div style="display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 15px; margin-bottom: 15px;">
                <div>
                    <label for="diff-tile" style="display:block; margin-bottom: 5px;"><strong>Span Gap / Tile Size:</strong></label>
                    <select id="diff-tile" style="width:100%; padding:6px; background:#020617; color:#f8fafc; border:1px solid #334155; border-radius:4px;">
                        <option value="8">8 px</option>
                        <option value="16">16 px (Default)</option>
                        <option value="32">32 px</option>
                        <option value="64">64 px</option>
                        <option value="128">128 px</option>
                    </select>
                </div>
                <div>
                    <label for="merge-threshold" style="display:block; margin-bottom: 5px;"><strong>Merge Tolerance:</strong></label>
                    <input type="number" id="merge-threshold" min="0" max="64" value="4" style="width:100%; padding:6px; background:#020617; color:#f8fafc; border:1px solid #334155; border-radius:4px;">
                    <small style="color:var(--text-sub);">Max vertical gap (px)</small>
                </div>
                <div>
                    <label for="skip-nth" style="display:block; margin-bottom: 5px;"><strong>Pixel Skip (skip_nth):</strong></label>
                    <input type="number" id="skip-nth" min="1" max="16" value="1" style="width:100%; padding:6px; background:#020617; color:#f8fafc; border:1px solid #334155; border-radius:4px;">
                    <small style="color:var(--text-sub);">1 = All pixels (Normal), 2 = Skip every 2nd px</small>
                </div>
            <div style="margin-bottom: 15px;">
                <label for="skip-even-rows" style="display:block; margin-bottom: 5px;"><strong>Row Drawing / Scanline Mode:</strong></label>
                <select id="skip-even-rows" style="width:100%; padding:6px; background:#020617; color:#f8fafc; border:1px solid #334155; border-radius:4px;">
                    <option value="0">Mode 0: Draw All Rows (Normal, Current Driver Intact)</option>
                    <option value="1">Mode 1: Skip Even Rows (Draw Odd Rows Only - Halves SPI Data)</option>
                    <option value="2">Mode 2: Skip Odd Rows (Draw Even Rows Only)</option>
                    <option value="3">Mode 3: Interlaced (Alternate Even/Odd Fields Each Frame)</option>
                    <option value="4">Mode 4: Retro CRT Scanlines (Blackout Even Rows)</option>
                </select>
            </div>

            <div class="btn-group">
                <button onclick="applyDiffSettings()" class="primary">⚡ Apply Live Diffing Settings</button>
                <button onclick="fetchStatus()">Refresh Driver Values</button>
            </div>
            <div id="diff-status-msg" style="margin-top:10px; font-size:0.85rem; color:#38bdf8;"></div>
            <span id="diff-reboot" class="subtitle" style="display:block; margin-top:8px;"></span>
        </div>

        <div class="card" style="margin-bottom: 20px;">
            <h2>Driver Init Sequence Editor (ili9486.c)</h2>
            <p class="subtitle" style="margin-bottom: 10px;">Edit the command sequence below and click 'Compile & Reload Driver' to apply changes instantly on hardware.</p>
            <textarea id="init-code" spellcheck="false"></textarea>
            <div class="btn-group" style="margin-top: 10px;">
                <button onclick="saveAndCompileDriver()" class="primary">Compile & Reload Driver</button>
                <button onclick="loadDefaultInitSeq()">Reload Text</button>
            </div>
        </div>

        <div class="grid">
            <div class="card">
                <h2>Actions & Overlay Setup</h2>
                <div class="btn-group" style="flex-direction: column;">
                    <button onclick="compileDTBO()" class="primary">Compile & Install DTBO</button>
                    <button onclick="restartNODM()">Restart Matchbox / nodm</button>
                    <button onclick="rebootBoard()" class="danger">Reboot Radxa SBC</button>
                </div>
            </div>

            <div class="card">
                <h2>Live Console & Kernel Logs</h2>
                <div id="log-box" class="log-box">Console output will appear here...</div>
                <div class="btn-group" style="margin-top: 8px;">
                    <button onclick="fetchLogs()">Fetch dmesg</button>
                    <button onclick="clearConsole()">Clear Console</button>
                </div>
            </div>
        </div>
    </div>

    <script>
        function showToast(msg, isError = false) {
            const t = document.getElementById('toast');
            t.className = 'toast ' + (isError ? 'error' : 'success');
            t.innerText = msg;
            setTimeout(() => { t.className = 'toast'; }, 5000);
        }

        function appendLog(text) {
            const box = document.getElementById('log-box');
            box.innerText += '\\n' + text;
            box.scrollTop = box.scrollHeight;
        }

        function clearConsole() {
            document.getElementById('log-box').innerText = 'Console cleared.';
        }

        async function updateBrightness() {
            const val = document.getElementById('brightness').value;
            document.getElementById('bright-val').innerText = val;
        }

        const gammaEditors = {};

        function gammaValues(inputId) {
            return document.getElementById(inputId).value.split(',').map((value) => {
                const parsed = parseInt(value.trim(), 16);
                return Number.isFinite(parsed) ? Math.max(0, Math.min(255, parsed)) : 0;
            }).slice(0, 15);
        }

        function formatGamma(values) {
            return values.map((value) => '0x' + value.toString(16).padStart(2, '0').toUpperCase()).join(', ');
        }

        function drawGammaEditor(canvasId, inputId, color) {
            const canvas = document.getElementById(canvasId);
            const input = document.getElementById(inputId);
            if (!canvas || !input) return;
            const ratio = window.devicePixelRatio || 1;
            const width = Math.max(300, canvas.clientWidth);
            const height = 180;
            canvas.width = width * ratio;
            canvas.height = height * ratio;
            const ctx = canvas.getContext('2d');
            ctx.scale(ratio, ratio);
            const values = gammaValues(inputId);
            while (values.length < 15) values.push(values.length ? values[values.length - 1] : 0);
            const pointX = (index) => 10 + index * ((width - 20) / 14);
            const pointY = (value) => height - 12 - (value / 255) * (height - 24);

            ctx.fillStyle = '#020617';
            ctx.fillRect(0, 0, width, height);
            ctx.strokeStyle = '#334155';
            ctx.lineWidth = 1;
            for (let value = 0; value <= 255; value += 51) {
                const y = pointY(value);
                ctx.beginPath(); ctx.moveTo(10, y); ctx.lineTo(width - 10, y); ctx.stroke();
            }
            for (let index = 0; index < 15; index++) {
                const x = pointX(index);
                ctx.beginPath(); ctx.moveTo(x, 10); ctx.lineTo(x, height - 12); ctx.stroke();
            }
            ctx.strokeStyle = color;
            ctx.lineWidth = 2;
            ctx.beginPath();
            values.forEach((value, index) => {
                const x = pointX(index), y = pointY(value);
                if (index === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
            });
            ctx.stroke();
            values.forEach((value, index) => {
                ctx.fillStyle = color;
                ctx.beginPath(); ctx.arc(pointX(index), pointY(value), 5, 0, Math.PI * 2); ctx.fill();
            });
            gammaEditors[canvasId] = { canvas, input, values, pointX, pointY };
        }

        function installGammaEditor(canvasId, inputId, color) {
            const canvas = document.getElementById(canvasId);
            if (!canvas) return;
            drawGammaEditor(canvasId, inputId, color);
            canvas.addEventListener('pointerdown', (event) => {
                const editor = gammaEditors[canvasId];
                const rect = canvas.getBoundingClientRect();
                const x = event.clientX - rect.left;
                const y = event.clientY - rect.top;
                let nearest = 0, distance = Infinity;
                editor.values.forEach((value, index) => {
                    const dx = x - editor.pointX(index), dy = y - editor.pointY(value);
                    const distanceHere = dx * dx + dy * dy;
                    if (distanceHere < distance) { distance = distanceHere; nearest = index; }
                });
                const move = (moveEvent) => {
                    const moveY = moveEvent.clientY - rect.top;
                    editor.values[nearest] = Math.max(0, Math.min(255, Math.round((180 - 12 - moveY) * 255 / (180 - 24))));
                    editor.input.value = formatGamma(editor.values);
                    drawGammaEditor(canvasId, inputId, color);
                };
                const stop = () => {
                    window.removeEventListener('pointermove', move);
                    window.removeEventListener('pointerup', stop);
                };
                window.addEventListener('pointermove', move);
                window.addEventListener('pointerup', stop);
                canvas.setPointerCapture(event.pointerId);
            });
            inputId && document.getElementById(inputId).addEventListener('input', () => drawGammaEditor(canvasId, inputId, color));
        }

        function refreshGammaEditors() {
            drawGammaEditor('gamma-pos-curve', 'gamma-pos', '#38bdf8');
            drawGammaEditor('gamma-neg-curve', 'gamma-neg', '#f59e0b');
        }

        async function applyGamma() {
            const bright = document.getElementById('brightness').value;
            const gPos = document.getElementById('gamma-pos').value;
            const gNeg = document.getElementById('gamma-neg').value;
            appendLog(`Applying Brightness=${bright} and Gamma arrays...`);
            
            try {
                const res = await fetch('/api/set_gamma', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ brightness: bright, gamma_pos: gPos, gamma_neg: gNeg })
                });
                const data = await res.json();
                appendLog(data.log);
                showToast(data.message, !data.success);
                fetchInitCode();
            } catch (e) {
                showToast('Failed to apply settings: ' + e, true);
            }
        }

        async function applyDiffSettings() {
            const enabled = document.getElementById('diff-enable').checked ? 1 : 0;
            const mode = Number(document.getElementById('diff-mode').value);
            const tile = Number(document.getElementById('diff-tile').value);
            const merge = Number(document.getElementById('merge-threshold').value);
            const skip = Number(document.getElementById('skip-nth').value);

            if (!Number.isInteger(skip) || skip < 1 || skip > 16) {
                showToast('Pixel skip (skip-nth) must be between 1 and 16.', true);
                return;
            }
            if (!Number.isInteger(merge) || merge < 0 || merge > 64) {
                showToast('Merge tolerance must be between 0 and 64.', true);
                return;
            }

            const skipEven = Number(document.getElementById('skip-even-rows').value);

            appendLog(`Applying Diffing settings: enable=${enabled}, mode=${mode}, tile=${tile}, merge=${merge}, skip=${skip}, skip_even=${skipEven}...`);
            try {
                const res = await fetch('/api/diff_settings', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        diff_enable: enabled,
                        diff_mode: mode,
                        diff_tile: tile,
                        merge_threshold: merge,
                        skip_nth: skip,
                        skip_even_rows: skipEven
                    })
                });
                const data = await res.json();
                appendLog(data.log || '');
                showToast(data.message || 'Differential settings updated.', !data.success);
                const statusEl = document.getElementById('diff-status-msg');
                if (statusEl) {
                    statusEl.innerText = data.live_applied ?
                        '⚡ Applied live to kernel driver via sysfs! Next frame will use these settings.' :
                        'Saved for next boot.';
                }
                fetchStatus();
            } catch (e) {
                showToast('Failed to apply differential settings: ' + e, true);
            }
        }

        async function fetchStatus() {
            try {
                const res = await fetch('/api/status');
                const data = await res.json();
                
                const modEl = document.getElementById('mod-status');
                modEl.innerText = data.module ? 'LOADED' : 'NOT LOADED';
                modEl.className = 'badge ' + (data.module ? 'active' : 'warning');

                const driEl = document.getElementById('dri-status');
                driEl.innerText = data.dri ? 'READY' : 'OFFLINE';
                driEl.className = 'badge ' + (data.dri ? 'active' : 'warning');

                const nodmEl = document.getElementById('nodm-status');
                nodmEl.innerText = data.nodm ? 'RUNNING' : 'STOPPED';
                nodmEl.className = 'badge ' + (data.nodm ? 'active' : 'warning');

                document.getElementById('spi-clk').innerText = data.spi_clk || 'Unknown';
                if (data.diff_settings) {
                    const ds = data.diff_settings;
                    const isEn = (ds['diff_enable'] === 1 || ds['diff-enable'] === 1);
                    document.getElementById('diff-enable').checked = isEn;
                    const enLbl = document.getElementById('diff-enable-label');
                    if (enLbl) enLbl.innerText = isEn ? 'Enabled' : 'Disabled';

                    if (ds['diff_mode'] !== undefined) {
                        document.getElementById('diff-mode').value = String(ds['diff_mode']);
                    }
                    const tileVal = ds['diff_tile'] !== undefined ? ds['diff_tile'] : ds['diff-tile'];
                    if (tileVal !== undefined) {
                        document.getElementById('diff-tile').value = String(tileVal);
                    }
                    if (ds['merge_threshold'] !== undefined) {
                        document.getElementById('merge-threshold').value = ds['merge_threshold'];
                    }
                    const skipVal = ds['skip_nth'] !== undefined ? ds['skip_nth'] : ds['skip-nth'];
                    if (skipVal !== undefined) {
                        document.getElementById('skip-nth').value = skipVal;
                    }
                    if (ds['skip_even_rows'] !== undefined) {
                        document.getElementById('skip-even-rows').value = String(ds['skip_even_rows']);
                    }
                    const statusEl = document.getElementById('diff-status-msg');
                    if (statusEl && ds.sysfs_active) {
                        const modeNames = {0: "Disabled", 1: "fbcp Span Merging", 2: "Bounding Box", 3: "Tile Grid"};
                        const mName = modeNames[ds['diff_mode']] || `Mode ${ds['diff_mode']}`;
                        const skipEvenNames = {0: "All Rows", 1: "Skip Even", 2: "Skip Odd", 3: "Interlaced", 4: "Black Scanlines"};
                        const seName = skipEvenNames[ds['skip_even_rows']] || `Mode ${ds['skip_even_rows']}`;
                        statusEl.innerText = `Active in Kernel: ${mName} | Rows: ${seName} | Pixel Skip: ${skipVal == 1 ? "None (All px)" : "1/" + skipVal} | Span Gap ${tileVal}px | Merge Tol ${ds['merge_threshold']}px`;
                    }
                }
            } catch (e) {
                showToast('Failed to fetch status: ' + e, true);
            }
        }

        async function fetchInitCode() {
            try {
                const res = await fetch('/api/get_init');
                const data = await res.json();
                document.getElementById('init-code').value = data.code;
            } catch (e) {
                showToast('Failed to load init code: ' + e, true);
            }
        }

        async function saveAndCompileDriver() {
            const code = document.getElementById('init-code').value;
            appendLog('Saving driver init sequence and recompiling module...');
            try {
                const res = await fetch('/api/compile_driver', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ code })
                });
                const data = await res.json();
                appendLog(data.log);
                if (data.success) {
                    showToast('Driver recompiled and reloaded successfully!');
                    fetchStatus();
                } else {
                    showToast('Driver compilation/reload failed. Check log console.', true);
                }
            } catch (e) {
                appendLog('Error: ' + e);
                showToast('Network error during compilation', true);
            }
        }

        async function setInversion(on) {
            appendLog('Setting inversion mode to ' + (on ? 'ON (0x21)' : 'OFF (0x20)') + '...');
            try {
                const res = await fetch('/api/set_inversion', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ inversion: on })
                });
                const data = await res.json();
                appendLog(data.log);
                showToast(data.message, !data.success);
                fetchInitCode();
            } catch (e) {
                showToast('Failed to set inversion: ' + e, true);
            }
        }

        async function setChannel(mode) {
            appendLog('Setting color channel mode to ' + mode + '...');
            try {
                const res = await fetch('/api/set_channel', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ mode })
                });
                const data = await res.json();
                appendLog(data.log);
                showToast(data.message, !data.success);
                fetchInitCode();
            } catch (e) {
                showToast('Failed to set color mode: ' + e, true);
            }
        }

        async function setRotation(deg) {
            appendLog('Setting display rotation to ' + deg + ' deg in DTS...');
            try {
                const res = await fetch('/api/set_rotation', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ rotation: deg })
                });
                const data = await res.json();
                appendLog(data.log);
                showToast(data.message, !data.success);
            } catch (e) {
                showToast('Failed to set rotation: ' + e, true);
            }
        }

        async function compileDTBO() {
            appendLog('Compiling 35b1-mipidbi.dts to DTBO and updating system...');
            try {
                const res = await fetch('/api/compile_dtbo', { method: 'POST' });
                const data = await res.json();
                appendLog(data.log);
                showToast(data.message, !data.success);
            } catch (e) {
                showToast('Failed to compile DTBO: ' + e, true);
            }
        }

        async function restartNODM() {
            appendLog('Restarting nodm service...');
            try {
                const res = await fetch('/api/restart_nodm', { method: 'POST' });
                const data = await res.json();
                appendLog(data.log);
                showToast(data.message, !data.success);
                fetchStatus();
            } catch (e) {
                showToast('Failed to restart nodm: ' + e, true);
            }
        }

        async function rebootBoard() {
            if (!confirm('Are you sure you want to reboot the Radxa ROCK 4 SE board?')) return;
            appendLog('Sending reboot command...');
            try {
                await fetch('/api/reboot', { method: 'POST' });
                showToast('Rebooting board! Web interface will disconnect.', false);
            } catch (e) {
                showToast('Reboot command sent.', false);
            }
        }

        async function fetchLogs() {
            try {
                const res = await fetch('/api/logs');
                const data = await res.json();
                appendLog('=== dmesg | grep ili9486 ===\\n' + data.logs);
            } catch (e) {
                showToast('Failed to fetch logs: ' + e, true);
            }
        }

        async function loadDefaultInitSeq() {
            if (!confirm('Reset code area to disabled DTBO init sequence with Inversion OFF?')) return;
            fetchInitCode();
        }

        async function fetchOverlayBrightness() {
            try {
                const res = await fetch('/api/overlay_brightness');
                const data = await res.json();
                if (data.brightness !== undefined) {
                    document.getElementById('overlay-brightness').value = data.brightness;
                    document.getElementById('overlay-bright-val').innerText = data.brightness + '%';
                }
            } catch (e) {}
        }

        function onOverlaySliderInput(val) {
            document.getElementById('overlay-bright-val').innerText = val + '%';
        }

        async function setOverlayBrightness(val) {
            document.getElementById('overlay-brightness').value = val;
            document.getElementById('overlay-bright-val').innerText = val + '%';
            try {
                const res = await fetch('/api/overlay_brightness', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ brightness: parseInt(val) })
                });
                const data = await res.json();
                showToast('Brightness set to ' + val + '%');
            } catch (e) {
                showToast('Failed to set brightness: ' + e, true);
            }
        }

        async function toggleOverlayUI() {
            try {
                await fetch('/api/overlay_brightness', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ action: 'toggle' })
                });
                showToast('Toggled on-screen brightness UI');
            } catch (e) {
                showToast('Failed to toggle UI: ' + e, true);
            }
        }

        window.onload = () => {
            fetchStatus();
            fetchOverlayBrightness();
            fetchInitCode();
            fetchLogs();
            installGammaEditor('gamma-pos-curve', 'gamma-pos', '#38bdf8');
            installGammaEditor('gamma-neg-curve', 'gamma-neg', '#f59e0b');
            window.addEventListener('resize', refreshGammaEditors);
        };
    </script>
</body>
</html>
"""

def read_diff_settings():
    """Read differential update parameters from live sysfs or DTS source."""
    settings = dict(DIFF_DEFAULTS)
    sysfs_active = False

    if os.path.exists(DIFF_SYSFS):
        try:
            for k in list(DIFF_DEFAULTS.keys()):
                p = os.path.join(DIFF_SYSFS, k)
                if os.path.exists(p):
                    with open(p, "r") as f:
                        val = f.read().strip()
                        if k == "diff_enable":
                            settings[k] = 1 if val.upper() in ("Y", "1", "TRUE") else 0
                        else:
                            settings[k] = int(val)
                    sysfs_active = True
        except Exception:
            pass

    if not sysfs_active:
        try:
            with open(DTS_SRC, "r") as f:
                dts = f.read()
            mapping = {
                "diff_enable": "diff-enable",
                "diff_tile": "diff-tile",
                "skip_nth": "skip-nth"
            }
            for set_k, dts_k in mapping.items():
                match = re.search(r"%s\s*=\s*<([0-9]+)>\s*;" % re.escape(dts_k), dts)
                if match:
                    settings[set_k] = int(match.group(1))
        except OSError:
            pass

    settings["sysfs_active"] = sysfs_active
    return settings


def update_diff_settings(diff_enable, diff_mode, diff_tile, merge_threshold, skip_nth, skip_even_rows=0):
    """Update live sysfs parameters, /etc/modprobe.d/ili9486.conf, and DTBO."""
    if diff_enable not in (0, 1):
        raise ValueError("diff_enable must be 0 or 1")
    if diff_mode not in (0, 1, 2, 3):
        raise ValueError("diff_mode must be 0 (disabled), 1 (fbcp span), 2 (bounding box), or 3 (tile grid)")
    if diff_tile not in (8, 16, 32, 64, 128):
        raise ValueError("diff_tile must be 8, 16, 32, 64, or 128")
    if not (0 <= merge_threshold <= 64):
        raise ValueError("merge_threshold must be between 0 and 64")
    if not (1 <= skip_nth <= 16):
        raise ValueError("skip_nth must be between 1 and 16")
    if skip_even_rows not in (0, 1, 2, 3, 4):
        raise ValueError("skip_even_rows must be 0, 1, 2, 3, or 4")

    logs = []
    live_applied = False

    # 1. Update live sysfs parameters if available
    params = {
        "diff_enable": diff_enable,
        "diff_mode": diff_mode,
        "diff_tile": diff_tile,
        "merge_threshold": merge_threshold,
        "skip_nth": skip_nth,
        "skip_even_rows": skip_even_rows,
    }

    if os.path.exists(DIFF_SYSFS):
        sysfs_cmds = []
        for k, v in params.items():
            p = os.path.join(DIFF_SYSFS, k)
            if os.path.exists(p):
                val_str = "1" if (k == "diff_enable" and v == 1) else ("0" if (k == "diff_enable" and v == 0) else str(v))
                sysfs_cmds.append(f"echo {val_str} > {p}")
        if sysfs_cmds:
            cmd = "sudo -n sh -c '" + "; ".join(sysfs_cmds) + "'"
            c, out = run_cmd(cmd)
            if c == 0:
                logs.append("Live sysfs parameters updated successfully.")
                live_applied = True
            else:
                logs.append("Sysfs update warning: " + out.strip())

    # 2. Persist to /etc/modprobe.d/ili9486.conf for reboot survival
    modprobe_line = f"options ili9486 diff_enable={diff_enable} diff_mode={diff_mode} diff_tile={diff_tile} merge_threshold={merge_threshold} skip_nth={skip_nth} skip_even_rows={skip_even_rows}"
    cmd_modprobe = f"sudo -n sh -c 'echo \"{modprobe_line}\" > {MODPROBE_CONF}'"
    c_mod, out_mod = run_cmd(cmd_modprobe)
    if c_mod == 0:
        logs.append(f"Saved persistence to {MODPROBE_CONF}")
    else:
        logs.append("Modprobe persistence warning: " + out_mod.strip())

    # 3. Update DTS if present
    try:
        if os.path.exists(DTS_SRC):
            with open(DTS_SRC, "r") as f:
                dts = f.read()
            dts_vals = {"diff-enable": diff_enable, "diff-tile": diff_tile, "skip-nth": skip_nth}
            for name, value in dts_vals.items():
                replacement = "%s = <%d>;" % (name, value)
                pattern = r"%s\s*=\s*<\d+>\s*;" % re.escape(name)
                if re.search(pattern, dts):
                    dts = re.sub(pattern, replacement, dts, count=1)
            backup = DTS_SRC + ".backup-" + datetime.now().strftime("%Y%m%d-%H%M%S")
            with open(DTS_SRC + ".new", "w") as f:
                f.write(dts)
            os.replace(DTS_SRC, backup)
            os.replace(DTS_SRC + ".new", DTS_SRC)
            dtc_cmd = f"dtc -@ -I dts -O dtb -o /home/radxa/35b1-mipidbi.dtbo {DTS_SRC} && sudo -n cp /home/radxa/35b1-mipidbi.dtbo {DTBO_TARGET}"
            c_dtc, out_dtc = run_cmd(dtc_cmd)
            if c_dtc == 0:
                logs.append("DTS updated and DTBO compiled.")
    except Exception as e:
        logs.append("DTS update note: " + str(e))

    return True, "\n".join(logs), live_applied

class RequestHandler(http.server.BaseHTTPRequestHandler):
    def _send_json(self, data, code=200):
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(json.dumps(data).encode("utf-8"))

    def _send_html(self, html):
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(html.encode("utf-8"))

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/" or parsed.path == "/index.html":
            self._send_html(HTML_TEMPLATE)
        elif parsed.path == "/api/status":
            _, mod_out = run_cmd("lsmod | grep ili9486")
            _, dri_out = run_cmd("ls -l /dev/dri/card1 2>/dev/null")
            _, nodm_out = run_cmd("systemctl is-active nodm")
            _, clk_out = run_cmd("sudo -n grep -i spi1 /sys/kernel/debug/clk/clk_summary 2>/dev/null")
            
            clk_match = re.search(r'clk_spi1\s+\d+\s+\d+\s+\d+\s+(\d+)', clk_out)
            clk_str = f"{int(clk_match.group(1)) / 1e6:.2f} MHz" if clk_match else "32.0 MHz (Configured)"
            
            self._send_json({
                "module": bool(mod_out.strip()),
                "dri": bool("card1" in dri_out),
                "nodm": "active" in nodm_out,
                "spi_clk": clk_str,
                "diff_settings": read_diff_settings()
            })
        elif parsed.path == "/api/get_init":
            code_text = ""
            if os.path.exists(DRIVER_SRC):
                with open(DRIVER_SRC, "r") as f:
                    content = f.read()
                    # Extract waveshare_enable function
                    match = re.search(r'static void waveshare_enable.*?\n\{([\s\S]*?)\n\}', content)
                    if match:
                        code_text = match.group(1).strip()
                    else:
                        code_text = content
            self._send_json({"code": code_text})
        elif parsed.path == "/api/logs":
            _, log_out = run_cmd("sudo -n dmesg | grep -i -E 'ili9486|mipidbi' | tail -n 30")
            self._send_json({"logs": log_out})
        elif parsed.path == "/api/overlay_brightness":
            code, out = run_cmd("/usr/local/bin/brightness-cli get")
            m = re.search(r'Brightness:\s*(\d+)%', out)
            val = int(m.group(1)) if m else 75
            self._send_json({"brightness": val, "raw": out.strip()})
        else:
            self.send_error(404)

    def do_POST(self):
        parsed = urlparse(self.path)
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length).decode("utf-8") if length > 0 else ""
        data = json.loads(body) if body else {}

        if parsed.path == "/api/diff_settings":
            try:
                diff_enable = int(data.get("diff_enable", 1))
                diff_mode = int(data.get("diff_mode", 1))
                diff_tile = int(data.get("diff_tile", 16))
                merge_threshold = int(data.get("merge_threshold", 4))
                skip_nth = int(data.get("skip_nth", 1))
                skip_even_rows = int(data.get("skip_even_rows", 0))
                success, output, live_applied = update_diff_settings(
                    diff_enable, diff_mode, diff_tile, merge_threshold, skip_nth, skip_even_rows
                )
                self._send_json({
                    "success": success,
                    "message": "Differential settings applied LIVE to kernel driver!" if live_applied else "Settings saved.",
                    "log": output,
                    "live_applied": live_applied,
                    "reboot_required": not live_applied
                })
            except (TypeError, ValueError, OSError) as exc:
                self._send_json({"success": False, "message": str(exc), "log": ""}, 400)

        elif parsed.path == "/api/compile_driver":
            new_func_body = data.get("code", "")
            if not os.path.exists(DRIVER_SRC):
                self._send_json({"success": False, "log": "Driver source not found at " + DRIVER_SRC})
                return

            with open(DRIVER_SRC, "r") as f:
                content = f.read()

            # Replace body of waveshare_enable
            pattern = r'(static void waveshare_enable.*?\n\{)[\s\S]*?(\n\})'
            replacement = r'\1\n' + new_func_body + r'\2'
            updated_content = re.sub(pattern, replacement, content)

            with open(DRIVER_SRC, "w") as f:
                f.write(updated_content)

            # Build and reload cleanly
            cmd = (
                "cd /home/radxa/drm_build && make && "
                "sudo -n systemctl stop nodm || true && "
                "sudo -n fuser -k /dev/dri/* 2>/dev/null || true && "
                "sudo -n rmmod ili9486 2>/dev/null || true && "
                "sudo -n rmmod drm_mipi_dbi 2>/dev/null || true && "
                "sudo -n cp drm_mipi_dbi.ko ili9486.ko /lib/modules/$(uname -r)/extra/ && "
                "sudo -n depmod -a && "
                "sudo -n modprobe drm_mipi_dbi && "
                "sudo -n modprobe ili9486 && "
                "sudo -n systemctl start nodm"
            )
            code, out = run_cmd(cmd)
            self._send_json({"success": code == 0, "log": out})

        elif parsed.path == "/api/set_inversion":
            on = data.get("inversion", False)
            cmd_val = "MIPI_DCS_ENTER_INVERT_MODE" if on else "MIPI_DCS_EXIT_INVERT_MODE"
            hex_val = "0x21" if on else "0x20"
            
            with open(DRIVER_SRC, "r") as f:
                content = f.read()

            content = re.sub(r'mipi_dbi_command\(dbi, MIPI_DCS_(ENTER|EXIT)_INVERT_MODE\);',
                             f'mipi_dbi_command(dbi, {cmd_val});', content)
            
            with open(DRIVER_SRC, "w") as f:
                f.write(content)

            # Recompile
            cmd = "cd /home/radxa/drm_build && make && sudo -n cp ili9486.ko /lib/modules/$(uname -r)/extra/ && sudo -n depmod -a"
            code, out = run_cmd(cmd)
            msg = f"Inversion set to {hex_val} ({cmd_val}). Recompile result: {'Success' if code==0 else 'Failed'}"
            self._send_json({"success": code == 0, "message": msg, "log": out})

        elif parsed.path == "/api/set_channel":
            self._send_json({
                "success": False,
                "message": "RGB/BGR switching is not implemented in this snapshot.",
                "log": "The tested driver keeps BGR enabled in MADCTL."
            }, 501)

        elif parsed.path == "/api/set_gamma":
            bright = int(data.get("brightness", 255))
            gpos = data.get("gamma_pos", "")
            gneg = data.get("gamma_neg", "")

            with open(DRIVER_SRC, "r") as f:
                content = f.read()

            # Insert brightness command if not exists, right after Display ON
            bright_cmd = f"\n\t/* 0x1000051 - Brightness */\n\tmipi_dbi_command(dbi, 0x51, 0x{bright:02X});\n\tmipi_dbi_command(dbi, 0x53, 0x24);"
            
            if "0x51" in content:
                content = re.sub(r'mipi_dbi_command\(dbi, 0x51, 0x[0-9A-Fa-f]{2}\);', f'mipi_dbi_command(dbi, 0x51, 0x{bright:02X});', content)
            else:
                content = content.replace("mipi_dbi_command(dbi, MIPI_DCS_SET_DISPLAY_ON);\n\tmsleep(50);", f"mipi_dbi_command(dbi, MIPI_DCS_SET_DISPLAY_ON);\n\tmsleep(50);{bright_cmd}")

            # Update Gamma
            if gpos:
                content = re.sub(r'mipi_dbi_command\(dbi, 0xE0,[\s\S]*?\);', f'mipi_dbi_command(dbi, 0xE0,\n\t\t\t {gpos});', content)
            if gneg:
                content = re.sub(r'mipi_dbi_command\(dbi, 0xE1,[\s\S]*?\);', f'mipi_dbi_command(dbi, 0xE1,\n\t\t\t {gneg});', content)

            with open(DRIVER_SRC, "w") as f:
                f.write(content)

            # Recompile
            cmd = "cd /home/radxa/drm_build && make && sudo -n cp ili9486.ko /lib/modules/$(uname -r)/extra/ && sudo -n depmod -a"
            code, out = run_cmd(cmd)
            self._send_json({"success": code == 0, "message": "Advanced settings applied and compiled.", "log": out})

        elif parsed.path == "/api/set_rotation":
            rot = data.get("rotation", 90)
            with open(DTS_SRC, "r") as f:
                dts = f.read()
            dts = re.sub(r'rotation = <\d+>;', f'rotation = <{rot}>;', dts)
            with open(DTS_SRC, "w") as f:
                f.write(dts)
            
            # Recompile DTS
            cmd = f"dtc -@ -I dts -O dtb -o /home/radxa/35b1-mipidbi.dtbo {DTS_SRC} && sudo -n cp /home/radxa/35b1-mipidbi.dtbo {DTBO_TARGET}"
            code, out = run_cmd(cmd)
            self._send_json({"success": code == 0, "message": f"Rotation updated to {rot} deg.", "log": out})

        elif parsed.path == "/api/compile_dtbo":
            cmd = (
                f"dtc -@ -I dts -O dtb -o /home/radxa/35b1-mipidbi.dtbo {DTS_SRC} && "
                f"sudo -n cp /home/radxa/35b1-mipidbi.dtbo {DTBO_TARGET} && "
                f"sudo -n fdtoverlay -i /usr/lib/linux-image-$(uname -r)/rockchip/rk3399-rock-4se.dtb -o {MERGED_DTB} {DTBO_TARGET}"
            )
            code, out = run_cmd(cmd)
            self._send_json({"success": code == 0, "message": "DTBO compiled and merged.", "log": out})

        elif parsed.path == "/api/restart_nodm":
            code, out = run_cmd("sudo -n systemctl restart nodm")
            self._send_json({"success": code == 0, "message": "nodm service restarted.", "log": out})

        elif parsed.path == "/api/reboot":
            self._send_json({"success": True, "message": "Rebooting..."})
            subprocess.Popen("sudo -n reboot", shell=True)

        elif parsed.path == "/api/overlay_brightness":
            val = data.get("brightness", 75)
            action = data.get("action", "")
            if action == "toggle":
                code, out = run_cmd("/usr/local/bin/brightness-cli toggle")
            else:
                try:
                    val = int(val)
                except (TypeError, ValueError):
                    self._send_json({"success": False, "message": "Brightness must be an integer from 10 to 100."}, 400)
                    return
                if not 10 <= val <= 100:
                    self._send_json({"success": False, "message": "Brightness must be between 10 and 100."}, 400)
                    return
                code, out = run_cmd(f"/usr/local/bin/brightness-cli set {val}")
            self._send_json({"success": code == 0, "message": out.strip()})

        else:
            self.send_error(404)

def main():
    print(f"Starting ILI9486 GUI Server on http://{HOST}:{PORT}")
    socketserver.TCPServer.allow_reuse_address = True
    server = socketserver.TCPServer((HOST, PORT), RequestHandler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nServer stopped.")

if __name__ == "__main__":
    main()
