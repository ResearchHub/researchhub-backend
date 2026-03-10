from django.test import TestCase

from research_ai.constants import ExpertiseLevel, Gender, Region


class ConstantsTests(TestCase):
    def test_expertise_level_choices(self):
        self.assertEqual(ExpertiseLevel.PHD_POSTDOCS, "phd_postdocs")
        self.assertEqual(ExpertiseLevel.ALL_LEVELS, "all_levels")

    def test_region_choices(self):
        self.assertEqual(Region.US, "us")
        self.assertEqual(Region.ALL_REGIONS, "all_regions")

    def test_gender_choices(self):
        self.assertEqual(Gender.MALE, "male")
        self.assertEqual(Gender.ALL_GENDERS, "all_genders")
