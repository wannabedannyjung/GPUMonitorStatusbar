#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import argparse
import shutil
import subprocess
import sys
import time
import tkinter as tk

# Optional psutil for CPU/NET
try:
    import psutil  # type: ignore
except Exception:
    psutil = None

# ----------------------------- Helpers -----------------------------

def have_nvidia_smi() -> bool:
    return shutil.which("nvidia-smi") is not None

def get_gpu_count() -> int:
    out = subprocess.check_output(
        ["nvidia-smi", "--list-gpus"],
        encoding="utf-8"
    )
    return len(out.strip().splitlines())

def query_gpu_metrics(index: int = 0):
    """Returns (util, power, temp) as floats. Util%, Power W, Temp C."""
    out = subprocess.check_output(
        [
            "nvidia-smi",
            "--query-gpu=utilization.gpu,power.draw,temperature.gpu",
            "--format=csv,noheader,nounits",
            "-i",
            str(index),
        ],
        encoding="utf-8",
        stderr=subprocess.STDOUT,
    )
    line = out.strip().splitlines()[0] if out.strip() else ""
    parts = [p.strip() for p in line.split(",")]
    if len(parts) < 3:
        raise RuntimeError(f"Unexpected nvidia-smi output: {out!r}")
    return float(parts[0]), float(parts[1]), float(parts[2])

def color_for_util(x: float) -> str:
    if x < 40: return "#22c55e"  # green
    if x < 70: return "#f59e0b"  # amber
    return "#ef4444"             # red

def color_for_temp(t: float) -> str:
    if t < 70: return "#22c55e"
    if t < 85: return "#f59e0b"
    return "#ef4444"

def color_for_cpu(c: float) -> str:
    if c < 40: return "#22c55e"
    if c < 75: return "#f59e0b"
    return "#ef4444"

# CPU & NET helpers
def get_cpu_percent() -> float:
    if psutil:
        return float(psutil.cpu_percent(interval=None))
    # minimal fallback: show 0 if psutil not present
    return 0.0

def get_net_bytes_recv(iface=None):
    # psutil path
    if psutil:
        counters = psutil.net_io_counters(pernic=True)
        if iface and iface in counters:
            return counters[iface].bytes_recv
        candidates = {k:v for k,v in counters.items() if not k.startswith("lo")}
        if not candidates:
            return 0
        name = max(candidates, key=lambda k: counters[k].bytes_recv + counters[k].bytes_sent)
        return counters[name].bytes_recv
    # fallback (Linux)
    try:
        with open("/proc/net/dev", "r") as f:
            lines = f.readlines()
        stats = {}
        for ln in lines[2:]:
            if ":" not in ln:
                continue
            name, rest = ln.split(":", 1)
            name = name.strip()
            cols = rest.split()
            if len(cols) >= 1:
                rx_bytes = int(cols[0])
                stats[name] = rx_bytes
        candidates = {k:v for k,v in stats.items() if not k.startswith("lo")}
        if not candidates:
            return 0
        name = max(candidates, key=lambda k: candidates[k])
        return candidates[name]
    except Exception:
        return 0

def get_net_download_mbps(prev_bytes, curr_bytes, delta_sec):
    if delta_sec <= 0: return 0.0
    return max(0, (curr_bytes - prev_bytes) / (1024*1024)) / delta_sec  # MB/s

# ----------------------------- UI -----------------------------

