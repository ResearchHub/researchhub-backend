from django.test import TestCase

from ai_expert_finder.models import EmailTemplate
from ai_expert_finder.services import email_template_service as svc
from user.tests.helpers import create_random_authenticated_user


class GetTemplateTests(TestCase):
    def test_get_template_invalid_id_returns_none(self):
        self.assertIsNone(svc.get_template("not-an-int"))
        self.assertIsNone(svc.get_template(None))

    def test_get_template_found(self):
        user = create_random_authenticated_user("ets")
        t = EmailTemplate.objects.create(created_by=user, name="N")
        self.assertEqual(svc.get_template(t.id).id, t.id)
        self.assertEqual(svc.get_template(str(t.id)).id, t.id)
