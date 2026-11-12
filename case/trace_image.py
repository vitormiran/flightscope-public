"""Trace a line-art PNG into polygons for the model (read by flightscope_case.back_art). Run when the picture changes:
    .venv/bin/python trace_image.py imgs/daniel_the_tiger.png imgs/daniel_polys.json
Needs opencv-python-headless (VIRTUAL_ENV=.venv uv pip install opencv-python-headless); the model itself only reads the JSON.
Dark pixels become the engraved grooves. They are thickened by GROW px so the thin lines survive a 0.4 mm nozzle at the printed size."""
import sys, json
import numpy as np, cv2
from PIL import Image
GROW = 4           # px each side; at 54 mm tall (1441 px) this adds ~0.3 mm to every line
src, dst = sys.argv[1], sys.argv[2]
im = Image.open(src).convert("RGBA")
bg = Image.new("RGBA", im.size, (255, 255, 255, 255)); bg.alpha_composite(im)     # transparent -> white
dark = (np.array(bg.convert("L")) < 128).astype(np.uint8)
dark = cv2.dilate(dark, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * GROW + 1, 2 * GROW + 1)))
dark = (cv2.GaussianBlur(dark * 255, (0, 0), 1.5) > 127).astype(np.uint8)   # rounds pinch points and one-pixel bridges, which make self-touching outlines
ys, xs = np.where(dark); x0, x1, y0, y1 = xs.min(), xs.max() + 1, ys.min(), ys.max() + 1
dark = dark[y0:y1, x0:x1]
cnts, hier = cv2.findContours(dark, cv2.RETR_CCOMP, cv2.CHAIN_APPROX_NONE)
shapes = []     # {"outer": [(x, y)...], "holes": [...]} in px, y down, origin top-left of the cropped art
for i, c in enumerate(cnts):
    if hier[0][i][3] != -1: continue
    sh = {"outer": cv2.approxPolyDP(c, 0.8, True)[:, 0].tolist(), "holes": []}
    j = hier[0][i][2]
    while j != -1:
        sh["holes"].append(cv2.approxPolyDP(cnts[j], 0.8, True)[:, 0].tolist()); j = hier[0][j][0]
    shapes.append(sh)
json.dump({"w_px": int(x1 - x0), "h_px": int(y1 - y0), "shapes": shapes}, open(dst, "w"), separators=(",", ":"))
print(f"{len(shapes)} shapes, {sum(len(s['holes']) for s in shapes)} holes, {x1 - x0} x {y1 - y0} px -> {dst}")
