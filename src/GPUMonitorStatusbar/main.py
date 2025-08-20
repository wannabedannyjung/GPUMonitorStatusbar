import sys
import argparse
from .app import GPUMonitorStatusbar, have_nvidia_smi

def main():
    p = argparse.ArgumentParser(description="Always-on-top GPU/CPU/NET mini - All GPUs")
    p.add_argument("--interval", type=int, default=1000, help="Update interval in ms (default: 1000)")
    p.add_argument("--scale", type=float, default=1.0, help="UI scale factor (default: 1.0)")
    p.add_argument("--iface", type=str, default="auto", help="Network interface for download MB/s (default: auto)")
    p.add_argument("--xmargin", type=int, default=8, help="Right margin from screen edge (px, default: 8)")
    a = p.parse_args()

    if not have_nvidia_smi():
        print("Error: nvidia-smi not found in PATH. Install NVIDIA drivers & CUDA toolkit.", file=sys.stderr)
        sys.exit(1)

    app = GPUMonitorStatusbar(
        interval_ms=a.interval,
        scale=a.scale,
        iface=a.iface,
        xmargin=a.xmargin,
    )
    app.mainloop()
