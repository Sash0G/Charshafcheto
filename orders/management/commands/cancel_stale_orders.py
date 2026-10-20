from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from orders.models import Order
from orders.services import cancel_unpaid


class Command(BaseCommand):
    help = "Cancel card orders that were never paid and release their stock. Run from cron every 15 minutes."

    def add_arguments(self, parser):
        parser.add_argument("--hours", type=int, default=2)

    def handle(self, *args, hours, **opts):
        cutoff = timezone.now() - timedelta(hours=hours)
        stale = Order.objects.filter(status=Order.STATUS_PENDING_PAYMENT, created_at__lt=cutoff)
        n = 0
        for order in stale:
            cancel_unpaid(order, reason="Автоматично отказана — плащането не е завършено.")
            n += 1
        self.stdout.write(f"Отказани {n} неплатени поръчки.")