class GPUMonitorStatusbar(tk.Tk):
    def __init__(self, interval_ms=1000, scale=1.0, iface=None, xmargin=8):
        super().__init__()

        self.gpu_count = get_gpu_count()
        self.interval_ms = max(250, int(interval_ms))
        self.scale = float(scale) if scale > 0 else 1.0
        self.drag_start = None
        self.borderless = True
        self.iface = None if (iface in [None, "", "auto"]) else iface
        self.xmargin = int(xmargin)

        if psutil:
            psutil.cpu_percent(interval=None)  # warm up

        self._prev_rx = get_net_bytes_recv(self.iface)
        self._prev_time = time.time()

        # UI 초기화
        self.title("GPU/CPU/NET (Top=0 launch)")
        self.configure(bg="#111827")
        self.attributes("-topmost", True)
        self.overrideredirect(True)
        self.resizable(False, False)

        # Drag & Menu
        self.bind("<ButtonPress-1>", self.on_press)
        self.bind("<B1-Motion>", self.on_drag)
        self.menu = tk.Menu(self, tearoff=0)
        self.menu.add_command(label="Toggle border", command=self.toggle_border)
        self.menu.add_separator()
        self.menu.add_command(label="Quit", command=self.quit)
        self.bind("<Button-3>", self.show_menu)
        self.bind("q", lambda e: self.quit())

        # Font
        base = int(11 * self.scale)
        # 리눅스라면 "Noto Sans Mono" 또는 "DejaVu Sans Mono"가 선명합니다.
        self.font_main = ("Noto Sans Mono", base, "bold")

        pad_x = int(6 * self.scale)
        pad_y = int(1 * self.scale)
        self.container = tk.Frame(self, bg="#111827", padx=pad_x, pady=pad_y)
        self.container.pack()

        self.minsize(800, 1)

        # GPU별 라벨
        self.gpu_labels = []
        col = 0
        def add_label(text, fg="#e5e7eb"):
            nonlocal col
            lbl = tk.Label(self.container, text=text, fg=fg, bg="#111827", font=self.font_main)
            lbl.grid(row=0, column=col, sticky="w")
            col += 1
            return lbl
        def add_sep(text=" | "):
            return add_label(text, fg="#6b7280")

        for i in range(self.gpu_count):
            tag = add_label(f"GPU{i} ", fg="#e5e7eb")
            util = add_label("--%", fg="#9ca3af"); add_sep()
            power = add_label("-- W", fg="#e5e7eb"); add_sep()
            temp = add_label("-- °C", fg="#9ca3af"); add_sep()
            self.gpu_labels.append((util, power, temp))

        # CPU & NET
        self.lbl_cpu_tag = add_label("CPU ", fg="#e5e7eb")
        self.lbl_cpu = add_label("--%", fg="#9ca3af"); add_sep()
        self.lbl_net_tag = add_label("NET↓ ", fg="#e5e7eb")
        self.lbl_net = add_label("-- MB/s", fg="#9ca3af")

        self.update_idletasks()
        self.place_top_right_y0()
        self.after(200, self.refresh)

    # Initial placement only (no auto return after move)
    def place_top_right_y0(self):
        sw = self.winfo_screenwidth()
        ww = self.winfo_width()
        wh = self.winfo_height()
    
        # 원래 위치에서 x00px 왼쪽으로 이동
        x = sw - ww - self.xmargin - 200
        
        y = 0  # Start flush to top
        self.geometry(f"{ww}x{wh}+{x}+{y}")

    def on_press(self, event):
        self.drag_start = (event.x_root, event.y_root, self.winfo_x(), self.winfo_y())

    def on_drag(self, event):
        if not self.drag_start:
            return
        sx, sy, ox, oy = self.drag_start
        dx = event.x_root - sx
        dy = event.y_root - sy
        self.geometry(f"+{ox + dx}+{oy + dy}")

    def show_menu(self, event):
        try:
            self.menu.tk_popup(event.x_root, event.y_root)
        finally:
            self.menu.grab_release()

    def toggle_border(self):
        self.borderless = not self.borderless
        self.overrideredirect(self.borderless)

    # Refresh loop (no auto-snap back)
    def refresh(self):
        # GPU들 모두 업데이트
        for i, (util_lbl, power_lbl, temp_lbl) in enumerate(self.gpu_labels):
            try:
                util, power, temp = query_gpu_metrics(i)
                util_lbl.config(text=f"{util:.0f}%", fg=color_for_util(util))
                power_lbl.config(text=f"{power:.0f} W", fg="#e5e7eb")
                temp_lbl.config(text=f"{temp:.0f} °C", fg=color_for_temp(temp))
            except Exception:
                util_lbl.config(text="err", fg="#ef4444")
                power_lbl.config(text="n/a", fg="#f59e0b")
                temp_lbl.config(text="-- °C", fg="#9ca3af")

        # CPU
        try:
            cpu = get_cpu_percent()
            self.lbl_cpu.config(text=f"{cpu:.0f}%", fg=color_for_cpu(cpu))
        except Exception:
            self.lbl_cpu.config(text="--%", fg="#9ca3af")

        # NET
        now = time.time()
        curr_rx = get_net_bytes_recv(self.iface)
        mbps = get_net_download_mbps(self._prev_rx, curr_rx, now - self._prev_time)
        self._prev_rx, self._prev_time = curr_rx, now
        self.lbl_net.config(text=f"{mbps:.2f} MB/s", fg="#9ca3af")

        self.after(self.interval_ms, self.refresh)