from django.core.management import call_command
from django.core.management.base import BaseCommand

from coding.delegations import FeatureDelegationService
from coding.models import FeatureDelegation
from coding.services import CodingSessionService


class Command(BaseCommand):
    help = "Resume restart-interrupted coding work, then run the web server."

    def add_arguments(self, parser):
        parser.add_argument("addrport", nargs="?", default="0.0.0.0:8000")

    def handle(self, *args, **options):
        turns = CodingSessionService.recover_interrupted_turns()
        features = 0
        for delegation in FeatureDelegation.objects.filter(
            status__in=["queued", "coding", "qa", "fixing"]
        ).select_related("session__machine"):
            FeatureDelegationService.reconcile(delegation)
            features += 1
        if turns or features:
            self.stdout.write(
                f"Auto-resumed restart-interrupted coding work: {turns} task(s), "
                f"{features} feature delegation(s)."
            )
        call_command("runserver", options["addrport"], use_reloader=False)
