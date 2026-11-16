"""Benchmark round 17c: the r17 finish on a T-shirt and pants worn together (docs/06 "Finish pass on outfits,
round 17c").

    docker compose exec -T backend rm -rf /tmp/warp_benchmark
    docker compose exec -T [-e OUTFITS=28+51,43+48] backend python manage.py shell < tools/warp-benchmark/run_finish17c.py
    docker compose cp backend:/tmp/warp_benchmark/. tools/warp-benchmark/out/

OUTFITS = T-shirt id + pants id (DB garments), each on every avatar, through warp.render_tryon with the settings
flags (gender rule not applied). Columns:
- off: no finish (finish "r60", the three effects off).
- tshirt: finish "r17" on the T-shirt layer only (production of docs/09 #107).
- both: finish "r17" on the T-shirt and the pants layer.
- prod: the settings flags as the worker gets them.
- setting_pants_off: the settings flags under TRYON_FINISH_PANTS=0 (must equal "tshirt", 0 px).
Metrics against "off": new holes = figure px covered (alpha >= 128) by the T-shirt or the pants layer in "off" and by
neither in the variant, per layer; changed outside = final-image px that differ farther than 24 px from both
layers; pants changed = final-image px that differ on the pants layer farther than 24 px from the T-shirt layer
("tshirt" must give 0 there); diff px between "prod" and PROD_IS (default "both").
GATE: new holes 0, changed outside 0, "tshirt" pants changed 0, prod = PROD_IS 0 px.
Writes out/table_finish17c.md, out/results_finish17c.json, out/sheet_finish17c_<tshirt>_<pants>.png (rows =
avatars, columns = variants, clean), out/zoom_finish17c_<tshirt>_<pants>.png (the average avatar: 3x crops at the
T-shirt hem corners over the waistband, hip, crotch). Exit status 1 when a gate fails.
"""
import json
import os
import sys
import time

import cv2
import numpy as np

from django.test import override_settings

from apps.avatars.models import Avatar
from apps.garments.landmark_checks import engine_landmarks
from apps.garments.models import Garment
from apps.tryon_engine import warp
from apps.tryon_engine.flags import render_flags

with override_settings(TRYON_FINISH_PANTS=False):
    FLAGS_PANTS_OFF = render_flags("avatar")
OUTFITS = [tuple(int(v) for v in o.split("+")) for o in
           os.environ.get("OUTFITS", "28+51,43+48,40+49,44+18,45+51").split(",")]
PROD_IS = os.environ.get("PROD_IS", "both")
R17 = {"edge_feather": True, "shading": True, "contact_shadows": True, "finish": "r17"}
ALL = {"off": {"edge_feather": False, "shading": False, "contact_shadows": False, "finish": "r60"},
       "tshirt": {**R17, "finish_pants": False}, "both": {**R17, "finish_pants": True}, "prod": {},
       "setting_pants_off": FLAGS_PANTS_OFF}
VARIANTS = ["off", "tshirt", "both", "prod", "setting_pants_off"]
H, W = 1200, 600
OUT = "/tmp/warp_benchmark"
Z, ZS = 3, 110
os.makedirs(OUT, exist_ok=True)
flags = render_flags("avatar")


def label(img, text, y=14, scale=0.42):
    for col, th in (((255, 255, 255), 3), ((0, 0, 0), 1)):
        cv2.putText(img, text, (4, y), cv2.FONT_HERSHEY_SIMPLEX, scale, col, th, cv2.LINE_AA)
    return img


