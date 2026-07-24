import importlib
from unittest.mock import Mock

from django.test import SimpleTestCase


class UserMigrationTests(SimpleTestCase):
    def test_onboarding_backfill_uses_unfiltered_base_manager(self):
        # Arrange
        migration = importlib.import_module(
            "user.migrations.0099_user_has_completed_onboarding"
        )
        historical_user = Mock()
        apps = Mock()
        apps.get_model.return_value = historical_user
        schema_editor = Mock()
        schema_editor.connection.alias = "default"

        # Act
        migration.initialize_to_has_seen_orcid_connect_modal(apps, schema_editor)

        # Assert
        historical_user._base_manager.using.assert_called_once_with("default")
        historical_user.objects.using.assert_not_called()
        update = historical_user._base_manager.using.return_value.update
        update.assert_called_once()
        expression = update.call_args.kwargs["has_completed_onboarding"]
        self.assertEqual(expression.name, "has_seen_orcid_connect_modal")
