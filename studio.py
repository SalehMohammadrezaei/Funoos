"""FlowZoo Studio — a modern, multi-page CFD gallery (CustomTkinter UI).

  • Intro   — what FlowZoo is, and who made it.
  • Gallery — browse exhibits; in-depth physics, the governing equation, a demo.
  • Studio  — tune every parameter, Run once, then switch visualization
              (vorticity / speed / streamlines / …) live, with play/pause + export.

    pip install customtkinter pillow
    python studio.py

Package as a standalone Windows app: see docs/windows_build.md.
"""
from __future__ import annotations

import queue
import sys
import threading
from pathlib import Path

ROOT = Path(getattr(sys, "_MEIPASS", str(Path(__file__).resolve().parent)))
sys.path.insert(0, str(ROOT))
from flowzoo import engine, render, content

try:
    import tkinter as tk
    import customtkinter as ctk
    from PIL import Image, ImageTk, ImageSequence
    from tkinter import filedialog, messagebox
except Exception as e:  # pragma: no cover
    ctk = None
    _IMPORT_ERR = e

# ---- modern deep-indigo palette ----
BG = "#0e1322"; PANEL = "#161d31"; CARD = "#1c2740"; CARD2 = "#28344f"
FG = "#eef2fb"; MUTED = "#8a96b4"; ACCENT = "#5b8cff"; ACCENT_D = "#3f6fe0"
GOLD = "#ffc24d"; GOOD = "#46d39a"; WARN = "#ff7a6b"; INKCV = "#05070b"
F = "Segoe UI"


def slug(s):
    return "".join(c if c.isalnum() else "_" for c in s).strip("_").lower()


def load_gif(path, maxw=420):
    try:
        im = Image.open(path); out = []
        for fr in ImageSequence.Iterator(im):
            f = fr.convert("RGB")
            if f.width > maxw:
                f = f.resize((maxw, int(f.height * maxw / f.width)))
            out.append(ImageTk.PhotoImage(f))
        return out
    except Exception:
        return []


class Tooltip:
    def __init__(self, w, text):
        self.w, self.text, self.tip = w, text, None
        w.bind("<Enter>", self.show); w.bind("<Leave>", self.hide)

    def show(self, _=None):
        if self.tip or not self.text:
            return
        self.tip = tk.Toplevel(self.w); self.tip.wm_overrideredirect(True)
        self.tip.wm_geometry(f"+{self.w.winfo_rootx()+22}+{self.w.winfo_rooty()+20}")
        tk.Label(self.tip, text=self.text, bg="#05070d", fg=FG, justify="left",
                 wraplength=320, padx=11, pady=9, relief="solid", bd=1, font=(F, 9)).pack()

    def hide(self, _=None):
        if self.tip:
            self.tip.destroy(); self.tip = None


