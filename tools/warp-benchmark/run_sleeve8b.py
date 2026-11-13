"""MLS benchmark round 8b: round 8 re-measured with the re-marked landmarks + shoulder_top_skin_px (docs/06, NOT
production). Reads the export of tools/warp-benchmark/export_sleeve8b.py (data/sleeve8b/), not the DB.

    docker compose cp tools/warp-benchmark backend:/tmp/warp-benchmark
    docker compose exec -T backend python manage.py shell < tools/warp-benchmark/run_sleeve8b.py
    docker compose cp backend:/tmp/warp_benchmark/. tools/warp-benchmark/out/

apps.tryon_engine.mls.tshirt_layer(..., "adapt", sleeve_variant=v, debug_map=True) for #28, #43, #40 x all avatars,
k 1.0 (adapt). r7 = round 7 (production default); A = no smid pairs; B = smid_out at the deltoid edge; C = B + cuff_mid.
Metrics: arm_band_skin_px (figure px inside the r7 body-target quad shoulder -> cuff_out -> cuff_in -> armpit, not
covered; the same quad for every variant), cuff_wave_px, gap_px, excess_px, fold, runtime.
shoulder_top_skin_px: figure px not covered in the band neck edge -> acromion, neck row -> shoulder line + 0.08 x
shoulder width, arm band excluded (r7 boxes for every variant). side_floor off.
Writes out/results8b.json, out/table8b.md, out/sheet_sleeve8b_<id>.png (rows = avatars, columns = r7 | A | B | C;
grey = arm band, blue = shoulder-top band) and out/crop_sleeve8b_worst_<v>.png (2x, most arm-band + shoulder-top skin).
"""
import json
import os
import sys

import cv2
import numpy as np

sys.path.insert(0, "/tmp/warp-benchmark")
import mls as bm  # noqa: E402  (benchmark: metrics, composite)
import mls_fitted as mf  # noqa: E402

from apps.tryon_engine import mls as pm  # noqa: E402  (production)
from apps.tryon_engine import warp  # noqa: E402

GARMENTS = [28, 43, 40]
VARIANTS = ["r7", "A", "B", "C"]
H, W = 1200, 600
OUT = "/tmp/warp_benchmark"
CROP_H = 380
DATA = "/tmp/warp-benchmark/data/sleeve8b"
os.makedirs(OUT, exist_ok=True)


def label(img, text):
    for col, th in (((255, 255, 255), 3), ((0, 0, 0), 1)):
        cv2.putText(img, text, (6, 18), cv2.FONT_HERSHEY_SIMPLEX, 0.5, col, th, cv2.LINE_AA)
    return img


def crop_y0(blm):
    return max(int(blm["shoulder"]["y"]) - 60, 0)


class Av:
    def __init__(self, pk):
        with open(f"{DATA}/avatars/{pk}.json") as fh:
            d = json.load(fh)
        self.pk, self.sex, self.build, self.landmarks = pk, d["sex"], d["build"], d["landmarks"]


avatars = [Av(pk) for pk in sorted(int(f[:-5]) for f in os.listdir(f"{DATA}/avatars") if f.endswith(".json"))]
bases, masks = {}, {}
for av in avatars:
    bases[av.pk] = cv2.imread(f"{DATA}/avatars/{av.pk}.png", cv2.IMREAD_UNCHANGED)  # already 600x1200 BGRA
    masks[av.pk] = warp.figure_mask(bases[av.pk])

