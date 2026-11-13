import json
import matplotlib.pyplot as plt
from PIL import Image

IMG = "REPLACE_WITH_REAL_PATH.png"  # cleaned garment #40, 768x861
OUT = "tools/warp-benchmark/data/neck_hole/40.json"

img = Image.open(IMG)
plt.imshow(img)
plt.title("Left click = add point, Enter = finish")
pts = plt.ginput(n=-1, timeout=0)
with open(OUT, "w") as f:
    json.dump({"polygon": [[round(x), round(y)] for x, y in pts]}, f)
print("saved", len(pts), "points")
