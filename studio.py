"""FlowZoo Studio — an interactive control panel for the whole gallery.

Pick an exhibit, adjust its parameters (text, Reynolds number, resolution,
duration), hit Run, watch the animation play in the window, then export it as
a GIF or MP4. A single app containing every solver.

    python studio.py

Package as a standalone executable (optional):
    pip install pyinstaller
    pyinstaller --onefile --add-data "solvers:solvers" studio.py
    # the C++ solvers must be compiled for the target OS first (make -C solvers/*)
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


class Studio:
    def __init__(self, root):
        self.root = root
        root.title("FlowZoo Studio")
        root.configure(bg="#11131a")
        self.q = queue.Queue()
        self.frames = []
        self.play_idx = 0
        self.playing = False
        self.fps = tk.IntVar(value=26)
        self.param_vars = {}

        left = tk.Frame(root, bg="#171a23", padx=12, pady=12)
        left.pack(side="left", fill="y")
        tk.Label(left, text="🦓 FlowZoo Studio", bg="#171a23", fg="#e8ecf3",
                 font=("Helvetica", 15, "bold")).pack(anchor="w", pady=(0, 10))

        tk.Label(left, text="Exhibit", bg="#171a23", fg="#9aa3b2").pack(anchor="w")
        self.exhibit = tk.StringVar(value=list(engine.EXHIBITS)[0])
        om = ttk.OptionMenu(left, self.exhibit, self.exhibit.get(),
                            *engine.EXHIBITS, command=lambda *_: self._build_params())
        om.pack(fill="x", pady=(0, 10))

        self.param_frame = tk.Frame(left, bg="#171a23")
        self.param_frame.pack(fill="x")

        tk.Label(left, text="Playback FPS", bg="#171a23", fg="#9aa3b2").pack(anchor="w", pady=(8, 0))
        tk.Scale(left, from_=8, to=40, orient="horizontal", variable=self.fps,
                 bg="#171a23", fg="#e8ecf3", highlightthickness=0).pack(fill="x")

        self.run_btn = tk.Button(left, text="▶  Run simulation", command=self.run,
                                 bg="#2f6df0", fg="white", relief="flat", pady=8,
                                 font=("Helvetica", 11, "bold"))
        self.run_btn.pack(fill="x", pady=(12, 6))
        bf = tk.Frame(left, bg="#171a23"); bf.pack(fill="x")
        tk.Button(bf, text="Save GIF", command=lambda: self.save("gif"),
                  bg="#2a2f3c", fg="#e8ecf3", relief="flat").pack(side="left", expand=True, fill="x", padx=(0, 3))
        tk.Button(bf, text="Save MP4", command=lambda: self.save("mp4"),
                  bg="#2a2f3c", fg="#e8ecf3", relief="flat").pack(side="left", expand=True, fill="x", padx=(3, 0))

        self.status = tk.Label(left, text="Ready.", bg="#171a23", fg="#7f8a9c",
                               wraplength=240, justify="left")
        self.status.pack(anchor="w", pady=(12, 0))

        self.canvas = tk.Label(root, bg="#0a0b12")
        self.canvas.pack(side="right", expand=True, fill="both", padx=6, pady=6)

        self._build_params()
        self.root.after(80, self._poll)
        self.root.after(40, self._tick)

    def _build_params(self):
        for w in self.param_frame.winfo_children():
            w.destroy()
        self.param_vars = {}
        for q in engine.EXHIBITS[self.exhibit.get()]["params"]:
            tk.Label(self.param_frame, text=q["name"], bg="#171a23",
                     fg="#9aa3b2").pack(anchor="w", pady=(6, 0))
            if q["type"] == "choice":
                v = tk.StringVar(value=q["default"])
                ttk.OptionMenu(self.param_frame, v, q["default"], *q["choices"]).pack(fill="x")
            elif q["type"] == "str":
                v = tk.StringVar(value=q["default"])
                tk.Entry(self.param_frame, textvariable=v).pack(fill="x")
            else:  # float
                v = tk.DoubleVar(value=float(q["default"]))
                tk.Scale(self.param_frame, from_=q["min"], to=q["max"], resolution=
                         (0.1 if q["max"] <= 2 else 10), orient="horizontal", variable=v,
                         bg="#171a23", fg="#e8ecf3", highlightthickness=0).pack(fill="x")
            self.param_vars[q["name"]] = v

    def run(self):
        if self.run_btn["state"] == "disabled":
            return
        self.run_btn.config(state="disabled", text="Running…")
        self.playing = False
        params = {k: v.get() for k, v in self.param_vars.items()}
        name = self.exhibit.get()

        def work():
            try:
                frames, info = engine.run_exhibit(name, params,
                                                  progress=lambda s: self.q.put(("status", s)))
                self.q.put(("done", (frames, info)))
            except Exception as ex:  # pragma: no cover
                self.q.put(("error", str(ex)))

        threading.Thread(target=work, daemon=True).start()

    def _poll(self):
        try:
            while True:
                kind, payload = self.q.get_nowait()
                if kind == "status":
                    self.status.config(text=payload)
                elif kind == "done":
                    self.frames, info = payload
                    self.play_idx = 0; self.playing = True
                    self.status.config(text=f"Done — {info}\n{len(self.frames)} frames. Playing.")
                    self.run_btn.config(state="normal", text="▶  Run simulation")
                elif kind == "error":
                    self.status.config(text=f"Error: {payload}")
                    self.run_btn.config(state="normal", text="▶  Run simulation")
        except queue.Empty:
            pass
        self.root.after(80, self._poll)

    def _tick(self):
        if self.playing and self.frames:
            arr = self.frames[self.play_idx % len(self.frames)]
            cw = max(self.canvas.winfo_width(), 100)
            ch = max(self.canvas.winfo_height(), 100)
            img = Image.fromarray(arr)
            scale = min(cw / img.width, ch / img.height)
            img = img.resize((max(1, int(img.width * scale)), max(1, int(img.height * scale))))
            self._photo = ImageTk.PhotoImage(img)
            self.canvas.config(image=self._photo)
            self.play_idx += 1
        self.root.after(int(1000 / max(1, self.fps.get())), self._tick)

    def save(self, kind):
        if not self.frames:
            messagebox.showinfo("FlowZoo", "Run a simulation first."); return
        ext = ".gif" if kind == "gif" else ".mp4"
        path = filedialog.asksaveasfilename(defaultextension=ext,
                                            initialfile=f"flowzoo{ext}")
        if not path:
            return
        (render.save_gif if kind == "gif" else render.save_mp4)(self.frames, path, fps=self.fps.get())
        self.status.config(text=f"Saved {path}")


def main():
    if tk is None:
        print(f"Tkinter/Pillow unavailable: {_IMPORT_ERR}")
        return
    try:
        root = tk.Tk()
    except Exception as e:
        print(f"No display available to open the Studio window ({e}).\n"
              f"Run on a machine with a desktop, or use the command-line demos in demos/.")
        return
    root.geometry("1100x620")
    Studio(root)
    root.mainloop()


if __name__ == "__main__":
    main()
