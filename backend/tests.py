import io
import pytest
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.test import TestCase
from rest_framework.test import APIClient
from PIL import Image

from avatars.models import Avatar, Measurements
from catalog.models import Item
from outfits.models import Outfit, OutfitItem


def make_png_bytes(size=(600, 1200), fmt='PNG', color=(180, 120, 200, 200)):
    img = Image.new('RGBA', size, color=color)
    buf = io.BytesIO()
    img.save(buf, format=fmt)
    buf.seek(0)
    return buf


def make_item(name='Test Top', category='top', size=(600, 1200)):
    from django.core.files.base import ContentFile
    item = Item(name=name, category=category,
                region='torso' if category == 'top' else 'legs',
                fit_measure='chest' if category == 'top' else 'hip',
                z_index=20 if category == 'top' else 10)
    png = make_png_bytes(size=size)
    item.image.save(f'{name}.png', ContentFile(png.read()), save=False)
    item.save()
    return item


# ── Auth ──────────────────────────────────────────────────────────────────────

class AuthFlowTest(TestCase):
    def setUp(self):
        self.client = APIClient()

    def test_register_returns_tokens_and_creates_avatar(self):
        res = self.client.post('/api/auth/register', {
            'username': 'alice', 'email': 'alice@example.com', 'password': 'pass1234'
        }, format='json')
        self.assertEqual(res.status_code, 201)
        self.assertIn('access', res.data)
        self.assertIn('refresh', res.data)
        user = User.objects.get(username='alice')
        self.assertTrue(Avatar.objects.filter(user=user).exists())

    def test_register_duplicate_username(self):
        User.objects.create_user('bob', 'bob@example.com', 'pass1234')
        res = self.client.post('/api/auth/register', {
            'username': 'bob', 'email': 'other@example.com', 'password': 'pass1234'
        }, format='json')
        self.assertEqual(res.status_code, 400)

    def test_login_returns_tokens(self):
        User.objects.create_user('carol', 'carol@example.com', 'pass1234')
        res = self.client.post('/api/auth/login', {
            'username': 'carol', 'password': 'pass1234'
        }, format='json')
        self.assertEqual(res.status_code, 200)
        self.assertIn('access', res.data)

    def test_me_requires_auth(self):
        res = self.client.get('/api/auth/me')
        self.assertEqual(res.status_code, 401)

    def test_me_returns_user(self):
        user = User.objects.create_user('dave', 'dave@example.com', 'pass1234')
        self.client.force_authenticate(user=user)
        res = self.client.get('/api/auth/me')
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.data['username'], 'dave')


# ── Ownership / 404 ───────────────────────────────────────────────────────────

