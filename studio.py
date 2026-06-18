"""FlowZoo Studio — interactive control panel for the whole gallery.

Pick an exhibit, tune every parameter (each with a "?" explaining what it does),
choose a palette / resolution / duration, Run, watch it animate live, export a
GIF or MP4. One app containing every solver.

    python studio.py

Package as a standalone Windows app: see docs/windows_build.md.
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

# ---- modern dark palette ----
BG = "#0c0e14"; PANEL = "#141822"; CARD = "#1d2330"; CARD2 = "#262d3d"
FG = "#eef2f8"; MUTED = "#7e8aa0"; ACCENT = "#4f8cff"; ACCENT_D = "#3a6fd8"
GOOD = "#46d39a"; WARN = "#ff7a6b"
FONT = "Segoe UI"   # native on Windows; falls back elsewhere
GROUP_ORDER = ["Geometry", "Physics", "Render"]


class Tooltip:
    def __init__(self, w, text):
        self.w, self.text, self.tip = w, text, None
        w.bind("<Enter>", self.show); w.bind("<Leave>", self.hide)

    def show(self, _=None):
        if self.tip or not self.text:
            return
        self.tip = tk.Toplevel(self.w); self.tip.wm_overrideredirect(True)
        self.tip.wm_geometry(f"+{self.w.winfo_rootx()+22}+{self.w.winfo_rooty()+18}")
        tk.Label(self.tip, text=self.text, bg="#05070d", fg=FG, justify="left",
                 wraplength=300, padx=11, pady=9, relief="solid", bd=1,
                 font=(FONT, 9)).pack()

    def hide(self, _=None):
        if self.tip:
            self.tip.destroy(); self.tip = None


def _hoverable(btn, base, hover):
    btn.bind("<Enter>", lambda e: btn.config(bg=hover))
    btn.bind("<Leave>", lambda e: btn.config(bg=base))


class Studio:
    def __init__(self, root):
        self.root = root
        root.title("FlowZoo Studio"); root.configure(bg=BG)
        self.q = queue.Queue()
        self.frames, self.play_idx, self.playing, self.busy = [], 0, False, False
        self.fps = tk.IntVar(value=26); self.widgets = {}

        st = ttk.Style()
        try: st.theme_use("clam")
        except tk.TclError: pass
        st.configure("TCombobox", fieldbackground=CARD, background=CARD, foreground=FG,
                     arrowcolor=FG, bordercolor=CARD, lightcolor=CARD, darkcolor=CARD)
        st.map("TCombobox", fieldbackground=[("readonly", CARD)])
        st.configure("A.Horizontal.TProgressbar", background=ACCENT, troughcolor=CARD,
                     borderwidth=0)

        # ---- header band ----
        head = tk.Frame(root, bg=PANEL, height=64); head.pack(side="top", fill="x")
        head.pack_propagate(False)
        tk.Frame(root, bg=ACCENT, height=2).pack(side="top", fill="x")
        tk.Label(head, text="🦓  FlowZoo", bg=PANEL, fg=FG,
                 font=(FONT, 20, "bold")).pack(side="left", padx=(18, 8), pady=10)
        tk.Label(head, text="Studio", bg=PANEL, fg=ACCENT,
                 font=(FONT, 20, "bold")).pack(side="left", pady=10)
        tk.Label(head, text="a zoo of fluid simulations — solve · tune · render",
                 bg=PANEL, fg=MUTED, font=(FONT, 10)).pack(side="left", padx=14)

        body = tk.Frame(root, bg=BG); body.pack(fill="both", expand=True)

        # ---- sidebar ----
        side = tk.Frame(body, bg=PANEL, width=342); side.pack(side="left", fill="y")
        side.pack_propagate(False)

        tk.Label(side, text="EXHIBIT", bg=PANEL, fg=MUTED,
                 font=(FONT, 8, "bold")).pack(anchor="w", padx=16, pady=(14, 2))
        self.exhibit = tk.StringVar(value=list(engine.EXHIBITS)[0])
        cb = ttk.Combobox(side, textvariable=self.exhibit, state="readonly",
                          values=list(engine.EXHIBITS), font=(FONT, 10))
        cb.pack(fill="x", padx=16); cb.bind("<<ComboboxSelected>>", lambda *_: self._build())

        # scrollable parameter area
        wrap = tk.Frame(side, bg=PANEL); wrap.pack(fill="both", expand=True, padx=(16, 6), pady=10)
        self.cv = tk.Canvas(wrap, bg=PANEL, highlightthickness=0)
        sb = ttk.Scrollbar(wrap, orient="vertical", command=self.cv.yview)
        self.inner = tk.Frame(self.cv, bg=PANEL)
        self.inner.bind("<Configure>", lambda e: self.cv.configure(scrollregion=self.cv.bbox("all")))
        self.cv.create_window((0, 0), window=self.inner, anchor="nw", width=300)
        self.cv.configure(yscrollcommand=sb.set)
        self.cv.pack(side="left", fill="both", expand=True); sb.pack(side="right", fill="y")
        self.cv.bind_all("<MouseWheel>", lambda e: self.cv.yview_scroll(int(-e.delta / 120), "units"))
        self.cv.bind_all("<Button-4>", lambda e: self.cv.yview_scroll(-1, "units"))
        self.cv.bind_all("<Button-5>", lambda e: self.cv.yview_scroll(1, "units"))

        # bottom controls
        bot = tk.Frame(side, bg=PANEL); bot.pack(side="bottom", fill="x", padx=16, pady=(4, 14))
        fr = tk.Frame(bot, bg=PANEL); fr.pack(fill="x")
        tk.Label(fr, text="Playback FPS", bg=PANEL, fg=MUTED, font=(FONT, 9)).pack(side="left")
        tk.Scale(bot, from_=8, to=40, orient="horizontal", variable=self.fps, bg=PANEL,
                 fg=FG, highlightthickness=0, troughcolor=CARD, bd=0).pack(fill="x")
        self.run_btn = tk.Button(bot, text="▶  Run simulation", command=self.run, bg=ACCENT,
                                 fg="white", relief="flat", pady=10, bd=0,
                                 activebackground=ACCENT_D, font=(FONT, 11, "bold"))
        self.run_btn.pack(fill="x", pady=(10, 6)); _hoverable(self.run_btn, ACCENT, ACCENT_D)
        self.prog = ttk.Progressbar(bot, mode="indeterminate", style="A.Horizontal.TProgressbar")
        sv = tk.Frame(bot, bg=PANEL); sv.pack(fill="x", pady=2)
        for txt, k in (("⬇ GIF", "gif"), ("⬇ MP4", "mp4")):
            b = tk.Button(sv, text=txt, command=lambda k=k: self.save(k), bg=CARD2, fg=FG,
                          relief="flat", bd=0, activebackground="#33405a", font=(FONT, 10))
            b.pack(side="left", expand=True, fill="x", padx=2); _hoverable(b, CARD2, "#33405a")
        self.status = tk.Label(bot, text="Ready.", bg=PANEL, fg=MUTED, wraplength=300,
                               justify="left", font=(FONT, 9)); self.status.pack(anchor="w", pady=(10, 0))

        # ---- preview ----
        prev = tk.Frame(body, bg=BG); prev.pack(side="right", expand=True, fill="both")
        self.canvas = tk.Label(prev, bg="#05070b", text="Pick an exhibit  ›  press  Run ▶",
                               fg=MUTED, font=(FONT, 14)); self.canvas.pack(expand=True, fill="both",
                                                                            padx=10, pady=10)
        tk.Label(prev, text="FlowZoo · built by Saleh Rezaee", bg=BG, fg=MUTED,
                 font=(FONT, 8)).pack(side="bottom", anchor="e", padx=14, pady=(0, 6))

        self._build(); self.root.after(80, self._poll); self.root.after(40, self._tick)

    def _build(self):
        for w in self.inner.winfo_children():
            w.destroy()
        self.widgets = {}
        params = engine.EXHIBITS[self.exhibit.get()]["params"]
        groups = {}
        for qd in params:
            groups.setdefault(qd.get("group", "Render"), []).append(qd)
        for gname in GROUP_ORDER:
            if gname not in groups:
                continue
            tk.Label(self.inner, text=gname.upper(), bg=PANEL, fg=ACCENT,
                     font=(FONT, 8, "bold")).pack(anchor="w", pady=(12, 2))
            tk.Frame(self.inner, bg=CARD2, height=1).pack(fill="x", pady=(0, 4))
            for qd in groups[gname]:
                self._param_row(qd)

    def _param_row(self, qd):
        row = tk.Frame(self.inner, bg=PANEL); row.pack(fill="x", pady=(6, 0))
        head = tk.Frame(row, bg=PANEL); head.pack(fill="x")
        lab = qd.get("label", qd["name"])
        if qd["type"] == "float":
            lab += f"   {qd['min']:g}–{qd['max']:g}"
        tk.Label(head, text=lab, bg=PANEL, fg=FG, font=(FONT, 9, "bold")).pack(side="left")
        if qd.get("help"):
            chip = tk.Label(head, text=" ? ", bg=CARD2, fg=ACCENT, font=(FONT, 8, "bold"),
                            cursor="question_arrow"); chip.pack(side="right")
            Tooltip(chip, qd["help"])
            chip.bind("<Button-1>", lambda e, t=qd["help"], n=lab: messagebox.showinfo(n, t))
        if qd["type"] == "choice":
            v = tk.StringVar(value=qd["default"])
            ttk.Combobox(row, textvariable=v, state="readonly", values=qd["choices"],
                         font=(FONT, 10)).pack(fill="x", pady=(3, 0))
        else:
            default = qd["default"] if qd["type"] == "str" else f"{qd['default']:g}"
            v = tk.StringVar(value=default)
            tk.Entry(row, textvariable=v, bg=CARD, fg=FG, relief="flat", insertbackground=FG,
                     font=(FONT, 10)).pack(fill="x", pady=(3, 0), ipady=4)
        self.widgets[qd["name"]] = (qd, v)

    def _params(self):
        out = {}
        for name, (qd, v) in self.widgets.items():
            out[name] = float(v.get()) if qd["type"] == "float" else v.get()
        return out

    def run(self):
        if self.busy:
            return
        try:
            params = self._params()
        except ValueError:
            self.status.config(text="A numeric field has an invalid value.", fg=WARN); return
        self.busy = True; self.playing = False
        self.run_btn.config(state="disabled", text="● Simulating…")
        self.prog.pack(fill="x", pady=(2, 4)); self.prog.start(12)
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
                    self.status.config(text="⏳ " + payload, fg=MUTED)
                elif kind == "done":
                    self.frames, info = payload
                    self.play_idx, self.playing, self.busy = 0, True, False
                    self.status.config(text=f"✓ {info}\n{len(self.frames)} frames — playing.", fg=GOOD)
                    self.run_btn.config(state="normal", text="▶  Run simulation")
                    self.prog.stop(); self.prog.pack_forget()
                elif kind == "error":
                    self.busy = False
                    self.status.config(text=f"⚠ {payload}", fg=WARN)
                    self.run_btn.config(state="normal", text="▶  Run simulation")
                    self.prog.stop(); self.prog.pack_forget()
        except queue.Empty:
            pass
        self.root.after(80, self._poll)

    def _tick(self):
        if self.playing and self.frames:
            arr = self.frames[self.play_idx % len(self.frames)]
            cw, ch = max(self.canvas.winfo_width(), 100), max(self.canvas.winfo_height(), 100)
            img = Image.fromarray(arr); sc = min(cw / img.width, ch / img.height)
            img = img.resize((max(1, int(img.width * sc)), max(1, int(img.height * sc))))
            self._photo = ImageTk.PhotoImage(img)
            self.canvas.config(image=self._photo, text=""); self.play_idx += 1
        self.root.after(int(1000 / max(1, self.fps.get())), self._tick)

    def save(self, kind):
        if not self.frames:
            messagebox.showinfo("FlowZoo", "Run a simulation first."); return
        path = filedialog.asksaveasfilename(defaultextension="." + kind,
                                            initialfile="flowzoo." + kind)
        if not path:
            return
        try:
            (render.save_gif if kind == "gif" else render.save_mp4)(self.frames, path, fps=self.fps.get())
            self.status.config(text=f"✓ Saved {path}", fg=GOOD)
        except Exception as ex:
            messagebox.showerror("Export failed",
                                 f"{ex}\n\nGIF/MP4 export needs ffmpeg (see docs/windows_build.md).")


def main():
    if tk is None:
        print(f"Tkinter/Pillow unavailable: {_IMPORT_ERR}"); return
    try:
        root = tk.Tk()
    except Exception as e:
        print(f"No display to open the Studio ({e}).\nRun on a desktop, or use demos/.")
        return
    root.geometry("1240x720"); root.minsize(1000, 600)
    Studio(root); root.mainloop()


if __name__ == "__main__":
    main()
