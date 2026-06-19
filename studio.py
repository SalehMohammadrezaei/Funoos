"""Funoos Studio — a polished, multi-page CFD gallery (CustomTkinter UI).

  • Intro   — what Funoos is, and who made it.
  • Gallery — browse exhibits: in-depth physics, governing equation, live demo.
  • Studio  — tune every parameter, Run once, then switch visualization
              (vorticity / speed / streamlines / …) live, with play/pause + export.

    pip install customtkinter pillow
    python studio.py
"""
from __future__ import annotations

import queue
import sys
import threading
from pathlib import Path

ROOT = Path(getattr(sys, "_MEIPASS", str(Path(__file__).resolve().parent)))
sys.path.insert(0, str(ROOT))
from flowzoo import engine, render, content, postproc, catalog

try:
    import tkinter as tk
    import customtkinter as ctk
    from PIL import Image, ImageTk, ImageSequence
    from tkinter import filedialog, messagebox
except Exception as e:  # pragma: no cover
    ctk = None
    _IMPORT_ERR = e

# ─────────────────────────  Funoos design system  ─────────────────────────
# Funoos (فانوس, the lantern of imagination) — "where imagination becomes vision."
# Warm-cream paper, deep-navy ink, a blue primary, and a lime-green signature pop.
# The simulation viewports stay deep-navy so the flows glow as the focal points.
BG     = "#F7EEE9"   # app background — warm cream
SURF   = "#FBF8F7"   # bars / sidebars / scroll panels — off-white
CARD   = "#FFFFFF"   # cards
CARD2  = "#ECF1FD"   # raised / hover / active — pale-blue tint
LINE   = "#E7DCD2"   # hairline border — warm
FG     = "#163251"   # primary text — dark navy
MUTED  = "#5A6E8C"   # secondary text — slate blue
DIM    = "#9A8C80"   # captions — warm gray
READ   = "#21405F"   # long-form body text — deep ocean
CYAN   = "#476DD5"   # primary accent — Funoos blue
CYAN_D = "#225090"   # accent hover — royal blue
GOLD   = "#3359A6"   # method kicker — mid blue
LIME   = "#E1FC66"   # signature pop — lime green
ON_LIME = "#163251"  # text on the lime fill
GOOD   = "#2F8F5E"; WARN = "#C0392B"
ONACC  = "#FBF8F7"   # text on the blue accent fill
INKCV  = "#0C1A2E"   # simulation preview background — deep navy
F = "Aptos"          # brand UI font (modern Windows / Office)
# type scale
T_DISPLAY = (F, 52, "bold"); T_H1 = (F, 27, "bold"); T_H2 = (F, 15, "bold")
T_KICK = (F, 11, "bold"); T_BODY = (F, 13); T_SMALL = (F, 11); T_CAP = (F, 10)


def slug(s):
    return "".join(c if c.isalnum() else "_" for c in s).strip("_").lower()


def load_gif(path, maxw=500):
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


def bind_click(w, fn):
    w.bind("<Button-1>", lambda e: fn())
    for c in w.winfo_children():
        bind_click(c, fn)


class Tooltip:
    def __init__(self, w, text):
        self.w, self.text, self.tip = w, text, None
        w.bind("<Enter>", self.show); w.bind("<Leave>", self.hide)

    def show(self, _=None):
        if self.tip or not self.text:
            return
        self.tip = tk.Toplevel(self.w); self.tip.wm_overrideredirect(True)
        self.tip.wm_geometry(f"+{self.w.winfo_rootx()+22}+{self.w.winfo_rooty()+20}")
        tk.Label(self.tip, text=self.text, bg=FG, fg=ONACC, justify="left",
                 wraplength=320, padx=12, pady=10, relief="solid", bd=1, font=(F, 9)).pack()

    def hide(self, _=None):
        if self.tip:
            self.tip.destroy(); self.tip = None


def kicker(parent, text, color=CYAN):
    return ctk.CTkLabel(parent, text="  ".join(text.upper()), font=T_KICK, text_color=color, anchor="w")


def rule(parent, w=42, color=CYAN):
    f = ctk.CTkFrame(parent, fg_color=color, height=3, width=w, corner_radius=2)
    return f


