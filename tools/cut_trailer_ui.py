"""Cut the interface recording into one clip per action (ui/ui_<name>.mp4) and build a preview sheet."""
import json, os, subprocess, sys
from pathlib import Path
UI = Path(os.environ.get('FUNOOS_TRAILER_UI') or Path(__file__).resolve().parents[1] / 'results' / '_trailer' / 'ui')
meta = json.loads((UI / 'segments.json').read_text()); video = meta['video']
LEAD = float(sys.argv[1]) if len(sys.argv) > 1 else 0.0          # recording starts slightly before the first timestamp
tiles = []
for name, (t0, t1) in meta['segments'].items():
    out = UI / f'ui_{name}.mp4'
    subprocess.run(['ffmpeg', '-v', 'error', '-y', '-ss', f'{t0 + LEAD:.3f}', '-to', f'{t1 + LEAD:.3f}', '-i', video, '-vf', 'fps=30',
                    '-c:v', 'libx264', '-crf', '14', '-pix_fmt', 'yuv420p', '-an', str(out)], check=True)
    d = t1 - t0
    for k, frac in enumerate((0.12, 0.55, 0.95)):
        png = UI / f'prev_{name}_{k}.png'
        subprocess.run(['ffmpeg', '-v', 'error', '-y', '-ss', f'{d * frac:.3f}', '-i', str(out), '-frames:v', '1', '-vf', 'scale=640:-2', str(png)], check=True)
        tiles.append(str(png))
    print(f'{name:8s} {t0:6.2f} -> {t1:6.2f}  ({d:.2f} s)')
n = len(meta['segments'])
subprocess.run(['ffmpeg', '-v', 'error', '-y', '-pattern_type', 'glob', '-i', str(UI / 'prev_*.png'), '-vf', f'tile=3x{n}', str(UI / 'ui_sheet.png')], check=True)
print('sheet:', UI / 'ui_sheet.png'); print('log:', meta.get('log'))
