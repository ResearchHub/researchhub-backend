from django.db import models

from user.models import User

INTERACTIONS = {
    "CLICK": "CLICK",
    "VIEW": "VIEW",
}

INTERACTION_CHOICES = [
    (INTERACTIONS["CLICK"], INTERACTIONS["CLICK"]),
    (INTERACTIONS["VIEW"], INTERACTIONS["VIEW"]),
]


class WebsiteVisits(models.Model):
    uuid = models.CharField(max_length=36)
    saw_signup_banner = models.BooleanField(default=False)
    user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    created_date = models.DateTimeField(auto_now_add=True)
    updated_date = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.uuid}"
