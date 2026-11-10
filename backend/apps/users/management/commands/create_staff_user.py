"""Create a staff user (or promote an existing one) for the staff pages (/staff/avatars).

    manage.py create_staff_user --email staff@example.com

Password: env STAFF_PASSWORD if set, otherwise asked twice at the prompt. Never pass it on the command line
and never commit it. Staff are exempt from the per-user daily garment AI limit, but the AI check still runs
(AI_DEV_BYPASS is not touched). Staff are not superusers (no Django admin rights).
"""
import getpass
import os

from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError

from apps.users.models import User


class Command(BaseCommand):
    help = "Create or promote a staff user; password from STAFF_PASSWORD or a prompt"

    def add_arguments(self, parser):
        parser.add_argument("--email", required=True)

    def handle(self, *args, email, **options):
        password = os.environ.get("STAFF_PASSWORD")
        if not password:
            password = getpass.getpass("Password: ")
            if password != getpass.getpass("Password (again): "):
                raise CommandError("passwords do not match")
        if len(password) < 8:
            raise CommandError("password must be at least 8 characters")
        user = User.objects.filter(email__iexact=email).first()
        try:
            validate_password(password, user)
        except ValidationError as e:
            raise CommandError("; ".join(e.messages))
        if user is None:
            user = User.objects.create_user(email=email, password=password, is_staff=True, is_adult_confirmed=True)
            self.stdout.write(self.style.SUCCESS(f"staff user created: {user.email} (id {user.pk})"))
        else:
            user.is_staff = True
            user.set_password(password)
            user.save(update_fields=["is_staff", "password"])
            self.stdout.write(self.style.SUCCESS(f"existing user promoted to staff, password reset: {user.email}"))
