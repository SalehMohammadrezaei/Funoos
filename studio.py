"""FlowZoo Studio — interactive control panel for the whole gallery.

Pick an exhibit, tune its parameters (each with a "?" explaining what it does),
choose a color palette / resolution / duration, hit Run, watch the simulation
animate live, then export a GIF or MP4. One app containing every solver.

    python studio.py

Package as a standalone Windows executable: see docs/windows_build.md.
"""
from __future__ import annotations

import queue
import sys
import threading
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
from flowzoo import engine, render

try:
    import tkinter as tk
    from tkinter import ttk, filedialog, messagebox
    from PIL import Image, ImageTk
except Exception as e:  # pragma: no cover
    tk = None
    _IMPORT_ERR = e

# palette
BG = "#0e1016"; PANEL = "#171a23"; CARD = "#1e2330"
FG = "#e8ecf3"; MUTED = "#8b95a8"; ACCENT = "#3b82f6"; ACCENT2 = "#2a3142"


class Tooltip:
    """Hover tooltip for the '?' help chips."""
    def __init__(self, widget, text):
        self.widget, self.text, self.tip = widget, text, None
        widget.bind("<Enter>", self.show)
        widget.bind("<Leave>", self.hide)

    def show(self, _=None):
        if self.tip or not self.text:
            return
        x = self.widget.winfo_rootx() + 20
        y = self.widget.winfo_rooty() + 20
        self.tip = tk.Toplevel(self.widget)
        self.tip.wm_overrideredirect(True)
        self.tip.wm_geometry(f"+{x}+{y}")
        tk.Label(self.tip, text=self.text, bg="#0b0d14", fg=FG, justify="left",
                 wraplength=300, padx=10, pady=8, relief="solid", borderwidth=1,
                 font=("Helvetica", 9)).pack()

    def hide(self, _=None):
        if self.tip:
            self.tip.destroy(); self.tip = None


