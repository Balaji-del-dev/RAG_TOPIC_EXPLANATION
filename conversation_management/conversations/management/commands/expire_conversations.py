"""
10. Session expiration handling, bulk job. Run from cron, e.g. every 15 minutes:

    */15 * * * * cd /app && python manage.py expire_conversations

Marks conversations idle for more than CONVERSATION_IDLE_HOURS as expired and
deletes their LangGraph memory. Chat sessions need no job: Redis expires them.
"""

from django.core.management.base import BaseCommand

from conversations.services.expiration import expire_idle_conversations


class Command(BaseCommand):
    help = "Expire idle conversations and delete their LangGraph memory."

    def handle(self, *args, **options):
        count = expire_idle_conversations()
        self.stdout.write(self.style.SUCCESS(f"Expired {count} idle conversation(s)."))
