import rest_framework.serializers as serializers

from django.db import models

from rest_framework.compat import postgres_fields
from rest_framework.utils.field_mapping import (
    ClassLookupDict,
    get_field_kwargs
)
from rest_framework.fields import (
    ModelField,
    CharField,
    ChoiceField,
)


class DynamicModelFieldSerializer(serializers.ModelSerializer):
    def __init__(self, *args, **kwargs):
        # Don't pass the '_include_fields' arg up to the superclass
        _include_fields = kwargs.pop('_include_fields', '__all__')
        # Don't pass the '_exclude_fields' arg up to the superclass
        _exclude_fields = kwargs.pop('_exclude_fields', None)

        super(DynamicModelFieldSerializer, self).__init__(*args, **kwargs)

        if _include_fields is not None and _include_fields != '__all__':
            # Drop any fields that are not specified in the
            # `_include_fields` argument.
            allowed = set(_include_fields)
            existing = set(self.fields)
            for field_name in existing - allowed:
                self.fields.pop(field_name)

        if _exclude_fields is not None:
            existing = set(self.fields)
            if _exclude_fields == '__all__':
                for field_name in existing:
                    self.fields.pop(field_name)
            else:
                disallowed = set(_exclude_fields)
                for field_name in disallowed:
                    self.fields.pop(field_name)

    # TODO: Remove anything below this comment.
    # Testing purposes
    def _build_field(self, field_name, info, model_class, nested_depth):
        return super().build_field(field_name, info, model_class, nested_depth)
        import pdb; pdb.set_trace()

    def _build_standard_field(self, field_name, model_field):
        """
        Create regular model fields.
        """
        field_mapping = ClassLookupDict(self.serializer_field_mapping)

        field_class = field_mapping[model_field]
        field_kwargs = get_field_kwargs(field_name, model_field)

        # Special case to handle when a OneToOneField is also the primary key
        if model_field.one_to_one and model_field.primary_key:
            field_class = self.serializer_related_field
            field_kwargs['queryset'] = model_field.related_model.objects

        if 'choices' in field_kwargs:
            # Fields with choices get coerced into `ChoiceField`
            # instead of using their regular typed field.
            field_class = self.serializer_choice_field
            # Some model fields may introduce kwargs that would not be valid
            # for the choice field. We need to strip these out.
            # Eg. models.DecimalField(max_digits=3, decimal_places=1, choices=DECIMAL_CHOICES)
            valid_kwargs = {
                'read_only', 'write_only',
                'required', 'default', 'initial', 'source',
                'label', 'help_text', 'style',
                'error_messages', 'validators', 'allow_null', 'allow_blank',
                'choices'
            }
            for key in list(field_kwargs):
                if key not in valid_kwargs:
                    field_kwargs.pop(key)

        if not issubclass(field_class, ModelField):
            # `model_field` is only valid for the fallback case of
            # `ModelField`, which is used when no other typed field
            # matched to the model field.
            field_kwargs.pop('model_field', None)

        if not issubclass(field_class, CharField) and not issubclass(field_class, ChoiceField):
            # `allow_blank` is only valid for textual fields.
            field_kwargs.pop('allow_blank', None)

        is_django_jsonfield = (
            hasattr(models, 'JSONField') and
            isinstance(model_field, models.JSONField)
        )
        if (
            (
                postgres_fields and isinstance(
                model_field,
                postgres_fields.JSONField)
            )
            or is_django_jsonfield
        ):
            # Populate the `encoder` argument of `JSONField` instances generated
            # for the model `JSONField`.
            field_kwargs['encoder'] = getattr(model_field, 'encoder', None)
            if is_django_jsonfield:
                field_kwargs['decoder'] = getattr(model_field, 'decoder', None)

        if postgres_fields and isinstance(model_field, postgres_fields.ArrayField):
            # Populate the `child` argument on `ListField` instances generated
            # for the PostgreSQL specific `ArrayField`.
            child_model_field = model_field.base_field
            child_field_class, child_field_kwargs = self.build_standard_field(
                'child', child_model_field
            )
            field_kwargs['child'] = child_field_class(**child_field_kwargs)

        return field_class, field_kwargs
