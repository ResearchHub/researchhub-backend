from allauth.account.models import EmailAddress
from allauth.socialaccount.models import SocialAccount
from allauth.socialaccount.providers.google.provider import GoogleProvider
from allauth.socialaccount.providers.orcid.provider import OrcidProvider
from django.test import TestCase

from user.services.academic_email_service import (
    ACCOUNT_EMAIL_SOURCE,
    ORCID_SOURCE,
    AcademicEmailService,
)
from user.tests.helpers import create_user


def _badge(email_domain, institution_domain, source):
    return {
        "email_domain": email_domain,
        "institution_domain": institution_domain,
        "source": source,
    }


class AcademicEmailServiceTests(TestCase):
    def setUp(self):
        self.service = AcademicEmailService()

    def _connect_orcid(self, user, verified_edu_emails):
        SocialAccount.objects.update_or_create(
            user=user,
            provider=OrcidProvider.id,
            defaults={
                "uid": "0000-0001-2345-6789",
                "extra_data": {"verified_edu_emails": verified_edu_emails},
            },
        )

    def _connect_google(self, user, email, verified, verified_key="email_verified"):
        SocialAccount.objects.create(
            user=user,
            provider=GoogleProvider.id,
            uid="google-123",
            extra_data={"email": email, verified_key: verified},
        )

    def _add_login_email(self, user, verified):
        EmailAddress.objects.create(
            user=user, email=user.email, verified=verified, primary=True
        )

    def test_returns_orcid_verified_domain(self):
        # Arrange
        user = create_user(email="someone@gmail.com")
        self._connect_orcid(user, ["jdoe@purdue.edu"])

        # Act
        result = self.service.get_verified_academic_email(user)

        # Assert
        self.assertEqual(result, _badge("purdue.edu", "purdue.edu", ORCID_SOURCE))

    def test_returns_email_and_institution_domains(self):
        # Arrange
        user = create_user(email="someone@gmail.com")
        cases = {
            "JDoe@CS.Purdue.EDU": ("cs.purdue.edu", "purdue.edu"),
            "jdoe@eng.ox.ac.uk": ("eng.ox.ac.uk", "ox.ac.uk"),
            "jdoe@mail.nih.gov": ("mail.nih.gov", "nih.gov"),
        }
        for email, (email_domain, institution_domain) in cases.items():
            with self.subTest(email=email):
                self._connect_orcid(user, [email])

                # Act
                result = self.service.get_verified_academic_email(user)

                # Assert
                self.assertEqual(
                    result, _badge(email_domain, institution_domain, ORCID_SOURCE)
                )

    def test_ignores_open_registration_domains(self):
        # Arrange
        user = create_user(email="someone@gmail.com")
        self._connect_orcid(user, ["me@tyler.phd", "me@my.science"])

        # Act
        result = self.service.get_verified_academic_email(user)

        # Assert
        self.assertIsNone(result)

    def test_skips_open_registration_domain_for_next_orcid_email(self):
        # Arrange
        user = create_user(email="someone@gmail.com")
        self._connect_orcid(user, ["me@tyler.phd", "jdoe@mit.edu"])

        # Act
        result = self.service.get_verified_academic_email(user)

        # Assert
        self.assertEqual(result, _badge("mit.edu", "mit.edu", ORCID_SOURCE))

    def test_returns_verified_login_email_domain(self):
        # Arrange
        user = create_user(email="jdoe@stanford.edu")
        self._add_login_email(user, verified=True)

        # Act
        result = self.service.get_verified_academic_email(user)

        # Assert
        self.assertEqual(
            result, _badge("stanford.edu", "stanford.edu", ACCOUNT_EMAIL_SOURCE)
        )

    def test_ignores_unverified_login_email(self):
        # Arrange
        user = create_user(email="jdoe@stanford.edu")
        self._add_login_email(user, verified=False)

        # Act
        result = self.service.get_verified_academic_email(user)

        # Assert
        self.assertIsNone(result)

    def test_returns_google_verified_login_email_domain(self):
        # Arrange
        user = create_user(email="jdoe@stanford.edu")
        self._connect_google(user, "JDoe@Stanford.edu", verified=True)

        # Act
        result = self.service.get_verified_academic_email(user)

        # Assert
        self.assertEqual(
            result, _badge("stanford.edu", "stanford.edu", ACCOUNT_EMAIL_SOURCE)
        )

    def test_ignores_login_email_google_did_not_verify(self):
        # Arrange
        user = create_user(email="jdoe@stanford.edu")
        self._connect_google(user, "jdoe@stanford.edu", verified=False)

        # Act
        result = self.service.get_verified_academic_email(user)

        # Assert
        self.assertIsNone(result)

    def test_ignores_google_verified_email_that_differs_from_login_email(self):
        # Arrange
        user = create_user(email="jdoe@stanford.edu")
        self._connect_google(user, "jdoe@gmail.com", verified=True)

        # Act
        result = self.service.get_verified_academic_email(user)

        # Assert
        self.assertIsNone(result)

    def test_accepts_legacy_google_verified_email_flag(self):
        # Arrange
        user = create_user(email="jdoe@stanford.edu")
        self._connect_google(
            user, "jdoe@stanford.edu", verified=True, verified_key="verified_email"
        )

        # Act
        result = self.service.get_verified_academic_email(user)

        # Assert
        self.assertEqual(
            result, _badge("stanford.edu", "stanford.edu", ACCOUNT_EMAIL_SOURCE)
        )

    def test_prefers_orcid_over_login_email(self):
        # Arrange
        user = create_user(email="jdoe@stanford.edu")
        self._add_login_email(user, verified=True)
        self._connect_orcid(user, ["jdoe@mit.edu"])

        # Act
        result = self.service.get_verified_academic_email(user)

        # Assert
        self.assertEqual(result, _badge("mit.edu", "mit.edu", ORCID_SOURCE))

    def test_falls_back_to_login_email_when_orcid_has_no_restricted_email(self):
        # Arrange
        user = create_user(email="jdoe@stanford.edu")
        self._add_login_email(user, verified=True)
        self._connect_orcid(user, ["me@tyler.phd"])

        # Act
        result = self.service.get_verified_academic_email(user)

        # Assert
        self.assertEqual(
            result, _badge("stanford.edu", "stanford.edu", ACCOUNT_EMAIL_SOURCE)
        )

    def test_returns_none_without_academic_email(self):
        # Arrange
        user = create_user(email="someone@gmail.com")
        self._add_login_email(user, verified=True)
        self._connect_orcid(user, [])

        # Act
        result = self.service.get_verified_academic_email(user)

        # Assert
        self.assertIsNone(result)
