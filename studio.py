"""FlowZoo Studio — an interactive, multi-page CFD gallery.

  • Intro   — what FlowZoo is, and who made it.
  • Gallery — browse exhibits; see the method, governing equation and a demo clip.
  • Studio  — tune every parameter (each with a "?"), pick a visualization
              (vorticity / speed / streamlines / …), Run, watch it animate, export.

    python studio.py

Package as a standalone Windows app: see docs/windows_build.md.
"""
from __future__ import annotations

import queue
import sys
import threading
from pathlib import Path

import numpy as np

ROOT = Path(getattr(sys, "_MEIPASS", str(Path(__file__).resolve().parent)))
sys.path.insert(0, str(ROOT))
from flowzoo import engine, render

try:
    import tkinter as tk
    from tkinter import ttk, filedialog, messagebox
    from PIL import Image, ImageTk, ImageSequence
except Exception as e:  # pragma: no cover
    tk = None
    _IMPORT_ERR = e

# ---- curated deep-indigo theme ----
BG = "#0f1426"; BG2 = "#0b1020"; PANEL = "#161d36"; CARD = "#1d2742"; CARD2 = "#27314f"
FG = "#eef2fb"; MUTED = "#8893b2"; ACCENT = "#5b8cff"; ACCENT_D = "#3f6fe0"
GOLD = "#ffc24d"; GOOD = "#54e0a6"; WARN = "#ff8472"
FONT = "Segoe UI"
GROUPS = ["Geometry", "Physics", "Render"]


def slug(s):
    return "".join(c if c.isalnum() else "_" for c in s).strip("_").lower()


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
                 wraplength=320, padx=11, pady=9, relief="solid", bd=1, font=(FONT, 9)).pack()

    def hide(self, _=None):
        if self.tip:
            self.tip.destroy(); self.tip = None


def hover(btn, base, hi):
    btn.bind("<Enter>", lambda e: btn.config(bg=hi))
    btn.bind("<Leave>", lambda e: btn.config(bg=base))


def load_gif(path, maxw=520):
    try:
        im = Image.open(path); frames = []
        for fr in ImageSequence.Iterator(im):
            f = fr.convert("RGB")
            if f.width > maxw:
                f = f.resize((maxw, int(f.height * maxw / f.width)))
            frames.append(ImageTk.PhotoImage(f))
        return frames
    except Exception:
        return []


