"""Benchmark round 17: the finish pass (edges, shading, contact shadow) on the production T-shirt render
(docs/06 "Finish pass, round 17", NOT production: every effect is off by default).

    docker compose exec -T backend rm -rf /tmp/warp_benchmark
    docker compose exec -T [-e VARIANTS=off,all] [-e GARMENTS=28,43] [-e ZOOMS=0] backend python manage.py shell \
        < tools/warp-benchmark/run_finish17.py
    docker compose cp backend:/tmp/warp_benchmark/. tools/warp-benchmark/out/

Reads the garments and avatars from the DB and renders through warp.render_tryon with the settings flags, as the
worker does (gender rule not applied). Adapt #28, #43, #40 and keep_shape #44, #45 x every avatar.
Columns = VARIANTS (render_tryon keyword overrides on top of the flags); "off" is the reference.
Metrics per run and variant, on the T-shirt layer as it is composited (debug["tshirt_final"]) and the final image:
- hard edge px: layer px with alpha >= 128 that have a 4-neighbour with alpha < 26 (a 0 / 1 alpha step).
- new holes: figure px the reference covers (alpha >= 128) and the variant does not.
- lost / gained: covered px (alpha >= 128) of the reference missing in the variant / new in the variant.
- hard cuff px: the same count on the arm overlay weight (debug["arm_weight"]), neighbours covered by the garment
  only (the arm pasted over the sleeve with a 0 / 1 step).
- mean dL fabric: mean change of the grey value on px covered in both (shading), mean dL skin: mean change of the
  grey value on figure px not covered and not head / arm overlay, within 12 px of the garment (contact shadow).
- changed outside: final-image px that differ from the reference farther than 24 px from the garment layer (the
  contact shadow is a Gaussian of sigma 4 px shifted 3 px: its tail ends inside that distance).
GATE per variant: new holes = 0, changed outside = 0. Production gates (docs/09 #107), when both variants of a pair
are in VARIANTS: final image "prod" (the settings flags) = "r17", and "setting_off" (the flags under
TRYON_FINISH=off) = "off", 0 px each: VARIANTS=off,r17,prod,setting_off. With PANTS=1 (docs/09 #108) also
"setting_pants_off" (the flags under TRYON_FINISH_PANTS=0) = "off": VARIANTS=off,r17,prod,setting_off,setting_pants_off.
Round 17b, pants (docs/06 "Finish pass on pants, round 17b"): PANTS=1 GARMENTS=18,48,49,51 renders pants alone
with finish_pants=True in every variant and writes the same files as *_finish17b_*.
Writes out/table_finish17.md, out/results_finish17.json, out/sheet_finish17_<id>.png (rows = avatars, columns =
variants, clean), out/zoom_finish17_<id>.png (first avatar of the garment's sex: 3x crops shoulder / cuff / side /
hem per variant, clean). Exit status 1 when a gate fails.
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

NONE = {"edge_feather": False, "shading": False, "contact_shadows": False, "finish": "r60"}
ALL = {  # every variant sets the four finish keywords itself (the settings default is r17 since docs/09 #107)
    "off": NONE,
    "feather": {**NONE, "edge_feather": True},
    "shading": {**NONE, "shading": True},
    "shadow": {**NONE, "contact_shadows": True},
    "all": {**NONE, "edge_feather": True, "shading": True, "contact_shadows": True},
    "smooth": {**NONE, "edge_feather": True, "finish": "r17"},
    "smooth_shadow": {**NONE, "edge_feather": True, "contact_shadows": True, "finish": "r17"},
    "r17": {"edge_feather": True, "shading": True, "contact_shadows": True, "finish": "r17"},
    "prod": {},  # render_flags as the worker gets them (TRYON_FINISH)
    "setting_off": None,  # render_flags under TRYON_FINISH=off
}
VARIANTS = os.environ.get("VARIANTS", "off,all,smooth,smooth_shadow,r17").split(",")
GARMENTS = [int(v) for v in os.environ.get("GARMENTS", "28,43,40,44,45").split(",")]
PANTS = os.environ.get("PANTS", "0") == "1"  # round 17b: the garments are pants, finish_pants=True in every variant
if PANTS:
    ALL = {k: (v if v is None or k == "prod" else {**v, "finish_pants": True}) for k, v in ALL.items()}
ZOOMS = os.environ.get("ZOOMS", "1") == "1"
H, W = 1200, 600
OUT = "/tmp/warp_benchmark"
Y0, Y1, X0, X1 = (520, 1180, 100, 500) if PANTS else (170, 730, 40, 560)  # sheet crop
Z, ZS = 3, 110  # zoom factor and crop size
TAG = "finish17b" if PANTS else "finish17"
os.makedirs(OUT, exist_ok=True)
flags = render_flags("avatar")
with override_settings(TRYON_FINISH="off"):
    ALL["setting_off"] = render_flags("avatar")
with override_settings(TRYON_FINISH_PANTS=False):
    ALL["setting_pants_off"] = render_flags("avatar")  # docs/09 #108: must equal "off" for pants alone
if not PANTS:
    ALL["r17"] = {**ALL["r17"], "finish_pants": False}
PAIRS = [p for p in (("prod", "r17"), ("setting_off", "off"), ("setting_pants_off", "off"))
         if p[0] in VARIANTS and p[1] in VARIANTS]
pair_diff = {p: 0 for p in PAIRS}


def label(img, text, y=14, scale=0.42):
    for col, th in (((255, 255, 255), 3), ((0, 0, 0), 1)):
        cv2.putText(img, text, (4, y), cv2.FONT_HERSHEY_SIMPLEX, scale, col, th, cv2.LINE_AA)
    return img


def crop(img, cx, cy):
    x0, y0 = int(min(max(cx - ZS // 2, 0), W - ZS)), int(min(max(cy - ZS // 2, 0), H - ZS))
    return cv2.resize(img[y0:y0 + ZS, x0:x0 + ZS], None, fx=Z, fy=Z, interpolation=cv2.INTER_NEAREST)


def hard_edge(a, where=None):
    cov, bare = a >= 128, a < 26
    if where is not None:
        bare = bare & where
    nb = np.zeros_like(bare)
    nb[1:] |= bare[:-1]
    nb[:-1] |= bare[1:]
    nb[:, 1:] |= bare[:, :-1]
    nb[:, :-1] |= bare[:, 1:]
    return int((cov & nb).sum())


def zoom_points(a, body_lm):
    """Crop centres on the image's right side: shoulder, cuff, side below the armpit, hem corner. Pants: waist
    corner, hip side, crotch, leg hem."""
    ys, xs = np.where(a >= 128)
    x1, y0, y1 = xs.max(), ys.min(), ys.max()
    if PANTS:
        cx = int(round((xs[ys == y0 + 10].min() + xs[ys == y0 + 10].max()) / 2))
        open_rows = [y for y in range(y0 + 10, y1) if a[y, cx] < 128]
        cy = open_rows[0] if open_rows else (y0 + y1) // 2
        hip = y0 + (cy - y0) * 2 // 3
        return {"waist": (xs[ys == y0 + 8].max() - 30, y0 + 20), "hip": (xs[ys == hip].max() - 10, hip),
                "crotch": (cx, cy + 15), "hem": (xs[ys == y1 - 6].max() - 25, y1 - 20)}
    cuff_y = int(ys[xs >= x1 - 3].max())
    mid = (cuff_y + y1) // 2
    return {"shoulder": (x1 - 45, y0 + 60), "cuff": (x1 - 35, cuff_y), "side": (xs[ys == mid].max(), mid),
            "hem": (xs[ys == y1 - 6].max() - 30, y1 - 20)}


avatars = sorted(Avatar.objects.all(), key=lambda a: a.pk)
results, fails = [], []
for gid in GARMENTS:
    g = Garment.objects.get(pk=gid)
    g_img = cv2.imread(g.image.path, cv2.IMREAD_UNCHANGED)
    glm = engine_landmarks(g.type, g.landmarks)
    rows, zoom_rows = [], []
    for av in avatars:
        who = f"{av.sex[0]}-{av.build}"
        base = cv2.imread(av.image.path, cv2.IMREAD_UNCHANGED)
        base_r = cv2.resize(warp._bgra(base), (W, H))
        mask = warp.figure_mask(base_r)
        out = {}
        for name in VARIANTS:
            t0 = time.perf_counter()
            rgb, _, dbg = warp.render_tryon(base, av.landmarks, [(g.type, g_img, glm)], H, W,
                                            fit_modes={g.type: g.fit_mode}, **{**flags, **ALL[name]})
            dbg["tshirt_final"] = dbg["final_layers"][g.type]
            out[name] = (rgb, dbg, time.perf_counter() - t0)
        for pr_ in PAIRS:  # docs/09 #107 gates: production = the benchmark call, setting off = before
            pair_diff[pr_] += int((out[pr_[0]][0] != out[pr_[1]][0]).any(2).sum())
        ref_rgb, ref_dbg, _ = out["off"] if "off" in out else out[VARIANTS[0]]
        a0 = ref_dbg["tshirt_final"][:, :, 3]
        c0 = a0 >= 128
        near = cv2.dilate((a0 > 0).astype(np.uint8), np.ones((25, 25), np.uint8)) > 0
        far = cv2.dilate((a0 > 0).astype(np.uint8), np.ones((49, 49), np.uint8)) > 0
        grey0 = cv2.cvtColor(ref_rgb, cv2.COLOR_BGR2GRAY).astype(np.float32)
        over = (ref_dbg["head_overlay"] > 0.02) | ref_dbg["arm_mask"]
        for name in VARIANTS:
            rgb, dbg, sec = out[name]
            a = dbg["tshirt_final"][:, :, 3]
            c = a >= 128
            grey = cv2.cvtColor(rgb, cv2.COLOR_BGR2GRAY).astype(np.float32)
            skin = mask & ~c & ~c0 & ~over & near
            rec = {"garment": gid, "fit": g.fit_mode, "who": who, "variant": name, "hard_edge": hard_edge(a),
                   "hard_cuff": hard_edge(dbg["arm_weight"] * 255, c),
                   "new_holes": int((mask & c0 & ~c).sum()), "lost": int((c0 & ~c).sum()),
                   "gained": int((c & ~c0).sum()),
                   "dl_fabric": round(float((grey - grey0)[c & c0 & ~over].mean()), 2),
                   "dl_skin": round(float((grey - grey0)[skin].mean()), 2) if skin.any() else 0.0,
                   "changed_outside": int(((rgb != ref_rgb).any(2) & ~far).sum()), "runtime": round(sec, 3)}
            bad = [f"{k} {rec[k]}" for k in ("new_holes", "changed_outside") if rec[k]]
            if bad:
                fails.append(f"#{gid} {who} {name}: " + ", ".join(bad))
            results.append(rec)
            print(json.dumps(rec))
        rows.append(np.hstack([label(out[n][0][Y0:Y1, X0:X1].copy(), f"#{gid} {who} {n}") for n in VARIANTS]))
        if ZOOMS and (av.sex[0] == (g.gender or "m")[0] or g.gender == "unisex") and av.build == "average" \
                and not zoom_rows:
            pts = zoom_points(a0, av.landmarks)
            for part, (cx, cy) in pts.items():
                zoom_rows.append(np.hstack([label(crop(out[n][0], cx, cy), f"{part} {n} #{gid} {who}")
                                            for n in VARIANTS]))
    cv2.imwrite(f"{OUT}/sheet_{TAG}_{gid}.png", np.vstack(rows))
    if zoom_rows:
        cv2.imwrite(f"{OUT}/zoom_{TAG}_{gid}.png", np.vstack(zoom_rows))

with open(f"{OUT}/results_{TAG}.json", "w") as fh:
    json.dump({"runs": results, "fails": fails}, fh, indent=1)

cols = ("hard_edge", "hard_cuff", "new_holes", "lost", "gained", "dl_fabric", "dl_skin", "changed_outside", "runtime")
lines = ["| garment | variant | runs | hard edge px | hard cuff px | new holes | lost px | gained px | mean dL fabric | "
         "mean dL skin near | changed outside | runtime s mean |", "|" + "---|" * 12]
for gid in GARMENTS + ["all"]:
    for name in VARIANTS:
        rs = [r for r in results if r["variant"] == name and (gid == "all" or r["garment"] == gid)]
        s = {k: sum(r[k] for r in rs) for k in cols}
        lines.append(f"| {'#' + str(gid) if gid != 'all' else 'all'} | {name} | {len(rs)} | {s['hard_edge']} | "
                     f"{s['hard_cuff']} | {s['new_holes']} | {s['lost']} | {s['gained']} | "
                     f"{s['dl_fabric'] / len(rs):.2f} | {s['dl_skin'] / len(rs):.2f} | {s['changed_outside']} | "
                     f"{s['runtime'] / len(rs):.3f} |")
lines += ["", f"GATE (new holes 0, changed outside 0): {len(fails)} / {len(results)} runs fail"]
for (a_, b_), px in pair_diff.items():
    lines.append(f"GATE final image {a_} vs {b_}: {px} px differ over {len(results) // len(VARIANTS)} renders")
    if px:
        fails.append(f"{a_} vs {b_}: {px} px")
lines += [f"- {f}" for f in fails]
with open(f"{OUT}/table_{TAG}.md", "w") as fh:
    fh.write("\n".join(lines) + "\n")
print("\n".join(lines))
if fails:
    sys.exit(1)
