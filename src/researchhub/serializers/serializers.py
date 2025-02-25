import rest_framework.serializers as serializers


class DynamicModelFieldSerializer(serializers.ModelSerializer):
    def __init__(self, *args, **kwargs):
        # Don't pass the '_include_fields' arg up to the superclass
        # _include_fields = kwargs.pop("_include_fields", "_all_")
        _include_fields = kwargs.pop("_include_fields", "__all__")
        # Don't pass the '_exclude_fields' arg up to the superclass
        _exclude_fields = kwargs.pop("_exclude_fields", None)
        # Don't pass the '_filter_fields' arg up to the superclass
        _filter_fields = kwargs.pop("_filter_fields", None)
        # Don't pass the '_order_fields' arg up to the superclass
        _order_fields = kwargs.pop("_order_fields", None)
        # Don't pass the '_select_related_fields' arg up to the superclass
        _select_related_fields = kwargs.pop("_select_related_fields", None)
        # Don't pass the '_prefetch_related_fields' arg up to the superclass
        _prefetch_related_fields = kwargs.pop("_prefetch_related_fields", None)

        super(DynamicModelFieldSerializer, self).__init__(*args, **kwargs)

        # instance_class_name = self.instance.__class__.__name__
        # is_manager = (
        #     instance_class_name == "RelatedManager"
        #     or instance_class_name == "ManyRelatedManager"
        # )
        # known_related_objects = getattr(self.instance, "_known_related_objects", [])
        # if is_manager or len(known_related_objects) > 0:
        #     if _include_fields == "_all_":
        #         _include_fields = None
        #         _exclude_fields = "__all__"
        # elif _include_fields == "_all_":
        #     _include_fields = "__all__"

        if _include_fields is not None and _include_fields != "__all__":
            # Drop any fields that are not specified in the
            # `_include_fields` argument.
            allowed = set(_include_fields)
            existing = set(self.fields)
            for field_name in existing - allowed:
                self.fields.pop(field_name)

        if _exclude_fields is not None:
            existing = set(self.fields)
            if _exclude_fields == "__all__":
                for field_name in existing:
                    self.fields.pop(field_name)
            else:
                disallowed = set(_exclude_fields)
                for field_name in disallowed:
                    self.fields.pop(field_name)