class App:
    def __init__(self, root):
        self.root = root
        root.title("Funoos  ·  where imagination becomes vision"); root.geometry("1360x840"); root.minsize(1120, 700)
        root.configure(fg_color=BG)
        self.q = queue.Queue()
        self.frames, self.pidx, self.playing, self.busy = [], 0, False, False
        self.fps = tk.IntVar(value=26)
        self.sel = list(engine.EXHIBITS)[0]
        self.gframes, self.gidx, self._eqimg = [], 0, None
        self.result = None; self.view = tk.StringVar(); self.cmap = tk.StringVar()
        self.viewbtns = {}; self.widgets = {}; self.cur = ""; self.viewcache = {}
        self.iframes, self.iidx = [], 0
        self.diag_on = False; self._scrub_guard = False; self._plotimgs = []
        self.scene_key = catalog.SCENES[0]["key"]; self.preset_seed = {}
        self.pages = {}
        self._intro(); self._gallery(); self._studio()
        self.show("intro")
        root.after(80, self._poll); root.after(45, self._tick_studio)
        root.after(60, self._tick_gallery); root.after(50, self._tick_intro)

    def show(self, name):
        for p in self.pages.values():
            p.pack_forget()
        self.pages[name].pack(fill="both", expand=True)
        self.cur = name
        if name == "gallery":
            self._select_scene(self.scene_key)
        if name == "studio":
            self._build_params()
            self.preset_seed = {}                  # consumed on this build; don't re-impose on re-flow

    # ─────────────────────────  intro  ─────────────────────────
    def _intro(self):
        pg = ctk.CTkFrame(self.root, fg_color=BG, corner_radius=0); self.pages["intro"] = pg
        col = ctk.CTkFrame(pg, fg_color=BG); col.place(relx=0.5, rely=0.5, anchor="center")
        # animated hero clip — the lantern's light
        hero = ctk.CTkFrame(col, fg_color=CARD, corner_radius=22, border_width=1, border_color=LINE)
        hero.pack(pady=(0, 14))
        self.intro_demo = tk.Label(hero, bg=INKCV, bd=0); self.intro_demo.pack(padx=10, pady=10)
        self.iframes = load_gif(ROOT / "results" / "gallery" / "spec_kh.gif", maxw=560) \
            or load_gif(ROOT / engine.META["Wind Tunnel"]["demo"], maxw=560)
        self.iidx = 0
        if not self.iframes:
            self.intro_demo.config(text="  Funoos  ", fg=MUTED, font=(F, 24), width=40, height=4)
        # FUNOOS wordmark — FUN (blue) · OOS (navy), echoing the logo
        t = ctk.CTkFrame(col, fg_color=BG); t.pack(pady=(2, 0))
        ctk.CTkLabel(t, text="FUN", font=T_DISPLAY, text_color=CYAN).pack(side="left")
        ctk.CTkLabel(t, text="OOS", font=T_DISPLAY, text_color=FG).pack(side="left")
        ctk.CTkLabel(col, text="Where imagination becomes vision.", font=(F, 16, "bold"),
                     text_color=GOLD).pack(pady=(4, 10))
        # the couplet — Bidel Dehlavi (فانوس = the lantern of imagination)
        couplet = ctk.CTkFrame(col, fg_color=CARD, corner_radius=16, border_width=1, border_color=LINE)
        couplet.pack(pady=(0, 12))
        ctk.CTkLabel(couplet, text="نگه شد شمعِ فانوسِ خیال از چشم‌پوشیدن",
                     font=(F, 13), text_color=READ).pack(padx=26, pady=(14, 0))
        ctk.CTkLabel(couplet, text="فنا، مشکل که از عاشق برد ذوقِ تماشا را",
                     font=(F, 13), text_color=READ).pack(padx=26, pady=(2, 8))
        ctk.CTkLabel(couplet, text="“When the eyes close, vision itself becomes the candle inside\n"
                     "imagination’s lantern — even annihilation can hardly take from the\n"
                     "lover the desire to visualize.”",
                     font=(F, 11), text_color=MUTED, justify="center").pack(padx=26, pady=(0, 2))
        ctk.CTkLabel(couplet, text="— Bidel Dehlavi", font=(F, 10, "bold"),
                     text_color=DIM).pack(padx=26, pady=(0, 12))
        ctk.CTkLabel(col, text="A visual exhibition of worlds in motion — flows illuminated through simulation.",
                     font=(F, 12), text_color=MUTED).pack(pady=(0, 12))
        chips = ctk.CTkFrame(col, fg_color=BG); chips.pack(pady=(0, 18))
        for c in ["Lattice-Boltzmann", "Navier–Stokes", "Compressible Euler", "SPH", "Spectral"]:
            ctk.CTkLabel(chips, text=f"  {c}  ", font=T_SMALL, text_color=READ, fg_color=CARD2,
                         corner_radius=20, height=30).pack(side="left", padx=4)
        cta = ctk.CTkButton(col, text="Enter the gallery   →", font=(F, 15, "bold"), width=260, height=50,
                            corner_radius=25, fg_color=LIME, hover_color="#CDEA4D", text_color=ON_LIME,
                            command=lambda: self.show("gallery")); cta.pack()
        ctk.CTkFrame(col, fg_color=LINE, height=1, width=320).pack(pady=(26, 12))
        ctk.CTkLabel(col, text="created by   Saleh Mohammadrezaei   ·   salehmrezaee@gmail.com",
                     font=T_SMALL, text_color=MUTED).pack()

    # ─────────────────────────  gallery  ─────────────────────────
    def _topbar(self, pg, back_label, back_cmd, title):
        bar = ctk.CTkFrame(pg, fg_color=SURF, corner_radius=0, height=64); bar.pack(fill="x")
        bar.pack_propagate(False)
        ctk.CTkButton(bar, text=back_label, width=70, height=34, fg_color="transparent",
                      hover_color=CARD, text_color=MUTED, font=T_SMALL,
                      command=back_cmd).pack(side="left", padx=(14, 6), pady=15)
        return bar

    def _gallery(self):
        pg = ctk.CTkFrame(self.root, fg_color=BG, corner_radius=0); self.pages["gallery"] = pg
        bar = self._topbar(pg, "‹ Home", lambda: self.show("intro"), "")
        ctk.CTkLabel(bar, text="The Gallery", font=T_H2, text_color=FG).pack(side="left", padx=4)
        ctk.CTkLabel(bar, text="   browse by method, then scene", font=T_SMALL,
                     text_color=MUTED).pack(side="left", padx=2)

        body = ctk.CTkFrame(pg, fg_color=BG); body.pack(fill="both", expand=True, padx=20, pady=18)

        # left: method → scene navigation
        nav = ctk.CTkScrollableFrame(body, fg_color=SURF, width=296, corner_radius=18)
        nav.pack(side="left", fill="y")
        self.scene_cards = {}
        for method, scenes in catalog.by_method().items():
            kicker(nav, method, GOLD).pack(fill="x", padx=16, pady=(16, 4))
            for s in scenes:
                card = ctk.CTkFrame(nav, fg_color=CARD, corner_radius=12, border_width=1, border_color=CARD)
                card.pack(fill="x", padx=8, pady=3)
                ctk.CTkLabel(card, text=s["name"], font=(F, 12, "bold"), text_color=FG,
                             anchor="w").pack(fill="x", padx=13, pady=8)
                bind_click(card, lambda k=s["key"]: self._select_scene(k))
                self._bind_hover(card, s["key"])
                self.scene_cards[s["key"]] = card

        # right: scene detail
        det = ctk.CTkFrame(body, fg_color=BG); det.pack(side="left", fill="both", expand=True, padx=(18, 0))
        self.g_method = kicker(det, "", GOLD); self.g_method.pack(fill="x")
        self.g_title = ctk.CTkLabel(det, text="", font=T_H1, text_color=FG, anchor="w")
        self.g_title.pack(fill="x", pady=(2, 6)); rule(det).pack(anchor="w", pady=(0, 8))

        split = ctk.CTkFrame(det, fg_color=BG); split.pack(fill="both", expand=True)
        media = ctk.CTkFrame(split, fg_color=BG, width=580); media.pack(side="right", fill="y", padx=(18, 0))
        media.pack_propagate(False)
        mc = ctk.CTkFrame(media, fg_color=BG); mc.pack(expand=True)
        demo_card = ctk.CTkFrame(mc, fg_color=CARD, corner_radius=18, border_width=1, border_color=LINE)
        demo_card.pack()
        self.g_demo = tk.Label(demo_card, bg=INKCV, bd=0); self.g_demo.pack(padx=12, pady=12)
        self.g_caption = ctk.CTkLabel(mc, text="", font=T_CAP, text_color=DIM); self.g_caption.pack(pady=(8, 0))
        ctk.CTkButton(mc, text="Open in Studio   →", font=(F, 15, "bold"), height=52, corner_radius=16,
                      fg_color=CYAN, hover_color=CYAN_D, text_color=ONACC,
                      command=self._open_in_studio).pack(fill="x", pady=(14, 0))
        self.read = ctk.CTkScrollableFrame(split, fg_color=SURF, corner_radius=18)
        self.read.pack(side="left", fill="both", expand=True)

    def _bind_hover(self, card, key):
        # cards lift (pale-blue fill + accent border) as the pointer floats over them
        def on(_=None):
            if key != self.scene_key:
                card.configure(fg_color=CARD2, border_color=CYAN)

        def off(_=None):
            if key != self.scene_key:
                card.configure(fg_color=CARD, border_color=CARD)
        for w in [card] + list(card.winfo_children()):
            w.bind("<Enter>", on); w.bind("<Leave>", off)

    def _section(self, header, body, color=CYAN):
        kicker(self.read, header, color).pack(fill="x", pady=(16, 4), padx=16)
        ctk.CTkLabel(self.read, text=body, font=T_BODY, text_color=READ, justify="left",
                     anchor="w", wraplength=600).pack(fill="x", padx=16)

    def _select_scene(self, key):
        s = catalog.scene(key)
        if not s:
            return
        self.scene_key = key; self.sel = s["exhibit"]
        for k, c in self.scene_cards.items():
            on = k == key
            c.configure(fg_color=CARD2 if on else CARD, border_color=CYAN if on else CARD)
        m = engine.META.get(s["exhibit"], {}); d = content.DETAIL.get(s["exhibit"], {})
        self.g_method.configure(text="  ".join(s["method"].upper()))
        self.g_title.configure(text=s["name"])
        for w in self.read.winfo_children():
            w.destroy()
        self._section("this scene", s["blurb"])
        self._section("the physics", d.get("physics", m.get("blurb", "")))
        kicker(self.read, "governing equation", CYAN).pack(fill="x", pady=(18, 6), padx=16)
        try:
            im = Image.open(ROOT / "docs" / "eq" / (slug(s["exhibit"]) + ".png"))
            w = min(600, im.width); h = int(im.height * w / im.width)
            self._eqimg = ctk.CTkImage(light_image=im, dark_image=im, size=(w, h))
            ctk.CTkLabel(self.read, image=self._eqimg, text="").pack(anchor="w", padx=16)
        except Exception:
            pass
        if d.get("terms"):
            ctk.CTkLabel(self.read, text=d["terms"], font=T_SMALL, text_color=MUTED,
                         justify="left", anchor="w", wraplength=600).pack(fill="x", padx=16, pady=(8, 0))
        self._section("how it's solved", m.get("numerics", ""))
        self._section("validation", "✓  " + m.get("validation", ""), color=GOOD)
        ctk.CTkLabel(self.read, text="", font=T_CAP).pack(pady=4)        # bottom breathing room

        self.g_caption.configure(text=f"{s['exhibit']} · {m.get('method', '')}")
        self.gframes = load_gif(ROOT / "results" / "gallery" / (key + ".gif"), maxw=540)
        if not self.gframes:                                            # fall back to stock demo
            self.gframes = load_gif(ROOT / m.get("demo", ""), maxw=540)
        self.gidx = 0
        if not self.gframes:
            self.g_demo.config(image="", text="\n  clip rendering —\n  run  render_gallery.py\n",
                               fg=MUTED, font=(F, 11), width=58, height=14)

    def _open_in_studio(self):
        s = catalog.scene(self.scene_key)
        if s:
            self.sel = s["exhibit"]; self.widgets = {}
            self.preset_seed = {k: (v if isinstance(v, str) else f"{v:g}") for k, v in s["preset"].items()}
            self.exhibit.set(s["exhibit"])
        self.show("studio")

    def _tick_gallery(self):
        if self.cur == "gallery" and self.gframes:
            self.g_demo.config(image=self.gframes[self.gidx % len(self.gframes)]); self.gidx += 1
        self.root.after(45, self._tick_gallery)

    def _tick_intro(self):
        if self.cur == "intro" and self.iframes:
            self.intro_demo.config(image=self.iframes[self.iidx % len(self.iframes)]); self.iidx += 1
        self.root.after(42, self._tick_intro)

    # ─────────────────────────  studio  ─────────────────────────
    def _studio(self):
        pg = ctk.CTkFrame(self.root, fg_color=BG, corner_radius=0); self.pages["studio"] = pg
        bar = self._topbar(pg, "‹ Gallery", lambda: self.show("gallery"), "")
        self.exhibit = ctk.CTkOptionMenu(bar, values=list(engine.EXHIBITS), width=320, height=34, font=T_SMALL,
                                         fg_color=CARD, button_color=CARD2, button_hover_color=CYAN,
                                         dropdown_fg_color=CARD, command=self._pick_exhibit)
        self.exhibit.set(self.sel); self.exhibit.pack(side="left", padx=6)

        body = ctk.CTkFrame(pg, fg_color=BG); body.pack(fill="both", expand=True, padx=20, pady=20)
        side = ctk.CTkFrame(body, fg_color=SURF, width=356, corner_radius=18); side.pack(side="left", fill="y")
        side.pack_propagate(False)
        kicker(side, "parameters", CYAN).pack(fill="x", padx=18, pady=(16, 0))
        self.pscroll = ctk.CTkScrollableFrame(side, fg_color=SURF, corner_radius=0)
        self.pscroll.pack(fill="both", expand=True, padx=8, pady=8)

        bot = ctk.CTkFrame(side, fg_color=SURF); bot.pack(fill="x", padx=18, pady=(0, 16))
        self.run_btn = ctk.CTkButton(bot, text="▶   Run simulation", font=(F, 14, "bold"), height=50,
                                     corner_radius=14, fg_color=CYAN, hover_color=CYAN_D, text_color=ONACC,
                                     command=self.run); self.run_btn.pack(fill="x")
        self.prog = ctk.CTkProgressBar(bot, mode="indeterminate", progress_color=CYAN, height=6)
        sv = ctk.CTkFrame(bot, fg_color=SURF); sv.pack(fill="x", pady=(10, 0))
        ctk.CTkButton(sv, text="⬇  GIF", fg_color=CARD2, hover_color=CYAN_D, text_color=FG, font=T_SMALL,
                      command=lambda: self.save("gif")).pack(side="left", expand=True, fill="x", padx=(0, 4))
        ctk.CTkButton(sv, text="⬇  MP4", fg_color=CARD2, hover_color=CYAN_D, text_color=FG, font=T_SMALL,
                      command=lambda: self.save("mp4")).pack(side="left", expand=True, fill="x")
        self.status = ctk.CTkLabel(bot, text="Ready.", text_color=MUTED, font=T_CAP, anchor="w",
                                   justify="left", wraplength=300); self.status.pack(fill="x", pady=(12, 0))

        prev = ctk.CTkFrame(body, fg_color=BG); prev.pack(side="left", fill="both", expand=True, padx=(20, 0))
        self.viewbar = ctk.CTkFrame(prev, fg_color=BG); self.viewbar.pack(fill="x", pady=(0, 12))
        # stage holds either the animation canvas or the diagnostics panel
        self.stage = ctk.CTkFrame(prev, fg_color=BG); self.stage.pack(fill="both", expand=True)
        self.framecard = ctk.CTkFrame(self.stage, fg_color=CARD, corner_radius=18, border_width=1, border_color=LINE)
        self.framecard.pack(fill="both", expand=True)
        self.canvas = tk.Label(self.framecard, bg=INKCV, fg=MUTED, font=(F, 15),
                               text="Set parameters   ›   Run ▶\nthen switch views live")
        self.canvas.pack(fill="both", expand=True, padx=12, pady=12)
        self.plotscroll = ctk.CTkScrollableFrame(self.stage, fg_color=SURF, corner_radius=18)  # diagnostics (hidden until requested)
        self._build_transport(prev)

    def _build_transport(self, parent):
        tb = ctk.CTkFrame(parent, fg_color=SURF, corner_radius=14, height=58); tb.pack(fill="x", pady=(12, 0))
        tb.pack_propagate(False)

        def btn(txt, cmd, w=40):
            return ctk.CTkButton(tb, text=txt, width=w, height=34, corner_radius=10, fg_color=CARD2,
                                 hover_color=CYAN, text_color=FG, font=(F, 13, "bold"), command=cmd)
        btn("⏮", self._to_start).pack(side="left", padx=(12, 3), pady=12)
        btn("◀", lambda: self._step(-1)).pack(side="left", padx=3)
        self.tplay = btn("▶", self._toggle_play, 46); self.tplay.pack(side="left", padx=3)
        btn("▶▶", lambda: self._step(1)).pack(side="left", padx=3)
        self.scrubvar = tk.DoubleVar(value=0)
        self.scrub = ctk.CTkSlider(tb, from_=0, to=1, variable=self.scrubvar, progress_color=CYAN,
                                   button_color=CYAN, button_hover_color=CYAN_D, command=self._on_scrub)
        self.scrub.pack(side="left", fill="x", expand=True, padx=10)
        self.fcount = ctk.CTkLabel(tb, text="—", text_color=MUTED, font=T_CAP, width=58); self.fcount.pack(side="left")
        ctk.CTkLabel(tb, text="speed", text_color=MUTED, font=T_CAP).pack(side="left", padx=(8, 2))
        btn("–", lambda: self._speed(-3), 30).pack(side="left", padx=2)
        self.spdlbl = ctk.CTkLabel(tb, text=str(self.fps.get()), text_color=FG, font=T_SMALL, width=26)
        self.spdlbl.pack(side="left")
        btn("+", lambda: self._speed(3), 30).pack(side="left", padx=(2, 12))

    def _show_frame(self):
        if not self.frames:
            return
        arr = self.frames[self.pidx % len(self.frames)]
        cw, ch = max(self.canvas.winfo_width(), 100), max(self.canvas.winfo_height(), 100)
        img = Image.fromarray(arr); sc = min(cw / img.width, ch / img.height)
        img = img.resize((max(1, int(img.width * sc)), max(1, int(img.height * sc))))
        self._photo = ImageTk.PhotoImage(img); self.canvas.config(image=self._photo, text="")

    def _to_start(self):
        self.playing = False; self.tplay.configure(text="▶"); self.pidx = 0; self._show_frame()

    def _step(self, d):
        if not self.frames:
            return
        self.playing = False; self.tplay.configure(text="▶")
        self.pidx = (self.pidx + d) % len(self.frames); self._show_frame()

    def _on_scrub(self, _=None):
        if self._scrub_guard or not self.frames:
            return
        self.playing = False; self.tplay.configure(text="▶")
        self.pidx = int(round(self.scrubvar.get() * (len(self.frames) - 1))); self._show_frame()

    def _speed(self, d):
        self.fps.set(max(2, min(60, self.fps.get() + d))); self.spdlbl.configure(text=str(self.fps.get()))

    # ---- diagnostics panel ----
    def _show_anim(self):
        self.plotscroll.pack_forget(); self.framecard.pack(fill="both", expand=True); self.diag_on = False
        if hasattr(self, "diagbtn"):
            self.diagbtn.configure(text="📊  Plots")

    def _toggle_diag(self):
        if self.diag_on:
            self._show_anim(); return
        if not self.result or self.busy:
            return
        self.busy = True; self.prog.pack(fill="x", pady=(10, 0)); self.prog.start()
        self.status.configure(text="⏳ computing diagnostics…", text_color=MUTED)
        res = self.result

        def work():
            try:
                self.q.put(("plots", postproc.plots(res)))
            except Exception as ex:  # pragma: no cover
                self.q.put(("error", str(ex)))
        threading.Thread(target=work, daemon=True).start()

    def _render_plots(self, plots):
        for w in self.plotscroll.winfo_children():
            w.destroy()
        self._plotimgs = []
        if not plots:
            ctk.CTkLabel(self.plotscroll, text="No diagnostics available for this case.",
                         text_color=MUTED, font=T_BODY).pack(pady=30)
        for title, arr in plots:
            kicker(self.plotscroll, title, CYAN).pack(fill="x", padx=16, pady=(16, 4))
            im = Image.fromarray(arr)
            ci = ctk.CTkImage(light_image=im, dark_image=im, size=(im.width, im.height))
            self._plotimgs.append(ci)
            ctk.CTkLabel(self.plotscroll, image=ci, text="").pack(padx=16, pady=(0, 4))
        self.framecard.pack_forget(); self.plotscroll.pack(fill="both", expand=True)
        self.diag_on = True; self.diagbtn.configure(text="▶  Animation")

    def _pick_exhibit(self, name):
        self.sel = name; self.preset_seed = {}; self.widgets = {}
        self._build_params(); self.result = None; self.viewcache = {}
        for w in self.viewbar.winfo_children():
            w.destroy()

    def _curval(self, name):
        # current value of a control: a built widget, else the value being carried
        # across a rebuild (controller may not be rebuilt yet), else the default
        if name in self.widgets:
            return self.widgets[name][1].get()
        pending = getattr(self, "_pending", {})
        if name in pending:
            return pending[name]
        for qd in engine.EXHIBITS[self.sel]["params"]:
            if qd["name"] == name:
                return qd["default"]
        return None

    def _visible(self, qd):
        # a param with "when": (control, [values]) only shows for those values
        w = qd.get("when")
        if not w:
            return True
        ctrl, vals = w
        return self._curval(ctrl) in vals

    def _build_params(self):
        # seed from a gallery preset (if any), then keep values the user already typed
        saved = dict(self.preset_seed)
        saved.update({n: v.get() for n, (qd, v) in self.widgets.items()})
        self._pending = saved
        for w in self.pscroll.winfo_children():
            w.destroy()
        self.widgets = {}
        groups = {}
        for qd in engine.EXHIBITS[self.sel]["params"]:
            groups.setdefault(qd.get("group", "Render"), []).append(qd)
        for g in ["Geometry", "Physics", "Render"]:
            vis = [qd for qd in groups.get(g, []) if self._visible(qd)]
            if not vis:
                continue
            kicker(self.pscroll, g, GOLD).pack(fill="x", pady=(14, 6))
            cardg = ctk.CTkFrame(self.pscroll, fg_color=CARD, corner_radius=12)
            cardg.pack(fill="x")
            for qd in vis:
                self._row(cardg, qd, saved.get(qd["name"]))

    def _row(self, parent, qd, saved=None):
        row = ctk.CTkFrame(parent, fg_color=CARD); row.pack(fill="x", padx=10, pady=(8, 4))
        head = ctk.CTkFrame(row, fg_color=CARD); head.pack(fill="x")
        lab = qd.get("label", qd["name"])
        if qd["type"] == "float":
            lab += f"   ({qd['min']:g}–{qd['max']:g})"
        ctk.CTkLabel(head, text=lab, font=(F, 11, "bold"), text_color=FG, anchor="w").pack(side="left")
        if qd.get("help"):
            chip = ctk.CTkLabel(head, text=" ? ", font=(F, 10, "bold"), text_color=ONACC, fg_color=CYAN,
                                corner_radius=9); chip.pack(side="right")
            Tooltip(chip, qd["help"])
            chip.bind("<Button-1>", lambda e, t=qd["help"], n=lab: messagebox.showinfo(n, t))
        if qd["type"] == "choice":
            init = saved if saved in qd["choices"] else qd["default"]
            v = tk.StringVar(value=init)
            # changing a control re-flows the panel so scene-specific params appear
            ctk.CTkOptionMenu(row, values=qd["choices"], variable=v, font=T_SMALL, fg_color=CARD2,
                              button_color=CYAN, button_hover_color=CYAN, dropdown_fg_color=CARD2,
                              command=lambda *_: self._build_params()).pack(fill="x", pady=(4, 0))
        else:
            default = qd["default"] if qd["type"] == "str" else f"{qd['default']:g}"
            v = tk.StringVar(value=saved if saved is not None else default)
            ctk.CTkEntry(row, textvariable=v, font=T_SMALL, fg_color=CARD2, border_color=LINE,
                         border_width=1).pack(fill="x", pady=(4, 0))
        self.widgets[qd["name"]] = (qd, v)

    def _params(self):
        # start from every param's default, then override with the built (visible) widgets,
        # so scene-hidden params still pass a sane value to the engine
        vals = {qd["name"]: qd["default"] for qd in engine.EXHIBITS[self.sel]["params"]}
        for n, (qd, v) in self.widgets.items():
            vals[n] = float(v.get()) if qd["type"] == "float" else v.get()
        return vals

    def run(self):
        if self.busy:
            return
        try:
            params = self._params()
        except ValueError:
            self.status.configure(text="A numeric field has an invalid value.", text_color=WARN); return
        self.busy = True; self.playing = False; self.viewcache = {}
        self.run_btn.configure(state="disabled", text="●  Simulating…")
        self.prog.pack(fill="x", pady=(10, 0)); self.prog.start()
        name = self.sel

        def work():
            try:
                res = engine.solve_exhibit(name, params, progress=lambda s: self.q.put(("status", s)))
                self.q.put(("solved", res))
                cm = engine.DEFCMAP[res.kind]; cache = {}
                for v in res.views:
                    if v == "Streamlines":      # expensive — rendered lazily on first click
                        continue
                    self.q.put(("status", f"rendering {v}…")); cache[v] = res.render(v, cm)
                self.q.put(("cached", (cache, res.views[0], res.info)))
            except Exception as ex:  # pragma: no cover
                self.q.put(("error", str(ex)))
        threading.Thread(target=work, daemon=True).start()

    def _set_views(self, res):
        for w in self.viewbar.winfo_children():
            w.destroy()
        self.view.set(res.views[0])
        self.seg = ctk.CTkSegmentedButton(self.viewbar, values=res.views, variable=self.view,
                                          font=(F, 11, "bold"), height=34, fg_color=CARD,
                                          selected_color=CYAN, selected_hover_color=CYAN_D,
                                          unselected_color=CARD, unselected_hover_color=CARD2,
                                          text_color=FG, command=self._change_view)
        self.seg.set(res.views[0]); self.seg.pack(side="left")
        ctk.CTkLabel(self.viewbar, text="  Palette", text_color=MUTED, font=T_CAP).pack(side="left", padx=(10, 4))
        self.cmap.set(engine.DEFCMAP[res.kind])
        ctk.CTkOptionMenu(self.viewbar, values=list(render.COLORMAPS), variable=self.cmap, width=160,
                          height=34, font=T_SMALL, fg_color=CARD, button_color=CARD2,
                          button_hover_color=CYAN, dropdown_fg_color=CARD,
                          command=lambda *_: self._recolor()).pack(side="left")
        self.diagbtn = ctk.CTkButton(self.viewbar, text="📊  Plots", width=120, height=34, corner_radius=12,
                                     font=(F, 11, "bold"), fg_color=CARD2, hover_color=CYAN, text_color=FG,
                                     command=self._toggle_diag); self.diagbtn.pack(side="right")

    def _change_view(self, v):
        self.view.set(v)
        if v in self.viewcache:
            self.frames = self.viewcache[v]; self.pidx = 0; self.playing = True; self._show_anim()
        elif self.result and not self.busy:          # render this view on demand (e.g. Streamlines)
            self.busy = True; self.run_btn.configure(state="disabled")
            self.prog.pack(fill="x", pady=(10, 0)); self.prog.start()
            self.status.configure(text=f"⏳ rendering {v}…", text_color=MUTED)
            res, c = self.result, self.cmap.get()

            def work():
                try:
                    self.q.put(("rendered_one", (v, res.render(v, c))))
                except Exception as ex:  # pragma: no cover
                    self.q.put(("error", str(ex)))
            threading.Thread(target=work, daemon=True).start()

    def _toggle_play(self):
        self.playing = not self.playing
        if hasattr(self, "tplay"):
            self.tplay.configure(text="⏸" if self.playing else "▶")

    def _recolor(self):
        if not self.result or self.busy:
            return
        self.busy = True; self.run_btn.configure(state="disabled")
        self.prog.pack(fill="x", pady=(10, 0)); self.prog.start()
        res, c = self.result, self.cmap.get()

        def work():
            try:
                cache = {}
                for v in res.views:
                    if v == "Streamlines":
                        continue
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
                    self.viewcache = cache
                    if view not in cache:
                        view = next(iter(cache))
                    self.view.set(view)
                    if hasattr(self, "seg"):
                        self.seg.set(view)
                    self.frames = cache[view]
                    self.pidx, self.playing, self.busy = 0, True, False
                    self._show_anim()
                    if hasattr(self, "tplay"):
                        self.tplay.configure(text="⏸")
                    self.status.configure(text=f"✓ {info} — views switch instantly.", text_color=GOOD)
                    self.run_btn.configure(state="normal", text="▶   Run simulation")
                    self.prog.stop(); self.prog.pack_forget()
                elif kind == "rendered_one":
                    v, fr = payload; self.viewcache[v] = fr
                    if self.view.get() == v:
                        self.frames = fr; self.pidx = 0; self.playing = True
                    self.busy = False; self.run_btn.configure(state="normal", text="▶   Run simulation")
                    self.prog.stop(); self.prog.pack_forget()
                    self.status.configure(text=f"✓ {v} ready.", text_color=GOOD)
                elif kind == "plots":
                    self._render_plots(payload)
                    self.busy = False; self.prog.stop(); self.prog.pack_forget()
                    self.status.configure(text="✓ diagnostics ready.", text_color=GOOD)
                elif kind == "error":
                    self.busy = False; self.status.configure(text=f"⚠ {payload}", text_color=WARN)
                    self.run_btn.configure(state="normal", text="▶   Run simulation")
                    self.prog.stop(); self.prog.pack_forget()
        except queue.Empty:
            pass
        self.root.after(80, self._poll)

    def _tick_studio(self):
        if self.cur == "studio" and self.frames and not self.diag_on:
            if self.playing:
                self.pidx = (self.pidx + 1) % len(self.frames)
                self._show_frame()
            n = len(self.frames); cur = self.pidx % n
            self.fcount.configure(text=f"{cur + 1}/{n}")
            self._scrub_guard = True                       # move the scrubber without firing its command
            self.scrubvar.set(cur / max(1, n - 1)); self._scrub_guard = False
        self.root.after(int(1000 / max(1, self.fps.get())), self._tick_studio)

    def save(self, kind):
        if not self.frames:
            messagebox.showinfo("Funoos", "Run a simulation first."); return
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
        ctk.set_appearance_mode("light")
        root = ctk.CTk()
    except Exception as e:
        print(f"No display to open the Studio ({e}).\nRun on a desktop, or use the demos in demos/.")
        return
    App(root); root.mainloop()


if __name__ == "__main__":
    main()
