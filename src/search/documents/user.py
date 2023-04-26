from django_elasticsearch_dsl import fields as es_fields
from django_elasticsearch_dsl.registries import registry

from user.models import User

from .base import BaseDocument


@registry.register_document
class UserDocument(BaseDocument):
    auto_refresh = True
    full_name = es_fields.TextField(attr="full_name")
    profile_img = es_fields.TextField()
    full_name_suggest = es_fields.Completion()
    author_profile = es_fields.ObjectField(
        properties={
            "profile_img": es_fields.TextField(),
            "id": es_fields.IntegerField(),
        },
    )

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
            "reputation",
        ]

    def prepare_author_profile(self, instance):
        profile = None

        try:
            profile = {
                "id": instance.author_profile.id,
                "headline": instance.author_profile.headline,
            }
        except Exception as e:
            return False

        try:
            profile["profile_image"] = instance.author_profile.profile_image.url
        except Exception as e:
            pass

        return profile

    # Used specifically for "autocomplete" style suggest feature
    def prepare_full_name_suggest(self, instance):
        full_name_suggest = f"{instance.first_name} {instance.last_name}"
        return {"input": full_name_suggest.split()}

    def prepare_full_name(self, instance):
        return f"{instance.first_name} {instance.last_name}"

    def prepare(self, instance):
        data = super().prepare(instance)
        data["full_name_suggest"] = self.prepare_full_name_suggest(instance)
        return data
