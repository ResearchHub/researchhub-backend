import rest_framework.serializers as serializers


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

    def is_valid(self, raise_exception=False):
        inital_data = self.inital_data
        read_only_fields = getattr(self.Meta, 'read_only_fields', [])

        for read_only_field in read_only_fields:
            # Not doing an exact check because some fields
            # can include _id or something similar
            if read_only_field in inital_data:
                inital_data.pop(read_only_field)

        return super(DynamicModelFieldSerializer, self).is_valid(
            self,
            raise_exception
        )
