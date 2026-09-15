# Layout at real window sizes

The interface is a web page inside the desktop window, so what matters is the usable area of
that window in CSS pixels, not the screen resolution. The sizes below cover the common cases:

* **Windows laptops.** 1920×1080 panels at 125 % scaling (1536×864) and 150 % (1280×720), and
  1366×768 panels, minus the 48 px taskbar and the title bar. StatCounter's desktop figures for
  August 2026 list 1920×1080 at 22 %, 1536×864 at 6.8 %, 1366×768 at 5.3 % and 1280×720 at 3.5 %.
* **MacBooks at their default "looks like" sizes** (device pixel ratio 2): Air 13″ 1470×956,
  Air 15″ 1710×1107, Pro 14″ 1512×982 and Pro 16″ 1728×1117, minus the menu bar and title bar.
* **Monitors.** 1080p and 1440p, maximised.
* **The app's own window sizes.** The default is 1440×900 and the minimum 1024×640.

`tools/check_layout.py` loads the real page with the real backend, runs one simulation (the
airfoil at Low resolution), then resizes through these sizes and measures the gallery, the detail
page and the Studio. It runs in CI (job `ui-layout`) and uploads a screenshot per size.

## Before (1.1.2)

Measured with the same method on the 1.1.2 page, the airfoil experiment with seven controls.
The old minimum window was 1120×720.

| window | controls visible without scrolling | stage share of window | field share of window | readouts column | gallery cards fully on first screen |
|---|---|---|---|---|---|
| app minimum 1120×690 | 1 of 7 | 0.48 | 0.22 | outside the window | 3 |
| Windows 1080p at 150 %, 1280×641 | 1 of 7 | 0.41 | 0.20 | outside the window | 3 |
| Windows 1366×768, 1366×689 | 1 of 7 | 0.40 | 0.18 | half outside | 3 |
| app default 1440×870 | 2 of 7 | 0.41 | 0.13 | inside | 4 |
| MacBook Air 13″, 1470×900 | 3 of 7 | 0.42 | 0.14 | inside | 4 |
| MacBook Pro 14″, 1512×930 | 3 of 7 | 0.44 | 0.14 | inside | 5 |
| Windows 1080p at 125 %, 1536×785 | 2 of 7 | 0.42 | 0.18 | inside | 4 |
| MacBook Air 15″, 1710×1050 | 4 of 7 | 0.49 | 0.17 | inside | 6 |
| MacBook Pro 16″, 1728×1065 | 4 of 7 | 0.52 | 0.17 | inside | 6 |
| PC 1080p, 1920×1001 | 3 of 7 | 0.55 | 0.23 | inside | 6 |
| PC 1440p, 2560×1361 | 6 of 7 | 0.65 | 0.29 | inside | 6 |

Other findings in 1.1.2:

* **Stage toolbar.** It wrapped to a second row after a run on every window up to 1536 px wide.
  Its items could not shrink below 775 px, which pushed the readouts column out of windows up to
  1366 px wide.
* **Gallery badges.** On 5 to 7 cards per size the status badge covered the method name.
* **Thumbnails.** Clips filled a median 71 % of the card's picture area: 46 % for the five wake
  experiments, 4 % for the shock tube. Every clip carried an unreadable colour bar.
* **Paused cards.** Beyond six playing clips, cards showed the clip's first frame, the initial
  state, instead of the poster.
* **Detail text.** Explanations used 45 % of their box, because the page layout rule also applied
  to each paragraph.

## After (1.2.0)

Measured on the 1.2.0 page by `tools/check_layout.py` (the airfoil experiment, seven controls).

| window | controls visible without scrolling | stage toolbar rows | stage share of window | field share of window | readouts and transport | gallery cards fully on first screen | detail text use of its box | checks |
|---|---|---|---|---|---|---|---|---|
| app minimum 1024x640 | 4 of 7 | 1 | 0.49 | 0.18 | inside | 3 | 100% | pass |
| Windows 1080p at 150% 1280x641 | 4 of 7 | 1 | 0.53 | 0.27 | inside | 4 | 100% | pass |
| Windows 1366x768 1366x689 | 4 of 7 | 1 | 0.55 | 0.28 | inside | 4 | 100% | pass |
| app default 1440x870 | 6 of 7 | 1 | 0.55 | 0.23 | inside | 5 | 100% | pass |
| MacBook Air 13in 1470x900 | 6 of 7 | 1 | 0.56 | 0.23 | inside | 10 | 100% | pass |
| MacBook Pro 14in 1512x930 | 6 of 7 | 1 | 0.57 | 0.24 | inside | 10 | 100% | pass |
| Windows 1080p at 125% 1536x785 | 5 of 7 | 1 | 0.54 | 0.29 | inside | 5 | 100% | pass |
| MacBook Air 15in 1710x1050 | 7 of 7 | 1 | 0.59 | 0.24 | inside | 10 | 100% | pass |
| MacBook Pro 16in 1728x1065 | 7 of 7 | 1 | 0.60 | 0.24 | inside | 10 | 100% | pass |
| PC 1080p 1920x1001 | 7 of 7 | 1 | 0.61 | 0.31 | inside | 10 | 100% | pass |
| PC 1440p 2560x1361 | 7 of 7 | 1 | 0.70 | 0.35 | inside | 11 | 100% | pass |

With Plots open, windows 1500 px and wider show the plots beside the field instead of over it.

## What changed

These changes follow the guidance summarised in the 1.2.0 changelog: one dominant canvas,
progressive disclosure with at most two levels, overflow menus for secondary commands, and
layout by window size.

* **Studio.** One setup panel that can be hidden, with experiment and preset on one line.
  Secondary actions sit in a More menu. Each control shows one line of help, derived
  quantities are collapsed and Run stays visible.
* **Stage.** Tabs for Field, Plots, Explain and Runs, and a readouts strip of measurements.
  Export and zoom are in a menu, and no stage-bar item has a fixed minimum width.
* **Window-size layouts.** The setup panel is 340, 300, 280 or 258 px wide depending on the
  window, with icon-only tabs up to 1366 px and compact spacing up to 780 px of height.
* **Gallery.** Cards use thumbnails without colour bars (tools/make_thumbs.py), one metadata
  line and a poster whenever a card is not playing. Phenomenon chips and a Start here row sit
  above the grid.

What this check cannot show is how Windows WebView2 and macOS WKWebView render the native
dropdown popups and system fonts; the layout uses the same CSS on both.
