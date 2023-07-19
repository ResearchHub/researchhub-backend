from slugify import slugify

from hub.models import Hub
from hub.related_models import HubMetadata, HubProvider, HubV2


class TestData:
    hub_name = "Hub Name"


def build_hub_data(name):
    return {"name": name}


def create_hub(name=TestData.hub_name):
    return Hub.objects.create(name=name)


def subscribe(hub, user):
    hub.subscribers.add(user)
    hub.save()
    return hub


def create_hub_v2(name=TestData.hub_name):
    return HubV2.objects.create(id=slugify(name), display_name=name, description=name)


def create_hub_provider(name="Test Provider", is_user=False):
    return HubProvider.objects.create(
        id=slugify(name), display_name=name, is_user=is_user
    )


def create_hub_metadata(provider: HubProvider, hub: HubV2):
    return HubMetadata.objects.create(
        hub=hub,
        hub_provider=provider,
        raw_data=f'{{"provider":"{provider.id}", "hub":"{hub.id}"}}',
    )
