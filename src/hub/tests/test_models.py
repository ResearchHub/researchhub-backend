from django.test import TestCase

from hub.tests.helpers import create_hub_metadata, create_hub_provider, create_hub_v2


class HubModelsTests(TestCase):
    def test_related_models_accessible(self):
        hub1 = create_hub_v2("Hub 1")
        hub2 = create_hub_v2("Hub 2")
        hub3 = create_hub_v2("Hub 3")

        provider1 = create_hub_provider("Provider 1")
        provider2 = create_hub_provider("Provider 2")

        create_hub_metadata(provider1, hub1)
        create_hub_metadata(provider1, hub2)
        create_hub_metadata(provider2, hub2)
        create_hub_metadata(provider2, hub3)

        actual_hub1_providers = [m.hub_provider.id for m in hub1.metadata.all()]
        expected_hub1_providers = [provider1.id]
        self.assertEqual(actual_hub1_providers, expected_hub1_providers)

        actual_hub2_providers = [m.hub_provider.id for m in hub2.metadata.all()]
        expected_hub2_providers = [provider1.id, provider2.id]
        self.assertEqual(actual_hub2_providers, expected_hub2_providers)

        actual_hub3_providers = [m.hub_provider.id for m in hub3.metadata.all()]
        expected_hub3_providers = [provider2.id]
        self.assertEqual(actual_hub3_providers, expected_hub3_providers)

        self.assertEqual([h.id for h in provider1.hubs.all()], [hub1.id, hub2.id])
        self.assertEqual([h.id for h in provider2.hubs.all()], [hub2.id, hub3.id])
