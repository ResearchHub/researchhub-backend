from allauth.account.models import EmailAddress
from django.test import TestCase

from hub.tests.helpers import create_hub
from paper.tests.helpers import create_paper
from researchhub_comment.tests.helpers import create_rh_comment
from user.tests.helpers import create_random_default_user


class UserSignalsTests(TestCase):
    def setUp(self):
        self.paper_uploader = create_random_default_user("paper_uploader")
        self.paper = create_paper(uploaded_by=self.paper_uploader)

    def test_create_discussion_item_creates_action(self):
        user = create_random_default_user("rando")
        create_rh_comment(created_by=user, paper=self.paper)

        user.refresh_from_db()
        actions = user.actions.all()
        self.assertEqual(len(actions), 1)

    def test_create_thread_creates_action_with_paper_hubs(self):
        user = create_random_default_user("nacho")
        hub = create_hub(name="Nacho Libre")
        paper = create_paper(uploaded_by=user)
        paper.unified_document.hubs.add(hub)
        create_rh_comment(paper=paper, created_by=user)

        action = user.actions.all()[0]
        self.assertIn(hub, action.hubs.all())


class EmailAddressSyncSignalTests(TestCase):
    """
    Tests for the sync_email_address_with_user signal.
    """

    def test_new_user_gets_verified_primary_email_address(self):
        """
        When a new user is created, they should have a verified primary EmailAddress.
        """
        # Act
        user = create_random_default_user("user1")

        # Assert
        email_address = EmailAddress.objects.get(user=user, email=user.email)
        self.assertTrue(email_address.verified)
        self.assertTrue(email_address.primary)

    def test_email_change_updates_email_address_primary(self):
        """
        When user email changes, the new email should become primary.
        """
        # Arrange
        user = create_random_default_user("userChangeEmail1")
        old_email = user.email
        new_email = "new_email@researchhub.com"

        # Act
        user.email = new_email
        user.save()

        # Assert
        new_email_address = EmailAddress.objects.get(user=user, email=new_email)
        self.assertTrue(new_email_address.verified)
        self.assertTrue(new_email_address.primary)

        old_email_address = EmailAddress.objects.get(user=user, email=old_email)
        self.assertFalse(old_email_address.primary)

    def test_email_change_creates_new_email_address_if_not_exists(self):
        """
        When user email changes to a new address, a new EmailAddress record is created.
        """
        # Arrange
        user = create_random_default_user("userNewEmail")
        new_email = "new@researchhub.com"

        # Act
        user.email = new_email
        user.save()

        # Assert
        self.assertTrue(
            EmailAddress.objects.filter(user=user, email=new_email).exists()
        )

    def test_email_change_marks_existing_unverified_as_verified(self):
        """
        If the new email already has an unverified EmailAddress, it should be verified.
        """
        # Arrange
        user = create_random_default_user("userUnverified")
        new_email = "unverified@researchhub.com"
        EmailAddress.objects.create(
            user=user, email=new_email, verified=False, primary=False
        )

        # Act
        user.email = new_email
        user.save()

        # Assert
        email_address = EmailAddress.objects.get(user=user, email=new_email)
        self.assertTrue(email_address.verified)
        self.assertTrue(email_address.primary)
