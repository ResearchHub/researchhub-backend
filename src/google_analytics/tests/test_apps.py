from django.test import TestCase

from google_analytics.apps import GoogleAnalytics, Hit


class GoogleAnalyticsAppsTests(TestCase):

    def setUp(self):
        self.ga = GoogleAnalytics()

    def test_hit_urlencoded(self):
        fields = Hit.build_event_fields(
            category='default_category',
            action='default_action',
            label='default_label',
            value=0
        )
        hit = Hit(Hit.EVENT, None, fields)
        result = self.ga.build_hit_urlencoded(hit)
        expected = 'v=1&t=event&tid=UA-106669204-1&cid=django&ua=Opera%2F9.80&npa=1&ds=django&qt=0&ni=0&ec=default_category&ea=default_action&el=default_label&ev=0'  # noqa
        self.assertEqual(result, expected)
