from django.db.migrations.loader import MigrationLoader
from django.test import SimpleTestCase


class UserManagerHistoricalMigrationTests(SimpleTestCase):
    def test_manager_supports_state_before_soft_delete_fields(self):
        # Arrange
        loader = MigrationLoader(None, ignore_no_migrations=True)
        state = loader.project_state(("user", "0099_user_has_completed_onboarding"))
        historical_user = state.apps.get_model("user", "User")

        # Act
        queryset = historical_user.objects.all()

        # Assert
        field_names = {field.name for field in historical_user._meta.get_fields()}
        self.assertNotIn("is_removed", field_names)
        self.assertFalse(queryset.query.where)