class App:
    def __init__(self, root):
        self.root = root
        root.title("FlowZoo Studio"); root.geometry("1320x820"); root.minsize(1080, 680)
        root.configure(fg_color=BG)
        self.q = queue.Queue()
        self.frames, self.pidx, self.playing, self.busy = [], 0, False, False
        self.fps = tk.IntVar(value=26)
        self.sel = list(engine.EXHIBITS)[0]
        self.gframes, self.gidx, self._eqimg = [], 0, None
        self.result = None; self.view = tk.StringVar(); self.cmap = tk.StringVar()
        self.viewbtns = {}; self.widgets = {}; self.cur = ""; self.viewcache = {}

        self.pages = {}
        self._intro(); self._gallery(); self._studio()
        self.show("intro")
        root.after(80, self._poll); root.after(45, self._tick_studio); root.after(60, self._tick_gallery)

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
        pg = ctk.CTkFrame(self.root, fg_color=BG, corner_radius=0); self.pages["intro"] = pg
        card = ctk.CTkFrame(pg, fg_color=PANEL, corner_radius=24, width=720, height=560)
        card.place(relx=0.5, rely=0.5, anchor="center")
        ctk.CTkLabel(card, text="🦓", font=(F, 64)).pack(pady=(46, 0))
        ctk.CTkLabel(card, text="FlowZoo Studio", font=(F, 46, "bold"),
                     text_color=FG).pack(pady=(2, 0))
        ctk.CTkLabel(card, text="a zoo of fluid simulations — five solvers, written from scratch",
                     font=(F, 15), text_color=GOLD).pack(pady=(8, 4))
        ctk.CTkLabel(card, text="Lattice-Boltzmann · Navier–Stokes · Compressible Euler · SPH · "
                     "Spectral\nWatch vortices, smoke, shockwaves, splashes and turbulence —\n"
                     "each validated against a textbook benchmark.",
                     font=(F, 12), text_color=MUTED, justify="center").pack(pady=(8, 22))
        ctk.CTkButton(card, text="Explore the zoo  →", font=(F, 15, "bold"), width=240, height=46,
                      corner_radius=23, fg_color=ACCENT, hover_color=ACCENT_D,
                      command=lambda: self.show("gallery")).pack()
        ctk.CTkLabel(card, text="created by", font=(F, 10), text_color=MUTED).pack(pady=(34, 0))
        ctk.CTkLabel(card, text="Saleh Mohammadrezaei", font=(F, 15, "bold"), text_color=FG).pack()
        ctk.CTkLabel(card, text="salehmrezaee@gmail.com", font=(F, 12), text_color=ACCENT).pack()

    # ---------------- gallery ----------------
    def _gallery(self):
        pg = ctk.CTkFrame(self.root, fg_color=BG, corner_radius=0); self.pages["gallery"] = pg
        bar = ctk.CTkFrame(pg, fg_color=PANEL, corner_radius=0, height=58); bar.pack(fill="x")
        ctk.CTkButton(bar, text="‹  Home", width=80, fg_color="transparent", hover_color=CARD,
                      text_color=MUTED, font=(F, 12), command=lambda: self.show("intro")).pack(side="left", padx=10, pady=10)
        ctk.CTkLabel(bar, text="The exhibits", font=(F, 16, "bold"), text_color=FG).pack(side="left", padx=4)

        body = ctk.CTkFrame(pg, fg_color=BG, corner_radius=0); body.pack(fill="both", expand=True, padx=14, pady=14)
        listfr = ctk.CTkFrame(body, fg_color=BG, width=270, corner_radius=0)
        listfr.pack(side="left", fill="y"); listfr.pack_propagate(False)
        self.exh_btns = {}
        for name in engine.EXHIBITS:
            b = ctk.CTkButton(listfr, text=name, anchor="w", height=46, corner_radius=12,
                              fg_color=CARD, hover_color=CARD2, text_color=FG, font=(F, 12, "bold"),
                              command=lambda n=name: self._select(n))
            b.pack(fill="x", pady=4); self.exh_btns[name] = b

        det = ctk.CTkFrame(body, fg_color=BG, corner_radius=0); det.pack(side="left", fill="both", expand=True, padx=(14, 0))
        self.g_method = ctk.CTkLabel(det, text="", font=(F, 11, "bold"), text_color=ACCENT, anchor="w")
        self.g_method.pack(fill="x")
        self.g_title = ctk.CTkLabel(det, text="", font=(F, 26, "bold"), text_color=FG, anchor="w")
        self.g_title.pack(fill="x", pady=(0, 8))

        split = ctk.CTkFrame(det, fg_color=BG, corner_radius=0); split.pack(fill="both", expand=True)
        media = ctk.CTkFrame(split, fg_color=BG, width=440, corner_radius=0)
        media.pack(side="right", fill="y", padx=(16, 0)); media.pack_propagate(False)
        self.g_demo = tk.Label(media, bg=INKCV); self.g_demo.pack(pady=(4, 12))
        ctk.CTkButton(media, text="Customize & run  →", font=(F, 14, "bold"), height=48,
                      corner_radius=14, fg_color=ACCENT, hover_color=ACCENT_D,
                      command=lambda: self.show("studio")).pack(fill="x")
        self.read = ctk.CTkScrollableFrame(split, fg_color=PANEL, corner_radius=16)
        self.read.pack(side="left", fill="both", expand=True)

    def _section(self, header, body):
        ctk.CTkLabel(self.read, text=header, font=(F, 13, "bold"), text_color=ACCENT,
                     anchor="w").pack(fill="x", pady=(14, 2), padx=4)
        ctk.CTkFrame(self.read, fg_color=CARD2, height=1).pack(fill="x", pady=(0, 6), padx=4)
        ctk.CTkLabel(self.read, text=body, font=(F, 12), text_color="#cdd5e6", justify="left",
                     anchor="w", wraplength=560).pack(fill="x", padx=4)

    def _select(self, name):
        self.sel = name
        for n, b in self.exh_btns.items():
            b.configure(fg_color=ACCENT if n == name else CARD,
                        text_color="white" if n == name else FG)
        m = engine.META.get(name, {}); d = content.DETAIL.get(name, {})
        self.g_method.configure(text=m.get("method", ""))
        self.g_title.configure(text=name.split(" (")[0])
        for w in self.read.winfo_children():
            w.destroy()
        self._section("What you're seeing", d.get("physics", m.get("blurb", "")))
        ctk.CTkLabel(self.read, text="Governing equation", font=(F, 13, "bold"), text_color=ACCENT,
                     anchor="w").pack(fill="x", pady=(16, 2), padx=4)
        ctk.CTkFrame(self.read, fg_color=CARD2, height=1).pack(fill="x", pady=(0, 8), padx=4)
        try:
            im = Image.open(ROOT / "docs" / "eq" / (slug(name) + ".png"))
            w = min(560, im.width); im = im.resize((w, int(im.height * w / im.width)))
            self._eqimg = ctk.CTkImage(light_image=im, dark_image=im, size=(w, int(im.height * w / im.width)))
            ctk.CTkLabel(self.read, image=self._eqimg, text="").pack(anchor="w", padx=4)
        except Exception:
            ctk.CTkLabel(self.read, text="(equation image not found)", text_color=MUTED,
                         font=(F, 10)).pack(anchor="w", padx=4)
        if d.get("terms"):
            ctk.CTkLabel(self.read, text=d["terms"], font=(F, 11), text_color="#cdd5e6",
                         justify="left", anchor="w", wraplength=560).pack(fill="x", padx=4, pady=(6, 0))
        self._section("How it's solved", m.get("numerics", ""))
        self._section("Validation", "✓  " + m.get("validation", ""))

        self.gframes = load_gif(ROOT / m.get("demo", ""), maxw=420); self.gidx = 0
        if not self.gframes:
            self.g_demo.config(image="", text="\n demo clip not found —\n open in Studio and Run\n",
                               fg=MUTED, font=(F, 11))
        self.view_exhibit = name

    def _tick_gallery(self):
        if self.cur == "gallery" and self.gframes:
            self.g_demo.config(image=self.gframes[self.gidx % len(self.gframes)]); self.gidx += 1
        self.root.after(45, self._tick_gallery)

    # ---------------- studio ----------------
    def _studio(self):
        pg = ctk.CTkFrame(self.root, fg_color=BG, corner_radius=0); self.pages["studio"] = pg
        bar = ctk.CTkFrame(pg, fg_color=PANEL, corner_radius=0, height=58); bar.pack(fill="x")
        ctk.CTkButton(bar, text="‹  Gallery", width=96, fg_color="transparent", hover_color=CARD,
                      text_color=MUTED, font=(F, 12), command=lambda: self.show("gallery")).pack(side="left", padx=10, pady=10)
        self.exhibit = ctk.CTkOptionMenu(bar, values=list(engine.EXHIBITS), width=300, font=(F, 12),
                                         fg_color=CARD, button_color=CARD2, button_hover_color=ACCENT,
                                         command=self._pick_exhibit)
        self.exhibit.set(self.sel); self.exhibit.pack(side="left", padx=6)

        body = ctk.CTkFrame(pg, fg_color=BG, corner_radius=0); body.pack(fill="both", expand=True, padx=14, pady=14)
        side = ctk.CTkFrame(body, fg_color=PANEL, width=350, corner_radius=16)
        side.pack(side="left", fill="y"); side.pack_propagate(False)
        self.pscroll = ctk.CTkScrollableFrame(side, fg_color=PANEL, corner_radius=0)
        self.pscroll.pack(fill="both", expand=True, padx=6, pady=(8, 4))

        bot = ctk.CTkFrame(side, fg_color=PANEL, corner_radius=0); bot.pack(fill="x", padx=14, pady=(0, 12))
        ctk.CTkLabel(bot, text="Playback FPS", text_color=MUTED, font=(F, 10), anchor="w").pack(fill="x")
        ctk.CTkSlider(bot, from_=8, to=40, variable=self.fps, progress_color=ACCENT).pack(fill="x", pady=(2, 8))
        self.run_btn = ctk.CTkButton(bot, text="▶  Run simulation", font=(F, 13, "bold"), height=46,
                                     corner_radius=14, fg_color=ACCENT, hover_color=ACCENT_D, command=self.run)
        self.run_btn.pack(fill="x")
        self.prog = ctk.CTkProgressBar(bot, mode="indeterminate", progress_color=ACCENT)
        sv = ctk.CTkFrame(bot, fg_color=PANEL); sv.pack(fill="x", pady=(8, 0))
        ctk.CTkButton(sv, text="⬇ GIF", width=10, fg_color=CARD2, hover_color="#34415d", font=(F, 11),
                      command=lambda: self.save("gif")).pack(side="left", expand=True, fill="x", padx=(0, 4))
        ctk.CTkButton(sv, text="⬇ MP4", width=10, fg_color=CARD2, hover_color="#34415d", font=(F, 11),
                      command=lambda: self.save("mp4")).pack(side="left", expand=True, fill="x")
        self.status = ctk.CTkLabel(bot, text="Ready.", text_color=MUTED, font=(F, 10), anchor="w",
                                   justify="left", wraplength=300); self.status.pack(fill="x", pady=(10, 0))

        prev = ctk.CTkFrame(body, fg_color=BG, corner_radius=0); prev.pack(side="left", fill="both", expand=True, padx=(14, 0))
        self.viewbar = ctk.CTkFrame(prev, fg_color=BG, corner_radius=0); self.viewbar.pack(fill="x", pady=(0, 8))
        self.canvas = tk.Label(prev, bg=INKCV, fg=MUTED, font=(F, 14),
                               text="Set parameters  ›  Run ▶\nthen switch views live")
        self.canvas.pack(fill="both", expand=True)

    def _pick_exhibit(self, name):
        self.sel = name; self._build_params()
        self.result = None; self.viewcache = {}
        for w in self.viewbar.winfo_children():
            w.destroy()

    def _build_params(self):
        for w in self.pscroll.winfo_children():
            w.destroy()
        self.widgets = {}
        params = engine.EXHIBITS[self.sel]["params"]
        groups = {}
        for qd in params:
            groups.setdefault(qd.get("group", "Render"), []).append(qd)
        for g in ["Geometry", "Physics", "Render"]:
            if g not in groups:
                continue
            ctk.CTkLabel(self.pscroll, text=g.upper(), font=(F, 10, "bold"), text_color=ACCENT,
                         anchor="w").pack(fill="x", pady=(12, 2))
            ctk.CTkFrame(self.pscroll, fg_color=CARD2, height=1).pack(fill="x", pady=(0, 4))
            for qd in groups[g]:
                self._row(qd)

    def _row(self, qd):
        row = ctk.CTkFrame(self.pscroll, fg_color=PANEL); row.pack(fill="x", pady=(6, 0))
        head = ctk.CTkFrame(row, fg_color=PANEL); head.pack(fill="x")
        lab = qd.get("label", qd["name"])
        if qd["type"] == "float":
            lab += f"   {qd['min']:g}–{qd['max']:g}"
        ctk.CTkLabel(head, text=lab, font=(F, 11, "bold"), text_color=FG, anchor="w").pack(side="left")
        if qd.get("help"):
            chip = ctk.CTkLabel(head, text=" ? ", font=(F, 10, "bold"), text_color=ACCENT,
                                fg_color=CARD2, corner_radius=8); chip.pack(side="right")
            Tooltip(chip, qd["help"])
            chip.bind("<Button-1>", lambda e, t=qd["help"], n=lab: messagebox.showinfo(n, t))
        if qd["type"] == "choice":
            v = tk.StringVar(value=qd["default"])
            ctk.CTkOptionMenu(row, values=qd["choices"], variable=v, font=(F, 11), fg_color=CARD,
                              button_color=CARD2, button_hover_color=ACCENT).pack(fill="x", pady=(3, 0))
        else:
            v = tk.StringVar(value=qd["default"] if qd["type"] == "str" else f"{qd['default']:g}")
            ctk.CTkEntry(row, textvariable=v, font=(F, 11), fg_color=CARD,
                         border_color=CARD2).pack(fill="x", pady=(3, 0))
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
            self.status.configure(text="A numeric field has an invalid value.", text_color=WARN); return
        self.busy = True; self.playing = False; self.viewcache = {}
        self.run_btn.configure(state="disabled", text="● Simulating…")
        self.prog.pack(fill="x", pady=(8, 0)); self.prog.start()
        name = self.sel

        def work():
            try:
                res = engine.solve_exhibit(name, params, progress=lambda s: self.q.put(("status", s)))
                self.q.put(("solved", res))
                cm = engine.DEFCMAP[res.kind]; cache = {}
                for v in res.views:
                    self.q.put(("status", f"rendering {v}…")); cache[v] = res.render(v, cm)
                self.q.put(("cached", (cache, res.views[0], res.info)))
            except Exception as ex:  # pragma: no cover
                self.q.put(("error", str(ex)))
        threading.Thread(target=work, daemon=True).start()

    def _set_views(self, res):
        for w in self.viewbar.winfo_children():
            w.destroy()
        self.viewbtns = {}
        ctk.CTkLabel(self.viewbar, text="View", text_color=MUTED, font=(F, 10)).pack(side="left", padx=(2, 6))
        self.view.set(res.views[0])
        for v in res.views:
            b = ctk.CTkButton(self.viewbar, text=v, width=10, height=30, corner_radius=10, font=(F, 11, "bold"),
                              fg_color=CARD, hover_color=CARD2, command=lambda vv=v: self._change_view(vv))
            b.pack(side="left", padx=2); self.viewbtns[v] = b
        ctk.CTkLabel(self.viewbar, text="  Palette", text_color=MUTED, font=(F, 10)).pack(side="left", padx=(8, 4))
        self.cmap.set(engine.DEFCMAP[res.kind])
        ctk.CTkOptionMenu(self.viewbar, values=list(render.COLORMAPS), variable=self.cmap, width=150,
                          font=(F, 11), fg_color=CARD, button_color=CARD2, button_hover_color=ACCENT,
                          command=lambda *_: self._recolor()).pack(side="left")
        self.playbtn = ctk.CTkButton(self.viewbar, text="⏸ Pause", width=90, height=30, corner_radius=10,
                                     font=(F, 11, "bold"), fg_color=CARD2, hover_color="#34415d",
                                     command=self._toggle_play); self.playbtn.pack(side="right")
        self._hl_view()

    def _hl_view(self):
        for v, b in self.viewbtns.items():
            b.configure(fg_color=ACCENT if v == self.view.get() else CARD)

    def _change_view(self, v):
        self.view.set(v); self._hl_view()
        if v in self.viewcache:
            self.frames = self.viewcache[v]; self.pidx = 0; self.playing = True

    def _toggle_play(self):
        self.playing = not self.playing
        self.playbtn.configure(text="⏸ Pause" if self.playing else "▶ Play")

    def _recolor(self):
        if not self.result or self.busy:
            return
        self.busy = True; self.run_btn.configure(state="disabled")
        self.prog.pack(fill="x", pady=(8, 0)); self.prog.start()
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
                    self.status.configure(text="⏳ " + payload, text_color=MUTED)
                elif kind == "solved":
                    self.result = payload; self._set_views(payload)
                elif kind == "cached":
                    cache, view, info = payload
                    self.viewcache = cache; self.view.set(view); self._hl_view()
                    self.frames = cache[view]
                    self.pidx, self.playing, self.busy = 0, True, False
                    self.playbtn.configure(text="⏸ Pause")
                    self.status.configure(text=f"✓ {info}\n{len(cache)} views ready — switch instantly.",
                                          text_color=GOOD)
                    self.run_btn.configure(state="normal", text="▶  Run simulation")
                    self.prog.stop(); self.prog.pack_forget()
                elif kind == "error":
                    self.busy = False; self.status.configure(text=f"⚠ {payload}", text_color=WARN)
                    self.run_btn.configure(state="normal", text="▶  Run simulation")
                    self.prog.stop(); self.prog.pack_forget()
        except queue.Empty:
            pass
        self.root.after(80, self._poll)

    def _tick_studio(self):
        if self.cur == "studio" and self.playing and self.frames:
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
            self.status.configure(text=f"✓ Saved {path}", text_color=GOOD)
        except Exception as ex:
            messagebox.showerror("Export failed", f"{ex}\n\nGIF/MP4 export needs ffmpeg "
                                 f"(see docs/windows_build.md).")


def main():
    if ctk is None:
        print(f"customtkinter/Pillow unavailable: {_IMPORT_ERR}\n  pip install customtkinter pillow")
        return
    try:
        ctk.set_appearance_mode("dark")
        root = ctk.CTk()
    except Exception as e:
        print(f"No display to open the Studio ({e}).\nRun on a desktop, or use the demos in demos/.")
        return
    App(root); root.mainloop()


if __name__ == "__main__":
    main()
