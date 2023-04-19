from django.db.models import CharField, F, Value
from django.db.models.functions import Concat
from django_elasticsearch_dsl import fields as es_fields
from django_elasticsearch_dsl.registries import registry

from search.analyzers import name_analyzer, title_analyzer
from user.models import User

from .base import BaseDocument


@registry.register_document
class UserDocument(BaseDocument):
    auto_refresh = True
    full_name = es_fields.TextField(attr="full_name")
    full_name_suggest = es_fields.Completion()

    class Index:
        name = "user"

    # Let ES know which fields we want indexed
    class Django:
        model = User
        queryset_pagination = 250
        fields = [
            "id",
            "first_name",
            "last_name",
        ]

    def prepare_full_name_suggest(self, instance):
        full_name_suggest = f"{instance.first_name} {instance.last_name}"
        return {"input": full_name_suggest.split(), "weight": instance.id}

    def prepare_full_name(self, instance):
        return f"{instance.first_name} {instance.last_name}"

    def prepare(self, instance):
        data = super().prepare(instance)
        data["full_name_suggest"] = self.prepare_full_name_suggest(instance)
        return data
