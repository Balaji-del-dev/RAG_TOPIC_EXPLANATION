"""
WSGI config for config project.

It exposes the WSGI callable as a module-level variable named ``application``.

For more information on this file, see
https://docs.djangoproject.com/en/6.1/howto/deployment/wsgi/
"""

import os

from django.core.wsgi import get_wsgi_application

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')

application = get_wsgi_application()

# Load the security models once at startup (WARMUP_ON_STARTUP=true), not on the
# first user request. wsgi.py is imported by servers only (gunicorn, runserver),
# not by tests or other manage.py commands.
from django.conf import settings  # noqa: E402

if settings.SECURITY_SETTINGS.warmup_on_startup:
    from input_guard.services import get_pipeline  # noqa: E402

    get_pipeline()
