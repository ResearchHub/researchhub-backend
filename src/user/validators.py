import re

from django.core.exceptions import ValidationError


class SymbolValidator(object):
    def validate(self, password, user=None):
        if not re.findall(r"[!@#$%^&*?]", password):
            raise ValidationError(
                "The password must contain at least 1 special character: !@#$%^&*?",
                code="password_no_symbol",
            )

    def get_help_text(self):
        return "Your password must contain at least 1 special character: !@#$%^&*?"
