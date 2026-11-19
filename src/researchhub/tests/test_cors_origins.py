from django.test import TestCase


class CorsAllowedOriginTests(TestCase):
    def preflight(self, origin):
        return self.client.options(
            "/api/auth/login/",
            HTTP_ORIGIN=origin,
            HTTP_ACCESS_CONTROL_REQUEST_METHOD="POST",
        )

    def test_deployment_origins_are_allowed(self):
        # Arrange
        origins = [
            "https://www.researchhub.com",
            "https://web-researchhub.vercel.app",
            "https://web-r2b8olu4e-researchhub.vercel.app",
            "https://web-git-feature-branch-researchhub.vercel.app",
            "https://researchhub-42fxbnmjd-researchhub.vercel.app",
            "https://researchhub-git-main-researchhub.vercel.app",
        ]

        for origin in origins:
            with self.subTest(origin=origin):
                # Act
                response = self.preflight(origin)

                # Assert
                self.assertEqual(
                    response.headers["access-control-allow-origin"], origin
                )

    def test_look_alike_origins_are_rejected(self):
        # Arrange
        origins = [
            "https://researchhub.vercel.app",
            "https://evilresearchhub.vercel.app",
            "https://evil-researchhub.vercel.app",
            "https://researchhub-evil.vercel.app",
            "https://evil-web-abc-researchhub.vercel.app",
            "https://web-abc-researchhub-evil.vercel.app",
            "https://web-abc-researchhub.vercel.app.example.com",
            "https://web-abc-researchhubxvercel.app",
            "https://web-abc-researchhub.vercelxapp",
            "https://web-a.b-researchhub.vercel.app",
            "https://web-abc-researchhub.vercel.app:8443",
            "https://web-abc-researchhub.vercel.app/",
            "https://web-abc-researchhub.vercel.app\n",
            "http://web-abc-researchhub.vercel.app",
        ]

        for origin in origins:
            with self.subTest(origin=origin):
                # Act
                response = self.preflight(origin)

                # Assert
                self.assertNotIn("access-control-allow-origin", response.headers)