def crop(img, cx, cy):
    x0, y0 = int(min(max(cx - ZS // 2, 0), W - ZS)), int(min(max(cy - ZS // 2, 0), H - ZS))
    return cv2.resize(img[y0:y0 + ZS, x0:x0 + ZS], None, fx=Z, fy=Z, interpolation=cv2.INTER_NEAREST)


def load(pk):
    g = Garment.objects.get(pk=pk)
    return g, cv2.imread(g.image.path, cv2.IMREAD_UNCHANGED), engine_landmarks(g.type, g.landmarks)


avatars = sorted(Avatar.objects.all(), key=lambda a: a.pk)
results, fails = [], []
for tid, pid in OUTFITS:
    (t, t_img, tlm), (p, p_img, plm) = load(tid), load(pid)
    assert (t.type, p.type) == ("tshirt", "pants"), (t.type, p.type)
    name_ = f"#{tid} + #{pid}"
    rows, zoom_rows = [], []
    for av in avatars:
        who = f"{av.sex[0]}-{av.build}"
        base = cv2.imread(av.image.path, cv2.IMREAD_UNCHANGED)
        mask = warp.figure_mask(cv2.resize(warp._bgra(base), (W, H)))
        out = {}
        for v in VARIANTS:
            t0 = time.perf_counter()
            rgb, _, dbg = warp.render_tryon(base, av.landmarks, [("tshirt", t_img, tlm), ("pants", p_img, plm)], H, W,
                                            fit_modes={"tshirt": t.fit_mode, "pants": p.fit_mode},
                                            **{**flags, **ALL[v]})
            out[v] = (rgb, dbg, time.perf_counter() - t0)
        rgb0, d0, _ = out["off"]
        ct0, cp0 = (d0["final_layers"][k][:, :, 3] >= 128 for k in ("tshirt", "pants"))
        grow = lambda m: cv2.dilate(m.astype(np.uint8), np.ones((49, 49), np.uint8)) > 0  # noqa: E731
        far_t = ~grow(d0["final_layers"]["tshirt"][:, :, 3] > 0)
        far = far_t & ~grow(d0["final_layers"]["pants"][:, :, 3] > 0)
        for v in VARIANTS[1:]:
            rgb, dbg, sec = out[v]
            ct, cp = (dbg["final_layers"][k][:, :, 3] >= 128 for k in ("tshirt", "pants"))
            diff = (rgb != rgb0).any(2)
            rec = {"outfit": name_, "who": who, "variant": v, "finish": dbg["finish"],
                   "new_holes_tshirt": int((mask & ct0 & ~ct & ~cp).sum()),
                   "new_holes_pants": int((mask & cp0 & ~cp & ~ct).sum()),
                   "changed_outside": int((diff & far).sum()), "pants_changed": int((diff & cp0 & far_t).sum()),
                   "runtime": round(sec, 3), "runtime_off": round(out["off"][2], 3)}
            if v == "prod":
                rec["prod_diff"] = int((rgb != out[PROD_IS][0]).any(2).sum())
            if v == "setting_pants_off":  # docs/09 #108: TRYON_FINISH_PANTS=0 = T-shirts only
                rec["prod_diff"] = int((rgb != out["tshirt"][0]).any(2).sum())
            bad = [f"{k} {rec[k]}" for k in ("new_holes_tshirt", "new_holes_pants", "changed_outside", "prod_diff")
                   if rec.get(k)]
            if v == "tshirt" and rec["pants_changed"]:
                bad.append(f"pants_changed {rec['pants_changed']}")
            if bad:
                fails.append(f"{name_} {who} {v}: " + ", ".join(bad))
            results.append(rec)
            print(json.dumps(rec))
        rows.append(np.hstack([label(out[v][0][170:1180, 60:540].copy(), f"{name_} {who} {v}") for v in VARIANTS]))
        if av.build == "average" and not zoom_rows:
            ys, xs = np.where(ct0)
            y1 = int(ys.max())
            hem = xs[ys == y1 - 6]
            py, px = np.where(cp0)
            cx = int(round((px[py == py.min() + 10].min() + px[py == py.min() + 10].max()) / 2))
            gap = [y for y in range(y1, int(py.max())) if not cp0[y, cx]]
            pts = {"hem left": (hem.min() + 30, y1), "hem right": (hem.max() - 30, y1),
                   "hip": (px[py == y1 + 60].max() - 10, y1 + 60), "crotch": (cx, (gap[0] if gap else y1 + 120) + 15)}
            for part, (qx, qy) in pts.items():
                zoom_rows.append(np.hstack([label(crop(out[v][0], qx, qy), f"{part} {v} {name_} {who}")
                                            for v in VARIANTS]))
    cv2.imwrite(f"{OUT}/sheet_finish17c_{tid}_{pid}.png", np.vstack(rows))
    if zoom_rows:
        cv2.imwrite(f"{OUT}/zoom_finish17c_{tid}_{pid}.png", np.vstack(zoom_rows))

with open(f"{OUT}/results_finish17c.json", "w") as fh:
    json.dump({"runs": results, "fails": fails}, fh, indent=1)
lines = ["| outfit | variant | runs | finish | new holes T-shirt | new holes pants | changed outside | pants changed away "
         "from the T-shirt | px vs target (prod: " + PROD_IS + ", setting_pants_off: tshirt) | runtime s mean (off) |", "|" + "---|" * 10]
for o in [f"#{a} + #{b}" for a, b in OUTFITS] + ["all"]:
    for v in VARIANTS[1:]:
        rs = [r for r in results if r["variant"] == v and (o == "all" or r["outfit"] == o)]
        s = lambda k: sum(r.get(k, 0) for r in rs)  # noqa: E731
        lines.append(f"| {o} | {v} | {len(rs)} | {', '.join(sorted({r['finish'] for r in rs}))} | "
                     f"{s('new_holes_tshirt')} | {s('new_holes_pants')} | {s('changed_outside')} | "
                     f"{s('pants_changed')} | {s('prod_diff') if 'prod_diff' in rs[0] else '-'} | "
                     f"{s('runtime') / len(rs):.3f} ({s('runtime_off') / len(rs):.3f}) |")
lines += ["", f"GATE (new holes 0, changed outside 0, tshirt: pants changed 0, prod = {PROD_IS}): "
              f"{len(fails)} / {len(results)} runs fail"] + [f"- {f}" for f in fails]
with open(f"{OUT}/table_finish17c.md", "w") as fh:
    fh.write("\n".join(lines) + "\n")
print("\n".join(lines))
if fails:
    sys.exit(1)
