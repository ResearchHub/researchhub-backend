from django.test import TestCase

from research_ai.constants import ExpertiseLevel, Gender, Region


class ConstantsTests(TestCase):
    def test_expertise_level_choices(self):
        self.assertEqual(ExpertiseLevel.PHD_POSTDOCS, "PhD/PostDocs")
        self.assertEqual(ExpertiseLevel.ALL_LEVELS, "All Levels")

    def test_region_choices(self):
        self.assertEqual(Region.US, "US")
        self.assertEqual(Region.ALL_REGIONS, "All Regions")

    def test_gender_choices(self):
        self.assertEqual(Gender.MALE, "Male")
        self.assertEqual(Gender.ALL_GENDERS, "All Genders")
