from rest_framework.serializers import ModelSerializer, SerializerMethodField, ModelField

from .researchhub_case_abstract_serializer import EXPOSABLE_FIELDS
from researchhub_case.models import AuthorClaimCase
from user.serializers import AuthorSerializer, UserSerializer

# TODO: calvinhlee 
# class ReadWriteSerializerMethodField(SerializerMethodField):
#     def __init__(self, method_name=None, **kwargs):
#         self.method_name = method_name
#         kwargs['source'] = '*'
#         super(SerializerMethodField, self).__init__(**kwargs)

#     def to_internal_value(self, data):
#         return {self.field_name: data}

class AuthorClaimCaseSerializer(ModelSerializer):
    moderator = ReadWriteSerializerMethodField(method_name='get_moderator')
    requestor = ReadWriteSerializerMethodField(method_name='get_requestor')
    target_author = ReadWriteSerializerMethodField(method_name='get_target_author')

    def get_moderator(self, case):
        serializer = UserSerializer(case.moderator)
        if (serializer is not None):
            return serializer.data
        return None

    def get_requestor(self, case):
        serializer = UserSerializer(case.requestor)
        if (serializer is not None):
            return serializer.data
        return None

    def get_target_author(self, case):
        serializer = AuthorSerializer(case.target_author)
        if (serializer is not None):
            return serializer.data
        return None

    class Meta(object):
        model = AuthorClaimCase
        fields = [
          *EXPOSABLE_FIELDS,
          'provided_email',
          'status',
          'target_author',
          'token_generated_time',
          'validation_attempt_count',
          'validation_token',
        ]
        read_only_fields = [
          'status',
          'token_generated_time',
          'validation_attempt_count',
          'validation_token',
        ]
