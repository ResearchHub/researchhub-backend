from django.test import SimpleTestCase, override_settings
import os


class PersonaWebhookViewTests(SimpleTestCase):

    webhook_secret = "wbhsec_researchhub"

    def setUp(self):
        self.webhook_approved_body = self.read_test_file(
            "persona_webhook_approved.json"
        )

    def read_test_file(self, filename):
        file_path = os.path.join(os.path.dirname(__file__), "test_files", filename)
        with open(file_path, "r") as file:
            return file.read()

    @override_settings(PERSONA_WEBHOOK_SECRET=webhook_secret)
    def test_post_webhook_without_signature(self):
        response = self.client.post(
            "/webhooks/persona/",
            self.webhook_approved_body,
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json(), {"message": "Unauthorized"})

    @override_settings(PERSONA_WEBHOOK_SECRET=webhook_secret)
    def test_post_webhook(self):
        response = self.client.post(
            "/webhooks/persona/",
            self.webhook_approved_body,
            content_type="application/json",
            headers={
                "Persona-Signature": "t=1720448965,v1=6d7a6f2356a65fd3a1734457430a1a2fe0c566349e0d472c45cb9281a7d3b68d"
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"message": "Webhook successfully processed"})

    @override_settings(PERSONA_WEBHOOK_SECRET=webhook_secret)
    def test_post_webhook_with_invalid_signature(self):
        body = self.webhook_approved_body
        response = self.client.post(
            "/webhooks/persona/",
            body,
            content_type="application/json",
            headers={
                "Persona-Signature": "t=1720448965,v1=aaabbb2356a65fd3a1734457430a1a2fe0c566349e0d472c45cb9281a7d3b68d"
            },
        )

        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json(), {"message": "Unauthorized"})