class App:
    def __init__(self, root):
        self.root = root
        root.title("FlowZoo Studio"); root.configure(bg=BG); root.geometry("1280x780")
        root.minsize(1040, 660)
        self.q = queue.Queue()
        self.frames, self.pidx, self.playing, self.busy = [], 0, False, False
        self.fps = tk.IntVar(value=26); self.widgets = {}
        self.sel = list(engine.EXHIBITS)[0]
        self.gframes, self.gidx, self._eqimg = [], 0, None
        self.result = None; self.view = tk.StringVar(); self.cmap = tk.StringVar()
        self.viewbtns = {}

        st = ttk.Style()
        try: st.theme_use("clam")
        except tk.TclError: pass
        st.configure("TCombobox", fieldbackground=CARD, background=CARD, foreground=FG,
                     arrowcolor=FG, bordercolor=CARD)
        st.map("TCombobox", fieldbackground=[("readonly", CARD)])
        st.configure("A.Horizontal.TProgressbar", background=ACCENT, troughcolor=CARD, borderwidth=0)

        self.container = tk.Frame(root, bg=BG); self.container.pack(fill="both", expand=True)
        self.pages = {}
        self._intro(); self._gallery(); self._studio()
        self.show("intro")
        self.root.after(80, self._poll)
        self.root.after(45, self._tick_studio)
        self.root.after(60, self._tick_gallery)

    def show(self, name):
        for p in self.pages.values():
            p.pack_forget()
        self.pages[name].pack(fill="both", expand=True)
        self.cur = name
        if name == "gallery":
            self._select(self.sel)
        if name == "studio":
            self._build_params()

    # ---------------- intro ----------------
    def _intro(self):
        pg = tk.Frame(self.container, bg=BG); self.pages["intro"] = pg
        cv = tk.Canvas(pg, highlightthickness=0, bg=BG2); cv.pack(fill="both", expand=True)

        def draw(_=None):
            cv.delete("grad")
            w = cv.winfo_width(); h = cv.winfo_height()
            for i in range(0, h, 2):
                t = i / max(1, h)
                r = int(0x0b + t * (0x1c - 0x0b)); g = int(0x10 + t * (0x12 - 0x10))
                b = int(0x20 + t * (0x3a - 0x20))
                cv.create_line(0, i, w, i, fill=f"#{r:02x}{g:02x}{b:02x}", tags="grad")
            cv.tag_lower("grad")
            cv.coords("content", w // 2, h // 2)
        cv.bind("<Configure>", draw)

        box = tk.Frame(cv, bg=BG2)
        cv.create_window(0, 0, window=box, tags="content")
        tk.Label(box, text="🦓", bg=BG2, fg=FG, font=(FONT, 52)).pack()
        t = tk.Frame(box, bg=BG2); t.pack(pady=(2, 0))
        tk.Label(t, text="FlowZoo ", bg=BG2, fg=FG, font=(FONT, 40, "bold")).pack(side="left")
        tk.Label(t, text="Studio", bg=BG2, fg=ACCENT, font=(FONT, 40, "bold")).pack(side="left")
        tk.Label(box, text="a zoo of fluid simulations — five solvers, written from scratch",
                 bg=BG2, fg=GOLD, font=(FONT, 13)).pack(pady=(6, 2))
        tk.Label(box, text="Lattice-Boltzmann · Navier–Stokes · Compressible Euler · SPH · Spectral\n"
                 "Watch vortices, smoke, shockwaves, splashes and turbulence — each validated\n"
                 "against a textbook benchmark. Tune the physics and render your own.",
                 bg=BG2, fg=MUTED, font=(FONT, 11), justify="center").pack(pady=(8, 18))
        go = tk.Button(box, text="Explore the zoo  →", bg=ACCENT, fg="white", relief="flat",
                       bd=0, padx=26, pady=11, font=(FONT, 13, "bold"),
                       activebackground=ACCENT_D, command=lambda: self.show("gallery"))
        go.pack(); hover(go, ACCENT, ACCENT_D)
        tk.Label(box, text="created by", bg=BG2, fg=MUTED, font=(FONT, 9)).pack(pady=(26, 0))
        tk.Label(box, text="Saleh Mohammadrezaei", bg=BG2, fg=FG,
                 font=(FONT, 13, "bold")).pack()
        tk.Label(box, text="salehmrezaee@gmail.com", bg=BG2, fg=ACCENT,
                 font=(FONT, 11)).pack()

    # ---------------- gallery ----------------
    def _gallery(self):
        pg = tk.Frame(self.container, bg=BG); self.pages["gallery"] = pg
        bar = tk.Frame(pg, bg=PANEL, height=52); bar.pack(fill="x"); bar.pack_propagate(False)
        b = tk.Button(bar, text="‹  Home", bg=PANEL, fg=MUTED, relief="flat", bd=0,
                      font=(FONT, 11), activebackground=PANEL, command=lambda: self.show("intro"))
        b.pack(side="left", padx=12)
        tk.Label(bar, text="The exhibits", bg=PANEL, fg=FG,
                 font=(FONT, 15, "bold")).pack(side="left", padx=8)

        body = tk.Frame(pg, bg=BG); body.pack(fill="both", expand=True)
        left = tk.Frame(body, bg=BG, width=290); left.pack(side="left", fill="y", padx=(14, 6), pady=14)
        left.pack_propagate(False)
        self.exh_btns = {}
        for name in engine.EXHIBITS:
            btn = tk.Button(left, text=name, bg=CARD, fg=FG, relief="flat", bd=0, anchor="w",
                            padx=14, pady=11, font=(FONT, 10, "bold"), activebackground=CARD2,
                            command=lambda n=name: self._select(n))
            btn.pack(fill="x", pady=3); hover(btn, CARD, CARD2)
            self.exh_btns[name] = btn

        st = ttk.Style()
        st.configure("TNotebook", background=BG, borderwidth=0)
        st.configure("TNotebook.Tab", background=CARD, foreground=MUTED, padding=(14, 6),
                     font=(FONT, 9, "bold"))
        st.map("TNotebook.Tab", background=[("selected", CARD2)], foreground=[("selected", FG)])

        det = tk.Frame(body, bg=BG); det.pack(side="right", fill="both", expand=True, padx=(6, 14), pady=14)
        self.g_method = tk.Label(det, text="", bg=BG, fg=ACCENT, font=(FONT, 10, "bold"))
        self.g_method.pack(anchor="w")
        self.g_title = tk.Label(det, text="", bg=BG, fg=FG, font=(FONT, 22, "bold"))
        self.g_title.pack(anchor="w", pady=(0, 8))

        nb = ttk.Notebook(det); nb.pack(fill="x")

        def _tab(title):
            fr = tk.Frame(nb, bg=CARD, padx=14, pady=12); nb.add(fr, text=title); return fr
        self.g_blurb = tk.Label(_tab("Overview"), text="", bg=CARD, fg=FG, font=(FONT, 11),
                                justify="left", wraplength=600); self.g_blurb.pack(anchor="w")
        eqtab = _tab("Equation"); self.g_eq = tk.Label(eqtab, bg=CARD); self.g_eq.pack(anchor="w")
        self.g_num = tk.Label(_tab("Numerics"), text="", bg=CARD, fg=FG, font=(FONT, 11),
                              justify="left", wraplength=600); self.g_num.pack(anchor="w")
        self.g_val = tk.Label(_tab("Validation"), text="", bg=CARD, fg=FG, font=(FONT, 11),
                              justify="left", wraplength=600); self.g_val.pack(anchor="w")

        self.g_demo = tk.Label(det, bg="#05070b"); self.g_demo.pack(anchor="w", pady=(12, 0))
        opn = tk.Button(det, text="Customize & run  →", bg=ACCENT, fg="white", relief="flat",
                        bd=0, padx=22, pady=10, font=(FONT, 12, "bold"), activebackground=ACCENT_D,
                        command=lambda: self.show("studio"))
        opn.pack(anchor="w", pady=14); hover(opn, ACCENT, ACCENT_D)

    def _select(self, name):
        self.sel = name
        for n, b in self.exh_btns.items():
            b.config(bg=CARD2 if n == name else CARD, fg=ACCENT if n == name else FG)
        m = engine.META.get(name, {})
        self.g_method.config(text=m.get("method", ""))
        self.g_title.config(text=name.split(" (")[0])
        self.g_blurb.config(text=m.get("blurb", ""))
        self.g_num.config(text=m.get("numerics", ""))
        self.g_val.config(text="✓  " + m.get("validation", ""))
        eqp = ROOT / "docs" / "eq" / (slug(name) + ".png")
        try:
            im = Image.open(eqp)
            w = min(580, im.width); im = im.resize((w, int(im.height * w / im.width)))
            self._eqimg = ImageTk.PhotoImage(im)
            self.g_eq.config(image=self._eqimg, text="")
        except Exception:
            self.g_eq.config(image="", text="(equation image not found)", fg=MUTED, font=(FONT, 11))
        self.gframes = load_gif(ROOT / m.get("demo", ""), maxw=560); self.gidx = 0
        if not self.gframes:
            self.g_demo.config(image="", text="  (demo clip not found — open it in Studio and "
                               "press Run)  ", fg=MUTED, font=(FONT, 11))
        if hasattr(self, "exhibit"):
            self.exhibit.set(name)

    def _tick_gallery(self):
        if getattr(self, "cur", "") == "gallery" and self.gframes:
            self.g_demo.config(image=self.gframes[self.gidx % len(self.gframes)])
            self.gidx += 1
        self.root.after(45, self._tick_gallery)

    # ---------------- studio ----------------
    def _studio(self):
        pg = tk.Frame(self.container, bg=BG); self.pages["studio"] = pg
        bar = tk.Frame(pg, bg=PANEL, height=52); bar.pack(fill="x"); bar.pack_propagate(False)
        b = tk.Button(bar, text="‹  Gallery", bg=PANEL, fg=MUTED, relief="flat", bd=0,
                      font=(FONT, 11), activebackground=PANEL, command=lambda: self.show("gallery"))
        b.pack(side="left", padx=12)
        self.exhibit = tk.StringVar(value=self.sel)
        cb = ttk.Combobox(bar, textvariable=self.exhibit, state="readonly",
                          values=list(engine.EXHIBITS), font=(FONT, 11), width=34)
        cb.pack(side="left", padx=8, pady=10)
        cb.bind("<<ComboboxSelected>>", lambda *_: (setattr(self, "sel", self.exhibit.get()),
                                                    self._build_params()))

        body = tk.Frame(pg, bg=BG); body.pack(fill="both", expand=True)
        side = tk.Frame(body, bg=PANEL, width=348); side.pack(side="left", fill="y")
        side.pack_propagate(False)

        wrap = tk.Frame(side, bg=PANEL); wrap.pack(fill="both", expand=True, padx=(16, 6), pady=12)
        self.cvp = tk.Canvas(wrap, bg=PANEL, highlightthickness=0)
        sb = ttk.Scrollbar(wrap, orient="vertical", command=self.cvp.yview)
        self.inner = tk.Frame(self.cvp, bg=PANEL)
        self.inner.bind("<Configure>", lambda e: self.cvp.configure(scrollregion=self.cvp.bbox("all")))
        self.cvp.create_window((0, 0), window=self.inner, anchor="nw", width=306)
        self.cvp.configure(yscrollcommand=sb.set)
        self.cvp.pack(side="left", fill="both", expand=True); sb.pack(side="right", fill="y")
        self.cvp.bind_all("<MouseWheel>", lambda e: self.cvp.yview_scroll(int(-e.delta / 120), "units")
                          if getattr(self, "cur", "") == "studio" else None)

        bot = tk.Frame(side, bg=PANEL); bot.pack(side="bottom", fill="x", padx=16, pady=(4, 14))
        tk.Label(bot, text="Playback FPS", bg=PANEL, fg=MUTED, font=(FONT, 9)).pack(anchor="w")
        tk.Scale(bot, from_=8, to=40, orient="horizontal", variable=self.fps, bg=PANEL, fg=FG,
                 highlightthickness=0, troughcolor=CARD, bd=0).pack(fill="x")
        self.run_btn = tk.Button(bot, text="▶  Run simulation", command=self.run, bg=ACCENT,
                                 fg="white", relief="flat", pady=10, bd=0, activebackground=ACCENT_D,
                                 font=(FONT, 11, "bold"))
        self.run_btn.pack(fill="x", pady=(10, 6)); hover(self.run_btn, ACCENT, ACCENT_D)
        self.prog = ttk.Progressbar(bot, mode="indeterminate", style="A.Horizontal.TProgressbar")
        sv = tk.Frame(bot, bg=PANEL); sv.pack(fill="x", pady=2)
        for txt, k in (("⬇ GIF", "gif"), ("⬇ MP4", "mp4")):
            sb2 = tk.Button(sv, text=txt, command=lambda k=k: self.save(k), bg=CARD2, fg=FG,
                            relief="flat", bd=0, font=(FONT, 10), activebackground="#33405a")
            sb2.pack(side="left", expand=True, fill="x", padx=2); hover(sb2, CARD2, "#33405a")
        self.status = tk.Label(bot, text="Ready.", bg=PANEL, fg=MUTED, wraplength=300,
                               justify="left", font=(FONT, 9)); self.status.pack(anchor="w", pady=(10, 0))

        prev = tk.Frame(body, bg=BG); prev.pack(side="right", fill="both", expand=True)
        self.viewbar = tk.Frame(prev, bg=BG); self.viewbar.pack(fill="x", padx=10, pady=(10, 0))
        self.canvas = tk.Label(prev, bg="#05070b",
                               text="Set parameters  ›  Run ▶\n(then switch Vorticity / Speed / "
                                    "Streamlines live)", fg=MUTED, font=(FONT, 14))
        self.canvas.pack(expand=True, fill="both", padx=10, pady=10)

    def _build_params(self):
        for w in self.inner.winfo_children():
            w.destroy()
        self.widgets = {}
        params = engine.EXHIBITS[self.sel]["params"]
        groups = {}
        for qd in params:
            groups.setdefault(qd.get("group", "Render"), []).append(qd)
        for gname in GROUPS:
            if gname not in groups:
                continue
            tk.Label(self.inner, text=gname.upper(), bg=PANEL, fg=ACCENT,
                     font=(FONT, 8, "bold")).pack(anchor="w", pady=(12, 2))
            tk.Frame(self.inner, bg=CARD2, height=1).pack(fill="x", pady=(0, 4))
            for qd in groups[gname]:
                self._row(qd)

    def _row(self, qd):
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
            v = tk.StringVar(value=qd["default"] if qd["type"] == "str" else f"{qd['default']:g}")
            tk.Entry(row, textvariable=v, bg=CARD, fg=FG, relief="flat", insertbackground=FG,
                     font=(FONT, 10)).pack(fill="x", pady=(3, 0), ipady=4)
        self.widgets[qd["name"]] = (qd, v)

    def _params(self):
        return {n: (float(v.get()) if qd["type"] == "float" else v.get())
                for n, (qd, v) in self.widgets.items()}

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
        name = self.sel

        self.viewcache = {}

        def work():
            try:
                res = engine.solve_exhibit(name, params, progress=lambda s: self.q.put(("status", s)))
                self.q.put(("solved", res))
                cm = engine.DEFCMAP[res.kind]; cache = {}
                for v in res.views:                       # pre-render EVERY view → instant switching
                    self.q.put(("status", f"rendering {v}…"))
                    cache[v] = res.render(v, cm)
                self.q.put(("cached", (cache, res.views[0], res.info)))
            except Exception as ex:  # pragma: no cover
                self.q.put(("error", str(ex)))
        threading.Thread(target=work, daemon=True).start()

    def _set_views(self, res):
        for w in self.viewbar.winfo_children():
            w.destroy()
        self.viewbtns = {}
        tk.Label(self.viewbar, text="View", bg=BG, fg=MUTED, font=(FONT, 9)).pack(side="left", padx=(0, 4))
        self.view.set(res.views[0])
        for v in res.views:
            b = tk.Button(self.viewbar, text=v, bg=CARD, fg=FG, relief="flat", bd=0, padx=11, pady=5,
                          font=(FONT, 9, "bold"), activebackground=CARD2,
                          command=lambda vv=v: self._change_view(vv))
            b.pack(side="left", padx=2); self.viewbtns[v] = b
        tk.Label(self.viewbar, text="   Palette", bg=BG, fg=MUTED, font=(FONT, 9)).pack(side="left", padx=(8, 4))
        self.cmap.set(engine.DEFCMAP[res.kind])
        cmb = ttk.Combobox(self.viewbar, textvariable=self.cmap, state="readonly",
                           values=list(render.COLORMAPS), width=16, font=(FONT, 9))
        cmb.pack(side="left"); cmb.bind("<<ComboboxSelected>>", lambda *_: self._recolor())
        self.playbtn = tk.Button(self.viewbar, text="⏸ Pause", bg=CARD2, fg=FG, relief="flat", bd=0,
                                 padx=12, pady=5, font=(FONT, 9, "bold"), activebackground="#33405a",
                                 command=self._toggle_play)
        self.playbtn.pack(side="right")
        self._hl_view()

    def _hl_view(self):
        for v, b in self.viewbtns.items():
            on = v == self.view.get()
            b.config(bg=ACCENT if on else CARD, fg="white" if on else FG)

    def _change_view(self, v):
        self.view.set(v); self._hl_view()
        if v in self.viewcache:                  # instant — already rendered
            self.frames = self.viewcache[v]; self.pidx = 0; self.playing = True

    def _toggle_play(self):
        self.playing = not self.playing
        self.playbtn.config(text="⏸ Pause" if self.playing else "▶ Play")

    def _recolor(self):
        """Re-render all views with the newly chosen palette (cached again)."""
        if not self.result or self.busy:
            return
        self.busy = True; self.run_btn.config(state="disabled")
        self.prog.pack(fill="x", pady=(2, 4)); self.prog.start(12)
        res, c = self.result, self.cmap.get()

        def work():
            try:
                cache = {}
                for v in res.views:
                    self.q.put(("status", f"recoloring {v}…")); cache[v] = res.render(v, c)
                self.q.put(("cached", (cache, self.view.get(), res.info)))
            except Exception as ex:  # pragma: no cover
                self.q.put(("error", str(ex)))
        threading.Thread(target=work, daemon=True).start()

    def _poll(self):
        try:
            while True:
                kind, payload = self.q.get_nowait()
                if kind == "status":
                    self.status.config(text="⏳ " + payload, fg=MUTED)
                elif kind == "solved":
                    self.result = payload; self._set_views(payload)
                elif kind == "cached":
                    cache, view, info = payload
                    self.viewcache = cache; self.view.set(view); self._hl_view()
                    self.frames = cache[view]
                    self.pidx, self.playing, self.busy = 0, True, False
                    self.playbtn.config(text="⏸ Pause")
                    self.status.config(text=f"✓ {info}\n{len(cache)} views ready — switch instantly.",
                                       fg=GOOD)
                    self.run_btn.config(state="normal", text="▶  Run simulation")
                    self.prog.stop(); self.prog.pack_forget()
                elif kind == "error":
                    self.busy = False; self.status.config(text=f"⚠ {payload}", fg=WARN)
                    self.run_btn.config(state="normal", text="▶  Run simulation")
                    self.prog.stop(); self.prog.pack_forget()
        except queue.Empty:
            pass
        self.root.after(80, self._poll)

    def _tick_studio(self):
        if getattr(self, "cur", "") == "studio" and self.playing and self.frames:
            arr = self.frames[self.pidx % len(self.frames)]
            cw, ch = max(self.canvas.winfo_width(), 100), max(self.canvas.winfo_height(), 100)
            img = Image.fromarray(arr); sc = min(cw / img.width, ch / img.height)
            img = img.resize((max(1, int(img.width * sc)), max(1, int(img.height * sc))))
            self._photo = ImageTk.PhotoImage(img); self.canvas.config(image=self._photo, text="")
            self.pidx += 1
        self.root.after(int(1000 / max(1, self.fps.get())), self._tick_studio)

    def save(self, kind):
        if not self.frames:
            messagebox.showinfo("FlowZoo", "Run a simulation first."); return
        path = filedialog.asksaveasfilename(defaultextension="." + kind, initialfile="flowzoo." + kind)
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
    App(root); root.mainloop()


if __name__ == "__main__":
    main()
