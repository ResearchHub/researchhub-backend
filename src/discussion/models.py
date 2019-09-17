from django.db import models

# Create your models here.
class Thread(models.Model):
    title = models.CharField(max_length=255)

class Post(models.Model):
    pass

class Reply(models.Model):
    pass
