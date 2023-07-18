from hub.models import Hub, HubV2
from slugify import slugify


class TestData:
    hub_name = 'Hub Name'


def build_hub_data(name):
    return {
        'name': name
    }


def create_hub(name=TestData.hub_name):
    return Hub.objects.create(
        name=name
    )


def subscribe(hub, user):
    hub.subscribers.add(user)
    hub.save()
    return hub


def create_hub_v2(name=TestData.hub_name):
    return HubV2.objects.create(
        id=slugify(name),
        display_name=name,
        description=name
    )