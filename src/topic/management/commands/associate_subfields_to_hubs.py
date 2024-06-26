"""
The purpose of this script is to associate hubs with subfields.
This is a prerequisite for calculating reputation since only specific
hubs that are tagged with subfields are used for reputation calculation.
"""

from django.core.management.base import BaseCommand

from hub.models import Hub
from topic.models import Subfield


class Command(BaseCommand):
    help = "Associate hubs with subfields (Used for rep)"

    def handle(self, *args, **kwargs):
        subfields = Subfield.objects.all()

        for subfield in subfields:
            try:
                hub = Hub.objects.get(subfield=subfield)
            except Hub.DoesNotExist:
                hub, created = Hub.objects.get_or_create(
                    name=subfield.display_name.lower(),
                    defaults={"subfield": subfield, "is_used_for_rep": True},
                )
                if created:
                    print(
                        f"Created new hub {hub.name} and associated with subfield {subfield.display_name}."
                    )
                else:
                    hub.subfield = subfield
                    hub.is_used_for_rep = True
                    hub.save()
                    print(
                        f"Updated hub {hub.name} with subfield {subfield.display_name}"
                    )