class Studio:
    def __init__(self, root):
        self.root = root
        root.title("FlowZoo Studio")
        root.configure(bg=BG)
        self.q = queue.Queue()
        self.frames, self.play_idx, self.playing, self.busy = [], 0, False, False
        self.fps = tk.IntVar(value=26)
        self.param_widgets = {}

        style = ttk.Style()
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure("TCombobox", fieldbackground=CARD, background=CARD, foreground=FG)
        style.configure("Accent.Horizontal.TProgressbar", background=ACCENT,
                        troughcolor=CARD, borderwidth=0)

        # ---- sidebar ----
        side = tk.Frame(root, bg=PANEL, width=300)
        side.pack(side="left", fill="y"); side.pack_propagate(False)
        tk.Label(side, text="🦓  FlowZoo Studio", bg=PANEL, fg=FG,
                 font=("Helvetica", 16, "bold")).pack(anchor="w", padx=16, pady=(16, 2))
        tk.Label(side, text="a zoo of fluid simulations", bg=PANEL, fg=MUTED,
                 font=("Helvetica", 9)).pack(anchor="w", padx=16, pady=(0, 12))

        tk.Label(side, text="EXHIBIT", bg=PANEL, fg=MUTED,
                 font=("Helvetica", 8, "bold")).pack(anchor="w", padx=16)
        self.exhibit = tk.StringVar(value=list(engine.EXHIBITS)[0])
        cb = ttk.Combobox(side, textvariable=self.exhibit, state="readonly",
                          values=list(engine.EXHIBITS))
        cb.pack(fill="x", padx=16, pady=(2, 10)); cb.bind("<<ComboboxSelected>>",
                                                          lambda *_: self._build_params())

        self.param_frame = tk.Frame(side, bg=PANEL)
        self.param_frame.pack(fill="x", padx=16)

        # playback speed
        sp = tk.Frame(side, bg=PANEL); sp.pack(fill="x", padx=16, pady=(12, 4))
        tk.Label(sp, text="Playback FPS", bg=PANEL, fg=MUTED).pack(side="left")
        tk.Scale(side, from_=8, to=40, orient="horizontal", variable=self.fps,
                 bg=PANEL, fg=FG, highlightthickness=0, troughcolor=CARD,
                 bd=0).pack(fill="x", padx=16)

        self.run_btn = tk.Button(side, text="▶  Run simulation", command=self.run,
                                 bg=ACCENT, fg="white", relief="flat", pady=9,
                                 activebackground="#2f6fd6", font=("Helvetica", 11, "bold"))
        self.run_btn.pack(fill="x", padx=16, pady=(14, 6))

        self.prog = ttk.Progressbar(side, mode="indeterminate",
                                    style="Accent.Horizontal.TProgressbar")
        # shown only while running

        bf = tk.Frame(side, bg=PANEL); bf.pack(fill="x", padx=16, pady=4)
        for txt, k in (("⬇ Save GIF", "gif"), ("⬇ Save MP4", "mp4")):
            tk.Button(bf, text=txt, command=lambda k=k: self.save(k), bg=ACCENT2,
                      fg=FG, relief="flat", activebackground="#39425a").pack(
                side="left", expand=True, fill="x", padx=2)

        self.status = tk.Label(side, text="Ready.", bg=PANEL, fg=MUTED,
                               wraplength=268, justify="left", font=("Helvetica", 9))
        self.status.pack(anchor="w", padx=16, pady=(14, 0))

        # ---- preview ----
        self.canvas = tk.Label(root, bg="#06070b",
                               text="Pick an exhibit and press Run ▶",
                               fg=MUTED, font=("Helvetica", 13))
        self.canvas.pack(side="right", expand=True, fill="both", padx=8, pady=8)

        self._build_params()
        self.root.after(80, self._poll)
        self.root.after(40, self._tick)

    def _build_params(self):
        for w in self.param_frame.winfo_children():
            w.destroy()
        self.param_widgets = {}
        for qd in engine.EXHIBITS[self.exhibit.get()]["params"]:
            row = tk.Frame(self.param_frame, bg=PANEL); row.pack(fill="x", pady=(8, 0))
            head = tk.Frame(row, bg=PANEL); head.pack(fill="x")
            label = qd.get("label", qd["name"])
            if qd["type"] == "float":
                label += f"  ({qd['min']:g}–{qd['max']:g})"
            tk.Label(head, text=label, bg=PANEL, fg=FG,
                     font=("Helvetica", 9, "bold")).pack(side="left")
            if qd.get("help"):
                chip = tk.Label(head, text=" ? ", bg=ACCENT2, fg=FG,
                                font=("Helvetica", 8, "bold"), cursor="question_arrow")
                chip.pack(side="right")
                Tooltip(chip, qd["help"])
                chip.bind("<Button-1>", lambda e, t=qd["help"], n=label:
                          messagebox.showinfo(n, t))
            if qd["type"] == "choice":
                v = tk.StringVar(value=qd["default"])
                ttk.Combobox(row, textvariable=v, state="readonly",
                             values=qd["choices"]).pack(fill="x", pady=(3, 0))
            elif qd["type"] == "str":
                v = tk.StringVar(value=qd["default"])
                tk.Entry(row, textvariable=v, bg=CARD, fg=FG, relief="flat",
                         insertbackground=FG).pack(fill="x", pady=(3, 0), ipady=3)
            else:  # float
                v = tk.StringVar(value=f"{qd['default']:g}")
                tk.Entry(row, textvariable=v, bg=CARD, fg=FG, relief="flat",
                         insertbackground=FG).pack(fill="x", pady=(3, 0), ipady=3)
            self.param_widgets[qd["name"]] = (qd, v)

    def _params(self):
        out = {}
        for name, (qd, v) in self.param_widgets.items():
            val = v.get()
            out[name] = float(val) if qd["type"] == "float" else val
        return out

    def run(self):
        if self.busy:
            return
        try:
            params = self._params()
        except ValueError:
            self.status.config(text="A numeric field has an invalid value."); return
        self.busy = True; self.playing = False
        self.run_btn.config(state="disabled", text="● Simulating…")
        self.prog.pack(fill="x", padx=16, pady=(2, 4)); self.prog.start(12)
        name = self.exhibit.get()

        def work():
            try:
                fr, info = engine.run_exhibit(name, params,
                                              progress=lambda s: self.q.put(("status", s)))
                self.q.put(("done", (fr, info)))
            except Exception as ex:  # pragma: no cover
                self.q.put(("error", str(ex)))
        threading.Thread(target=work, daemon=True).start()

    def _poll(self):
        try:
            while True:
                kind, payload = self.q.get_nowait()
                if kind == "status":
                    self.status.config(text="⏳ " + payload)
                elif kind == "done":
                    self.frames, info = payload
                    self.play_idx, self.playing, self.busy = 0, True, False
                    self.status.config(text=f"✓ {info}\n{len(self.frames)} frames — playing.")
                    self.run_btn.config(state="normal", text="▶  Run simulation")
                    self.prog.stop(); self.prog.pack_forget()
                elif kind == "error":
                    self.busy = False
                    self.status.config(text=f"⚠ Error: {payload}")
                    self.run_btn.config(state="normal", text="▶  Run simulation")
                    self.prog.stop(); self.prog.pack_forget()
        except queue.Empty:
            pass
        self.root.after(80, self._poll)

    def _tick(self):
        if self.playing and self.frames:
            arr = self.frames[self.play_idx % len(self.frames)]
            cw, ch = max(self.canvas.winfo_width(), 100), max(self.canvas.winfo_height(), 100)
            img = Image.fromarray(arr)
            sc = min(cw / img.width, ch / img.height)
            img = img.resize((max(1, int(img.width * sc)), max(1, int(img.height * sc))))
            self._photo = ImageTk.PhotoImage(img)
            self.canvas.config(image=self._photo, text="")
            self.play_idx += 1
        self.root.after(int(1000 / max(1, self.fps.get())), self._tick)

    def save(self, kind):
        if not self.frames:
            messagebox.showinfo("FlowZoo", "Run a simulation first."); return
        ext = "." + kind
        path = filedialog.asksaveasfilename(defaultextension=ext, initialfile="flowzoo" + ext)
        if not path:
            return
        try:
            (render.save_gif if kind == "gif" else render.save_mp4)(
                self.frames, path, fps=self.fps.get())
            self.status.config(text=f"✓ Saved {path}")
        except Exception as ex:
            messagebox.showerror("Export failed",
                                 f"{ex}\n\nGIF/MP4 export needs ffmpeg (see docs/windows_build.md).")


def main():
    if tk is None:
        print(f"Tkinter/Pillow unavailable: {_IMPORT_ERR}"); return
    try:
        root = tk.Tk()
    except Exception as e:
        print(f"No display available to open the Studio window ({e}).\n"
              f"Run on a machine with a desktop, or use the command-line demos in demos/.")
        return
    root.geometry("1180x680"); root.minsize(960, 560)
    Studio(root)
    root.mainloop()


if __name__ == "__main__":
    main()
