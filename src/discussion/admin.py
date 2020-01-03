from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from .models import Vote, Thread, Reply, Comment

admin.site.register(Vote)
admin.site.register(Thread)
admin.site.register(Reply)
admin.site.register(Comment)
