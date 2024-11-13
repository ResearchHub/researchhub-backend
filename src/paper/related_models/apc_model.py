from django.db import models


# Model for article processing charges (APC) for papers
class PaperAPC(models.Model):
    paper = models.ForeignKey("Paper", on_delete=models.CASCADE, related_name="apcs")
    amount = models.IntegerField(null=True, blank=True)
    currency = models.CharField(max_length=3, null=True, blank=True)
    paid = models.BooleanField(default=False)
    created_date = models.DateTimeField(auto_now_add=True)
    updated_date = models.DateTimeField(auto_now=True)
