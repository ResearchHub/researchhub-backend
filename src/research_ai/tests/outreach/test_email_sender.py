import unittest

from research_ai.services.outreach.email_sender import (
    SES_OUTREACH_DISABLED_DETAIL,
    ExpertFinderOutreachDisabledError,
    send_outreach_email,
)


class SendOutreachEmailTests(unittest.TestCase):
    def test_send_outreach_email_always_refuses_ses(self):
        # Arrange / Act / Assert
        with self.assertRaises(ExpertFinderOutreachDisabledError) as ctx:
            send_outreach_email(
                "expert@example.edu",
                "Subject",
                "Body",
                reply_to=["reply@example.com"],
                cc=["cc@example.com"],
                from_email="Editor <editor@example.com>",
            )
        self.assertEqual(str(ctx.exception), SES_OUTREACH_DISABLED_DETAIL)
