# Accessibility and readability

## Colour tokens and measured contrast

The interface uses one dark scheme (`color-scheme: dark` on `:root`, so native form
controls and dropdown popups render dark too). Text and control colours are semantic
tokens in `web/app.css`; the ratios below are WCAG 2.2 contrast ratios computed against
the composited backgrounds (translucent "glass" layers are composited over `--navy-1`
before measuring). Targets: ≥ 4.5:1 for ordinary text, ≥ 3:1 for large text and
essential control boundaries and states.

| pair | ratio | used for |
|---|---|---|
| `--ink` #e8eefc on `--ctrl-bg` #111c31 | 14.6:1 | control text, values |
| `--read` #c3d0ea on `--navy-2` | 10.9:1 | body text |
| `--muted` #9fb0cc on `--ctrl-bg` | 7.7:1 | secondary text, labels |
| `--dim` #8fa3c4 on `--navy-0` / glass-2 | 7.6:1 / 6.1:1 | help text, units, estimates (was 3.9:1 / 3.1:1) |
| placeholder #8fa3c4 on `--ctrl-bg` | 6.7:1 | placeholders |
| white on `--blue-br` #3f6fe0 | 4.6:1 | blue buttons, selected segment (was 3.4:1) |
| white on `--sel-bg` #2f57c0 | 6.5:1 | selected option |
| `--on-lime` on `--lime` | 15.0:1 | primary Run button |
| `--err` #ff9a9a on `--navy-0` | 9.6:1 | validation errors |
| `--warn` #f2b866 on `--navy-0` | 11.0:1 | warnings, qualitative status |
| `--ctrl-border` #66789b vs `--navy-1` | 4.2:1 | input/select/button borders (was 1.3:1) |

The field palette (how simulation values become colours), the plot background
(background, obstacles, missing data) and the application appearance are separate:
changing the field palette never changes the controls, legends or annotations, and
empty space (NaN), solid obstacles and fluid at zero remain distinguishable
(`render.field_to_rgb`, tested in `tests/test_media.py`).

## Opened dropdowns

All selects (palette, scene, preset, export, gallery method, sweep parameter, presets)
share `background: var(--ctrl-bg); color: var(--ctrl-fg)` on the element, its options
and optgroups, with `option:checked` on `--sel-bg`. On the Linux GTK backend the
opened popup follows these rules. **Not yet verified on this machine:** the native
popups of Windows WebView2 and macOS WKWebView, whose appearance is drawn by the
operating system; `color-scheme: dark` is the documented way to request the dark
variant there. Please check an opened palette dropdown on each platform after
building and report it.

## Keyboard and motion

* Inactive views are `inert` (not focusable, hidden from assistive technology).
* Gallery cards, related previews, the Back control and all icon buttons are real
  buttons or have `role="button"` with labels; the favourite button does not activate
  its card.
* Global playback shortcuts (space, arrows, +/−, 0, Ctrl+Z, Ctrl+Enter) are ignored
  while an input, select, button, link or summary has focus.
* `prefers-reduced-motion` disables the hero animation, staged reveals, counter
  animation, the card morph and preview autoplay; autoplay and instant previews can
  also be switched off in Settings.
* Layout collapses to two, then one column below 1100 px / 860 px; the minimum window
  is 1120 × 720 and controls stay reachable at 125 % text scaling (CSS rem/px mix;
  checked by resizing, not by an automated test).