class OwnershipTest(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.alice = User.objects.create_user('alice2', 'a@e.com', 'pass')
        self.bob   = User.objects.create_user('bob2',   'b@e.com', 'pass')
        self.alice_avatar = Avatar.objects.create(user=self.alice, name='A')

    def test_other_users_avatar_returns_404(self):
        self.client.force_authenticate(user=self.bob)
        res = self.client.get(f'/api/avatars/{self.alice_avatar.pk}/measurements')
        self.assertEqual(res.status_code, 404)

    def test_own_avatar_ok(self):
        self.client.force_authenticate(user=self.alice)
        res = self.client.get(f'/api/avatars/{self.alice_avatar.pk}/measurements')
        self.assertEqual(res.status_code, 200)


# ── Measurement validation ────────────────────────────────────────────────────

class MeasurementValidationTest(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user('eve', 'eve@e.com', 'pass')
        self.avatar = Avatar.objects.create(user=self.user, name='E')
        self.client.force_authenticate(user=self.user)

    def _post(self, data):
        return self.client.post(
            f'/api/avatars/{self.avatar.pk}/measurements', data, format='json'
        )

    def test_valid_measurements_accepted(self):
        res = self._post({'height': 165, 'weight': 60, 'shoulder': 38,
                          'chest': 88, 'waist': 68, 'hip': 95})
        self.assertEqual(res.status_code, 201)

    def test_height_too_low_rejected(self):
        res = self._post({'height': 100, 'weight': 60, 'shoulder': 38,
                          'chest': 88, 'waist': 68, 'hip': 95})
        self.assertEqual(res.status_code, 400)
        self.assertIn('height', res.data)

    def test_each_save_creates_new_row(self):
        self._post({'height': 165, 'weight': 60, 'shoulder': 38, 'chest': 88, 'waist': 68, 'hip': 95})
        self._post({'height': 166, 'weight': 61, 'shoulder': 38, 'chest': 88, 'waist': 68, 'hip': 95})
        self.assertEqual(Measurements.objects.filter(avatar=self.avatar).count(), 2)

    def test_get_returns_newest_first(self):
        self._post({'height': 165, 'weight': 60, 'shoulder': 38, 'chest': 88, 'waist': 68, 'hip': 95})
        self._post({'height': 170, 'weight': 65, 'shoulder': 40, 'chest': 90, 'waist': 70, 'hip': 95})
        res = self.client.get(f'/api/avatars/{self.avatar.pk}/measurements')
        self.assertEqual(res.data[0]['height'], 170)


# ── Item validation ───────────────────────────────────────────────────────────

class ItemValidationTest(TestCase):
    def test_top_must_have_torso_and_chest(self):
        item = Item(name='T', category='top', region='legs', fit_measure='hip', z_index=20)
        with self.assertRaises(ValidationError):
            item.full_clean()

    def test_bottom_must_have_legs_and_hip(self):
        item = Item(name='B', category='bottom', region='torso', fit_measure='chest', z_index=10)
        with self.assertRaises(ValidationError):
            item.full_clean()

    def test_image_must_be_png(self):
        from django.core.files.base import ContentFile
        img_bytes = make_png_bytes(fmt='PNG').read()
        # Rename to .jpg so we can test the format validator via save path
        # (validator checks Pillow format, not file extension)
        item = Item(name='I', category='top', region='torso', fit_measure='chest', z_index=20)
        item.image.save('test.png', ContentFile(img_bytes), save=False)
        # Should NOT raise for valid PNG
        item.full_clean()

    def test_wrong_size_rejected(self):
        from django.core.files.base import ContentFile
        from django.core.exceptions import ValidationError
        img_bytes = make_png_bytes(size=(100, 200)).read()
        item = Item(name='S', category='top', region='torso', fit_measure='chest', z_index=20)
        item.image.save('small.png', ContentFile(img_bytes), save=False)
        with self.assertRaises(ValidationError):
            item.full_clean()


# ── Outfit rules ──────────────────────────────────────────────────────────────

class OutfitRulesTest(TestCase):
    def setUp(self):
        self.user   = User.objects.create_user('frank', 'f@e.com', 'pass')
        self.avatar = Avatar.objects.create(user=self.user, name='F')
        self.top1   = make_item('Top A', 'top')
        self.top2   = make_item('Top B', 'top')
        self.bottom = make_item('Bottom A', 'bottom')
        self.outfit = Outfit.objects.create(user=self.user, avatar=self.avatar, name='Look')

    def test_can_add_one_top_and_one_bottom(self):
        OutfitItem.objects.create(outfit=self.outfit, item=self.top1)
        OutfitItem.objects.create(outfit=self.outfit, item=self.bottom)
        self.assertEqual(self.outfit.outfit_items.count(), 2)

    def test_second_top_rejected(self):
        OutfitItem.objects.create(outfit=self.outfit, item=self.top1)
        with self.assertRaises(ValidationError):
            OutfitItem.objects.create(outfit=self.outfit, item=self.top2)

    def test_outfit_delete_via_api(self):
        client = APIClient()
        client.force_authenticate(user=self.user)
        res = client.delete(f'/api/outfits/{self.outfit.pk}')
        self.assertEqual(res.status_code, 204)
        self.assertFalse(Outfit.objects.filter(pk=self.outfit.pk).exists())

    def test_other_user_cannot_delete_outfit(self):
        other = User.objects.create_user('grace', 'g@e.com', 'pass')
        client = APIClient()
        client.force_authenticate(user=other)
        res = client.delete(f'/api/outfits/{self.outfit.pk}')
        self.assertEqual(res.status_code, 404)
