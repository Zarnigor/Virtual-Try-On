"""Fit check calibration report (docs/11 "Calibration"; read-only, writes nothing to the DB).

Garments with complete sizes x the avatars of a matching gender (docs/09 #97), with the avatar's stored sizes through
the same fit gate as POST tryon/ (fit_gate.sizes_from + run_gate). Optional cases (model photos with a known height and
worn size) check only the height-dependent zones. CLI: tools/fit_check/matrix.py.
"""
from apps.garments.size_checks import sizes_complete

from . import fit_gate
from .views import garment_fits_sex

AVATAR_KEYS = ("height_cm", "chest", "waist", "hip", "shoulder_width")


def overall(result) -> str:
    """fits | katta (rendered with a warning) | mos emas (rejected) | the missing-size code."""
    if result.code:
        return result.code
    if not result.fits:
        return "mos emas"
    return "katta" if result.warnings else "fits"


def zone_text(c) -> str:
    return f"{c.zone} {c.ease_cm:+.1f} {c.verdict}"


def missing_avatar_keys(avatar) -> list:
    sizes = fit_gate.sizes_from(avatar)
    return [k for k in AVATAR_KEYS if k not in sizes]


def build_matrix(garments, avatars) -> dict:
    garments, avatars = list(garments), list(avatars)
    skipped_garments = [{"garment_id": g.pk, "reason": "no sizes" if not g.sizes else "sizes incomplete"}
                        for g in garments if not sizes_complete(g.type, g.sizes)]
    rows = [g for g in garments if sizes_complete(g.type, g.sizes)]
    skipped_avatars = [{"avatar_id": a.pk, "reason": "missing " + ", ".join(m)}
                       for a in avatars if (m := missing_avatar_keys(a))]
    cells = []
    for g in rows:
        for a in avatars:
            if not garment_fits_sex(g.gender, a.sex):
                continue  # other gender: not shown (docs/09 #97)
            r = fit_gate.check_garment(g, fit_gate.sizes_from(a))
            cells.append({
                "garment_id": g.pk, "avatar_id": a.pk, "overall": overall(r),
                "text": " | ".join(zone_text(c) for c in r.checks) if r.checks else f"{r.code}: {', '.join(r.keys)}",
                "checks": [{"zone": c.zone, "ease_cm": c.ease_cm, "verdict": c.verdict, "garment_cm": c.garment_cm,
                            "body_cm": c.body_cm, "limit_cm": c.limit_cm} for c in r.checks],
                "code": r.code, "keys": r.keys,
            })
    return {
        "avatars": [{"id": a.pk, "sex": a.sex, "build": a.build, "sizes": fit_gate.sizes_from(a)} for a in avatars],
        "garments": [{"id": g.pk, "type": g.type, "gender": g.gender, "fit_mode": g.fit_mode, "stretch": g.stretch,
                      "sizes": g.sizes} for g in rows],
        "cells": cells, "skipped_garments": skipped_garments, "skipped_avatars": skipped_avatars,
    }


def check_cases(cases, garments_by_id) -> list:
    """cases: [{garment, model_height_cm, worn_size, expected}]. Per case the height-dependent zones (inseam) and,
    for information only, the garment length; `failed` = expected "fits" but a height zone is too_small."""
    out = []
    for i, case in enumerate(cases):
        g = garments_by_id.get(case.get("garment"))
        item = {"case": i, "garment_id": case.get("garment"), "model_height_cm": case.get("model_height_cm"),
                "worn_size": case.get("worn_size"), "expected": case.get("expected")}
        if g is None:
            out.append({**item, "error": "garment not found"})
            continue
        if not isinstance(item["model_height_cm"], (int, float)):
            out.append({**item, "error": "model_height_cm missing"})
            continue
        checks = fit_gate.height_only_checks(g, item["model_height_cm"])
        failing = [c for c in checks if c.verdict == "too_small"]
        out.append({
            **item, "type": g.type,
            "checks": [{"zone": c.zone, "garment_cm": c.garment_cm, "body_cm": c.body_cm, "ease_cm": c.ease_cm,
                        "verdict": c.verdict} for c in checks],
            "length_cm": (g.sizes or {}).get("length") if g.type == "tshirt" else None,  # info, not a rule
            "failed": item["expected"] == "fits" and bool(failing),
            "failed_zones": [c.zone for c in failing] if item["expected"] == "fits" else [],
        })
    return out


def render_md(report: dict, cases=None) -> str:
    avatars = report["avatars"]
    cells = {(c["garment_id"], c["avatar_id"]): c for c in report["cells"]}
    lines = ["# Fit check matrix", "",
             "Avatar sizes (stored, same path as the fit gate): " + "; ".join(
                 f"#{a['id']} {a['sex']} {a['build']} {a['sizes']}" for a in avatars), "",
             "| garment | " + " | ".join(f"#{a['id']} {a['sex']} {a['build']}" for a in avatars) + " |",
             "|---|" + "---|" * len(avatars)]
    for g in report["garments"]:
        row = [f"#{g['id']} {g['type']} {g['gender']} {g['fit_mode']}{' stretch' if g['stretch'] else ''}"]
        for a in avatars:
            c = cells.get((g["id"], a["id"]))
            row.append("—" if c is None else f"**{c['overall']}**: {c['text']}")
        lines.append("| " + " | ".join(row) + " |")
    lines += ["", "## Skipped"]
    lines += [f"- garment #{s['garment_id']}: {s['reason']}" for s in report["skipped_garments"]] or ["- garments: none"]
    lines += [f"- avatar #{s['avatar_id']}: {s['reason']}" for s in report["skipped_avatars"]] or ["- avatars: none"]
    if cases is not None:
        lines += ["", "## Cases (height-dependent zones only)", ""]
        for c in cases:
            head = f"- case {c['case']}: garment #{c['garment_id']}, model {c['model_height_cm']} cm, " \
                   f"worn {c['worn_size']}, expected {c['expected']}"
            if "error" in c:
                lines.append(f"{head}: ERROR {c['error']}")
                continue
            zones = ", ".join(f"{z['zone']} {z['garment_cm']} vs {z['body_cm']} ({z['ease_cm']:+.1f} {z['verdict']})"
                              for z in c["checks"]) or "no height zone"
            info = f"; length {c['length_cm']} cm (info, not a rule)" if c["length_cm"] is not None else ""
            fail = f" **FAILS on {', '.join(c['failed_zones'])}**" if c["failed"] else ""
            lines.append(f"{head}: {zones}{info}{fail}")
    return "\n".join(lines) + "\n"
