"""
Create two demo users (alice and bob) with API tokens, for local testing only.

    python manage.py create_demo_users

Two users make the ownership rules visible: bob gets 404 for alice's conversations.
"""

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from rest_framework.authtoken.models import Token

DEMO_USERS = ["alice", "bob"]
DEMO_PASSWORD = "demo-password-123"


class Command(BaseCommand):
    help = "Create demo users alice and bob (development only)."

    def handle(self, *args, **options):
        if not settings.DEBUG:
            raise CommandError("Demo users are for development only (DJANGO_DEBUG=true).")
        User = get_user_model()
        for username in DEMO_USERS:
            user, created = User.objects.get_or_create(username=username)
            if created:
                user.set_password(DEMO_PASSWORD)
                user.save()
            token, _ = Token.objects.get_or_create(user=user)
            self.stdout.write(f"{username:<6} password={DEMO_PASSWORD}  token={token.key}  {'created' if created else 'exists'}")
