"""Demo mode: build_demo renders all pairs; DEMO_MODE serves them without Celery; off = nothing changes."""
import json
import tempfile
from pathlib import Path
from unittest import mock

import cv2
from django.core.files.base import ContentFile
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import override_settings

from apps.avatars.models import Avatar
from apps.garments.models import Garment
from apps.jobs.models import Job
from apps.outfits.models import Outfit
from apps.testing import MediaTestCase
from apps.tryon_engine import demo
from apps.tryon_engine.tests import avatar, pants, tshirt


def png(img):
    return cv2.imencode(".png", img)[1].tobytes()


class DemoTests(MediaTestCase):
    def setUp(self):
        super().setUp()
        self.user = self.make_user()
        img, lm = avatar()
        self.avatars = []
        for sex in ("male", "female"):
            a = Avatar(sex=sex, build="average", landmarks=lm)
            a.image.save(f"a_{sex}.png", ContentFile(png(img)), save=True)
            self.avatars.append(a)
        self.folder = Path(tempfile.mkdtemp())
        for name, (gimg, glm), gtype in (("shirt", tshirt(), "tshirt"), ("jeans", pants(), "pants")):
            (self.folder / f"{name}.png").write_bytes(png(gimg))
            (self.folder / f"{name}.json").write_text(json.dumps({"type": gtype, "name": name.title(), "landmarks": glm}))

    def build(self):
        call_command("build_demo", garments=str(self.folder), stdout=open("/dev/null", "w"))
        return demo.load_manifest()

    def test_build_renders_every_pair_and_makes_catalog_garments(self):
        m = self.build()
        self.assertEqual(len(m["results"]), 2 * 3)  # 2 avatars x (shirt, jeans, shirt+jeans)
        for rel in m["results"].values():
            img = cv2.imread(str(Path(self.settings_media()) / rel))
            self.assertEqual(img.shape[:2], (1200, 600))
        shirt = Garment.objects.get(pk=m["garments"]["shirt"])
        self.assertEqual((shirt.owner, shirt.visibility, shirt.status, shirt.name), (None, "public", "approved", "Shirt"))
        m2 = self.build()  # a rebuild updates the same catalog rows
        self.assertEqual(m2["garments"], m["garments"])
        self.assertEqual(Garment.objects.count(), 2)

    def test_bad_landmarks_fail_the_build(self):
        meta = json.loads((self.folder / "shirt.json").read_text())
        meta["landmarks"]["shoulder"]["left_x"] = 999
        (self.folder / "shirt.json").write_text(json.dumps(meta))
        with self.assertRaises(CommandError):
            self.build()

    @override_settings(DEMO_MODE=True)
    @mock.patch("apps.tryon_engine.views.run_tryon.delay")
    def test_demo_pair_is_served_without_celery(self, delay):
        m = self.build()
        self.login(self.user)
        ids = [m["garments"]["jeans"], m["garments"]["shirt"]]
        r = self.client.post("/api/tryon/", {"base": "avatar", "avatar_id": self.avatars[0].pk,
                                             "garment_ids": ids}, format="json")
        self.assertEqual(r.status_code, 202)
        delay.assert_not_called()
        job = Job.objects.get(pk=r.data["job_id"])
        self.assertEqual((job.status, job.result["demo"]), ("done", True))
        outfit = Outfit.objects.get(pk=r.data["outfit_id"])
        expected = (Path(self.settings_media()) / m["results"][demo.pair_key(self.avatars[0].pk, ids)]).read_bytes()
        self.assertEqual(outfit.result_image.read(), expected)
        outfit.delete()  # the outfit's copy goes; the demo file stays
        self.assertIsNotNone(demo.lookup(self.avatars[0].pk, ids))

    @override_settings(DEMO_MODE=True)
    @mock.patch("apps.tryon_engine.views.run_tryon.delay")
    def test_pair_not_in_the_demo_takes_the_normal_path(self, delay):
        self.build()
        own = Garment(owner=self.user, type="tshirt", landmarks=tshirt()[1])
        own.image.save("own.png", ContentFile(png(tshirt()[0])), save=True)
        self.login(self.user)
        r = self.client.post("/api/tryon/", {"base": "avatar", "avatar_id": self.avatars[0].pk,
                                             "garment_ids": [own.pk]}, format="json")
        self.assertEqual(r.status_code, 202)
        delay.assert_called_once()

    @override_settings(DEMO_MODE=False)
    @mock.patch("apps.tryon_engine.views.run_tryon.delay")
    def test_without_demo_mode_nothing_changes(self, delay):
        m = self.build()
        self.login(self.user)
        r = self.client.post("/api/tryon/", {"base": "avatar", "avatar_id": self.avatars[0].pk,
                                             "garment_ids": [m["garments"]["shirt"]]}, format="json")
        self.assertEqual(r.status_code, 202)
        delay.assert_called_once()
        self.assertEqual(Job.objects.get(pk=r.data["job_id"]).status, "queued")
        self.assertEqual(self.client.get("/api/config/").data, {"demo_mode": False})

    @override_settings(DEMO_MODE=True)
    def test_config_is_public(self):
        self.assertEqual(self.client.get("/api/config/").data, {"demo_mode": True})

    def settings_media(self):
        from django.conf import settings
        return settings.MEDIA_ROOT