results, worst = [], {}
for gid in GARMENTS:
    gimg = cv2.imread(f"{DATA}/garments/{gid}.png", cv2.IMREAD_UNCHANGED)
    with open(f"{DATA}/garments/{gid}.json") as fh:
        glm = json.load(fh)["landmarks"]
    rows = []
    for av in avatars:
        blm, mask = av.landmarks, masks[av.pk]
        cells, quads, boxes = [], None, None
        for v in VARIANTS:
            layer, info = pm.tshirt_layer(gimg, glm, blm, mask, "adapt", H, W, sleeve_variant=v, debug_map=True)
            if v == "r7":
                quads = mf.arm_band_quads(info["pairs"], blm)
                boxes = mf.shoulder_top_boxes(info["pairs"], blm, quads)
            band = mf.arm_band_skin_px(layer, mask, quads)
            top = mf.shoulder_top_skin_px(layer, mask, boxes)
            cov = mf.coverage_metrics(layer, mask, info, blm)
            rec = {"garment": gid, "avatar": av.pk, "who": f"{av.sex[0]}-{av.build}", "variant": v,
                   "arm_band_skin_px": band["total"], "arm_band_l": band["left"], "arm_band_r": band["right"],
                   "shoulder_top_skin_px": top["total"], "shoulder_top_l": top["left"], "shoulder_top_r": top["right"],
                   "cuff_wave_px": mf.cuff_wave_px(layer, info["pairs"]),
                   "gap_px": cov["gap_px"], "excess_px": cov["excess_px"],
                   "fold": round(bm.metrics(layer, info, blm)["fold"], 5),
                   "runtime_s": round(info["runtime"], 3), "rejected": info["rejected"],
                   "smid": sorted(k for k in info["pairs"] if k.startswith(("smid", "cuff_mid")))}
            results.append(rec)
            print(json.dumps(rec, default=str))
            rgb = bm.composite(bases[av.pk], layer, blm, info)
            y0 = crop_y0(blm)
            crop = rgb[y0:y0 + CROP_H].copy()
            for quad in quads.values():  # the measured arm band, thin grey outline
                if quad is not None:
                    q = np.round(quad - np.array([0, y0], np.float32)).astype(np.int32)
                    cv2.polylines(crop, [q], True, (160, 160, 160), 1, cv2.LINE_AA)
            for box in boxes.values():  # the shoulder-top band, thin blue outline
                if box is not None:
                    cs, _ = cv2.findContours(box[y0:y0 + CROP_H].astype(np.uint8), cv2.RETR_EXTERNAL,
                                             cv2.CHAIN_APPROX_SIMPLE)
                    cv2.drawContours(crop, cs, -1, (200, 120, 40), 1)
            cells.append(label(crop, f"{v} #{gid} {rec['who']} arm {band['total']} top {top['total']} "
                                     f"wave {rec['cuff_wave_px']}"))
            both = band["total"] + top["total"]
            if v not in worst or both > worst[v][0]:
                worst[v] = (both, gid, rec["who"], crop.copy())
        rows.append(np.hstack(cells))
    cv2.imwrite(f"{OUT}/sheet_sleeve8b_{gid}.png", np.vstack(rows))
for v, (n, gid, who, crop) in worst.items():
    big = cv2.resize(crop, None, fx=2, fy=2, interpolation=cv2.INTER_NEAREST)
    for col, th in (((255, 255, 255), 4), ((0, 0, 0), 1)):  # bottom: the cell label is already at the top
        cv2.putText(big, f"worst {v}: {n} arm-band + shoulder-top skin px, #{gid} {who}", (8, big.shape[0] - 14),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.8, col, th, cv2.LINE_AA)
    cv2.imwrite(f"{OUT}/crop_sleeve8b_worst_{v}.png", big)

with open(f"{OUT}/results8b.json", "w") as fh:
    json.dump(results, fh, default=str, indent=1)

# table: per variant summary, then every run
lines = ["| variant | arm-band skin px (sum / max) | shoulder-top skin px (sum L / R, max) | gap px (sum) | "
         "excess px (sum) | fold (max) | cuff wave px (median / max) | runtime s (max) | dropped |",
         "|---|---|---|---|---|---|---|---|---|"]
for v in VARIANTS:
    rs = [r for r in results if r["variant"] == v]
    waves = [r["cuff_wave_px"] for r in rs if r["cuff_wave_px"] is not None]
    dropped = sorted({x for r in rs for x in r["rejected"] if "smid" in x or "cuff_mid" in x})
    lines.append(f"| {v} | {sum(r['arm_band_skin_px'] for r in rs)} / {max(r['arm_band_skin_px'] for r in rs)} | "
                 f"{sum(r['shoulder_top_l'] or 0 for r in rs)} / {sum(r['shoulder_top_r'] or 0 for r in rs)}, "
                 f"{max(r['shoulder_top_skin_px'] for r in rs)} | {sum(r['gap_px'] for r in rs)} | "
                 f"{sum(r['excess_px'] for r in rs)} | {max(r['fold'] for r in rs):.5f} | "
                 f"{np.median(waves):.1f} / {max(waves):.1f} | {max(r['runtime_s'] for r in rs):.2f} | "
                 f"{', '.join(dropped) or '-'} |")
lines += ["", "| garment | avatar | variant | arm-band skin L / R | shoulder-top skin L / R | cuff wave | gap | excess | "
          "fold | runtime s | dropped |", "|---|---|---|---|---|---|---|---|---|---|---|"]
for r in results:
    lines.append(f"| #{r['garment']} | {r['who']} | {r['variant']} | {r['arm_band_l']} / {r['arm_band_r']} | "
                 f"{r['shoulder_top_l']} / {r['shoulder_top_r']} | {r['cuff_wave_px']} | {r['gap_px']} | "
                 f"{r['excess_px']} | {r['fold']:.4f} | {r['runtime_s']} | {', '.join(r['rejected']) or '-'} |")
table = "\n".join(lines)
with open(f"{OUT}/table8b.md", "w") as fh:
    fh.write(table + "\n")
print("\n".join(lines[:6]))
print("done", len(results))
