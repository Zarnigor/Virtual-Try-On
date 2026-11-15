"""Check renders through the real path: POST /api/tryon/ -> Celery job -> GET /api/jobs/{id}/ -> the outfit image.

    docker compose restart worker          # the worker must run the code under test
    docker compose exec -T -e TAG=before backend python manage.py shell < tools/tryon_check/post_path.py
    docker compose exec -T -e TAG=after  backend python manage.py shell < tools/tryon_check/post_path.py
    docker compose exec -T -e SHEET=1    backend python manage.py shell < tools/tryon_check/post_path.py
    docker compose cp backend:/tmp/tryon_post/. tools/tryon_check/out/post_path/

T-shirts GARMENTS (default 28, 43, 40, 44, 45) on every avatar the API accepts (the garment gender rule, docs/09 #97:
a male garment is refused on a female avatar with 400 GENDER_MISMATCH, listed as "refused"). Requests are made as
the garment's owner (private garments); every outfit this script creates is deleted again (its image with it).
Writes /tmp/tryon_post/<TAG>/<garment>_<avatar>.png and results.json (job result, wall time per job).
SHEET=1: /tmp/tryon_post/sheet_<garment>.png (before | after per avatar, 2x, clean) and diff px per pair.
"""
import json
import os
import time
import urllib.error
import urllib.request

import cv2
import numpy as np
from rest_framework_simplejwt.tokens import RefreshToken

from apps.avatars.models import Avatar
from apps.garments.models import Garment
from apps.jobs.models import Job
from apps.outfits.models import Outfit

API = "http://localhost:8000/api"
GARMENTS = [int(v) for v in os.environ.get("GARMENTS", "28,43,40,44,45").split(",")]
OUT = "/tmp/tryon_post"
TAG = os.environ.get("TAG", "after")


def call(method, path, token, body=None):
    req = urllib.request.Request(API + path, method=method, data=None if body is None else json.dumps(body).encode(),
                                 headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")


def who(a):
    return f"{a.sex[0]}-{a.build}"


def label(img, text):
    for col, th in (((255, 255, 255), 3), ((0, 0, 0), 1)):
        cv2.putText(img, text, (6, 22), cv2.FONT_HERSHEY_SIMPLEX, 0.6, col, th, cv2.LINE_AA)
    return img


avatars = sorted(Avatar.objects.all(), key=lambda a: a.pk)
if os.environ.get("SHEET") == "1":
    summary = []
    for gid in GARMENTS:
        rows = []
        for a in avatars:
            pair = [cv2.imread(f"{OUT}/{t}/{gid}_{who(a)}.png") for t in ("before", "after")]
            if pair[0] is None or pair[1] is None:
                continue
            y0, y1 = max(int(a.landmarks["neck"]["y"]) - 40, 0), min(int(a.landmarks["crotch"]["y"]) + 40, 1200)
            diff = int((pair[0] != pair[1]).any(2).sum())
            summary.append({"garment": gid, "avatar": who(a), "diff_px": diff})
            rows.append(np.hstack([label(cv2.resize(p[y0:y1, 60:540], None, fx=2, fy=2, interpolation=cv2.INTER_NEAREST),
                                         f"{t} #{gid} {who(a)}") for t, p in zip(("before", "after"), pair)]))
        if rows:
            w = max(r.shape[1] for r in rows)
            cv2.imwrite(f"{OUT}/sheet_{gid}.png", np.vstack(
                [np.pad(r, ((0, 0), (0, w - r.shape[1]), (0, 0)), constant_values=255) for r in rows]))
    print(json.dumps(summary))
else:
    os.makedirs(f"{OUT}/{TAG}", exist_ok=True)
    results = []
    for gid in GARMENTS:
        g = Garment.objects.get(pk=gid)
        token = str(RefreshToken.for_user(g.owner).access_token)
        for a in avatars:
            rec = {"garment": gid, "avatar": who(a), "fit_mode": g.fit_mode}
            results.append(rec)
            t0 = time.perf_counter()
            status, body = call("POST", "/tryon/", token, {"base": "avatar", "avatar_id": a.pk, "garment_ids": [gid]})
            if status != 202:
                rec.update(refused=status, code=body.get("code") or body.get("detail"))
                print(json.dumps(rec))
                continue
            rec["engine_asked"] = body.get("engine")
            try:
                job = None
                for _ in range(240):
                    time.sleep(0.25)
                    status, job = call("GET", f"/jobs/{body['job_id']}/", token)
                    if job.get("status") in ("done", "failed", "succeeded", "completed"):
                        break
                rec.update(job_status=job.get("status"), result=job.get("result"), wall_s=round(time.perf_counter() - t0, 2),
                           error=job.get("error_code"))
                outfit = Outfit.objects.get(pk=body["outfit_id"])
                if outfit.result_image:
                    img = cv2.imread(outfit.result_image.path, cv2.IMREAD_UNCHANGED)
                    cv2.imwrite(f"{OUT}/{TAG}/{gid}_{who(a)}.png", img)
            finally:
                Outfit.objects.filter(pk=body["outfit_id"]).delete()  # only what this script created
                Job.objects.filter(pk=body["job_id"]).delete()
            print(json.dumps(rec, default=str))
    with open(f"{OUT}/{TAG}/results.json", "w") as fh:
        json.dump(results, fh, indent=1, default=str)
