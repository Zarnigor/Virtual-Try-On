"""MLS benchmark round 8: sleeve variants r7 | A | B | C on the PRODUCTION tshirt_layer (docs/06, NOT production).

    docker compose cp tools/warp-benchmark backend:/tmp/warp-benchmark
    docker compose exec -T backend python manage.py shell < tools/warp-benchmark/run_sleeve8.py
    docker compose cp backend:/tmp/warp_benchmark/. tools/warp-benchmark/out/

apps.tryon_engine.mls.tshirt_layer(..., "adapt", sleeve_variant=v, debug_map=True) for #28, #43, #40 x all avatars,
k 1.0 (adapt). r7 = round 7 (production default); A = no smid pairs; B = smid_out at the deltoid edge; C = B + cuff_mid.
Metrics: arm_band_skin_px (figure px inside the r7 body-target quad shoulder -> cuff_out -> cuff_in -> armpit, not
covered; the same quad for every variant), cuff_wave_px, gap_px, excess_px, fold, runtime.
Writes out/results8.json, out/table8.md, out/sheet_sleeve8_<id>.png (rows = avatars, columns = r7 | A | B | C,
shoulder-to-cuff crop) and out/crop_sleeve8_worst_<v>.png (2x, the run with the most arm-band skin per variant).
"""
import json
import os
import sys

import cv2
import numpy as np

sys.path.insert(0, "/tmp/warp-benchmark")
import mls as bm  # noqa: E402  (benchmark: metrics, composite)
import mls_fitted as mf  # noqa: E402

from apps.avatars.models import Avatar  # noqa: E402
from apps.garments.landmark_checks import engine_landmarks  # noqa: E402
from apps.garments.models import Garment  # noqa: E402
from apps.tryon_engine import mls as pm  # noqa: E402  (production)
from apps.tryon_engine import warp  # noqa: E402

GARMENTS = [28, 43, 40]
VARIANTS = ["r7", "A", "B", "C"]
H, W = 1200, 600
OUT = "/tmp/warp_benchmark"
CROP_H = 380
os.makedirs(OUT, exist_ok=True)


def label(img, text):
    for col, th in (((255, 255, 255), 3), ((0, 0, 0), 1)):
        cv2.putText(img, text, (6, 18), cv2.FONT_HERSHEY_SIMPLEX, 0.5, col, th, cv2.LINE_AA)
    return img


def crop_y0(blm):
    return max(int(blm["shoulder"]["y"]) - 60, 0)


avatars = list(Avatar.objects.order_by("pk"))
bases, masks = {}, {}
for av in avatars:
    bases[av.pk] = cv2.resize(warp._bgra(cv2.imread(av.image.path, cv2.IMREAD_UNCHANGED)), (W, H))
    masks[av.pk] = warp.figure_mask(bases[av.pk])

results, worst = [], {}
for gid in GARMENTS:
    g = Garment.objects.get(pk=gid)
    gimg = cv2.imread(g.image.path, cv2.IMREAD_UNCHANGED)
    glm = engine_landmarks(g.type, g.landmarks)
    rows = []
    for av in avatars:
        blm, mask = av.landmarks, masks[av.pk]
        cells, quads = [], None
        for v in VARIANTS:
            layer, info = pm.tshirt_layer(gimg, glm, blm, mask, "adapt", H, W, sleeve_variant=v, debug_map=True)
            if v == "r7":
                quads = mf.arm_band_quads(info["pairs"], blm)
            band = mf.arm_band_skin_px(layer, mask, quads)
            cov = mf.coverage_metrics(layer, mask, info, blm)
            rec = {"garment": gid, "avatar": av.pk, "who": f"{av.sex[0]}-{av.build}", "variant": v,
                   "arm_band_skin_px": band["total"], "arm_band_l": band["left"], "arm_band_r": band["right"],
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
            cells.append(label(crop, f"{v} #{gid} {rec['who']} skin {band['total']} wave {rec['cuff_wave_px']}"))
            if v not in worst or band["total"] > worst[v][0]:
                worst[v] = (band["total"], gid, rec["who"], crop.copy())
        rows.append(np.hstack(cells))
    cv2.imwrite(f"{OUT}/sheet_sleeve8_{gid}.png", np.vstack(rows))
for v, (n, gid, who, crop) in worst.items():
    big = cv2.resize(crop, None, fx=2, fy=2, interpolation=cv2.INTER_NEAREST)
    for col, th in (((255, 255, 255), 4), ((0, 0, 0), 1)):  # bottom: the cell label is already at the top
        cv2.putText(big, f"worst {v}: {n} arm-band skin px, #{gid} {who}", (8, big.shape[0] - 14),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.8, col, th, cv2.LINE_AA)
    cv2.imwrite(f"{OUT}/crop_sleeve8_worst_{v}.png", big)

with open(f"{OUT}/results8.json", "w") as fh:
    json.dump(results, fh, default=str, indent=1)

# table: per variant summary, then per run
cols = ["arm_band_skin_px", "gap_px", "excess_px", "fold", "cuff_wave_px", "runtime_s"]
lines = ["| variant | arm-band skin px (sum / max) | gap px (sum) | excess px (sum) | fold (max) | "
         "cuff wave px (median / max) | runtime s (max) | dropped |", "|---|---|---|---|---|---|---|---|"]
for v in VARIANTS:
    rs = [r for r in results if r["variant"] == v]
    waves = [r["cuff_wave_px"] for r in rs if r["cuff_wave_px"] is not None]
    dropped = sorted({x for r in rs for x in r["rejected"] if "smid" in x or "cuff_mid" in x})
    lines.append(f"| {v} | {sum(r['arm_band_skin_px'] for r in rs)} / {max(r['arm_band_skin_px'] for r in rs)} | "
                 f"{sum(r['gap_px'] for r in rs)} | {sum(r['excess_px'] for r in rs)} | "
                 f"{max(r['fold'] for r in rs):.5f} | {np.median(waves):.1f} / {max(waves):.1f} | "
                 f"{max(r['runtime_s'] for r in rs):.2f} | {', '.join(dropped) or '-'} |")
lines += ["", "| garment | avatar | " + " | ".join(f"{v} skin / gap / excess / fold / wave" for v in VARIANTS) + " |",
          "|---|---|" + "---|" * len(VARIANTS)]
for gid in GARMENTS:
    for av in avatars:
        rs = {r["variant"]: r for r in results if r["garment"] == gid and r["avatar"] == av.pk}
        lines.append(f"| #{gid} | {rs['r7']['who']} | " + " | ".join(
            f"{rs[v]['arm_band_skin_px']} / {rs[v]['gap_px']} / {rs[v]['excess_px']} / {rs[v]['fold']:.4f} / "
            f"{rs[v]['cuff_wave_px']}" for v in VARIANTS) + " |")
table = "\n".join(lines)
with open(f"{OUT}/table8.md", "w") as fh:
    fh.write(table + "\n")
print(table)
print("done", len(results))
