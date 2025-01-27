from hub.models import Hub


class TestData:
    hub_name = "Hub Name"


def build_hub_data(name):
    return {"name": name}


def create_hub(name=TestData.hub_name, namespace=None):
    return Hub.objects.create(name=name, namespace=namespace)


def subscribe(hub, user):
    hub.subscribers.add(user)
    hub.save()
    return hub
