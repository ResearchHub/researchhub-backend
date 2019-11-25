import rest_framework.serializers as rest_framework_serializers
import rest_auth.registration.serializers as rest_auth_serializers

from .models import User, Author, University


class UniversitySerializer(rest_framework_serializers.ModelSerializer):
    class Meta:
        model = University
        fields = '__all__'


class AuthorSerializer(rest_framework_serializers.ModelSerializer):
    university = UniversitySerializer
    reputation = rest_framework_serializers.SerializerMethodField()

    class Meta:
        model = Author
        fields = [field.name for field in Author._meta.fields] + [
            'university',
            'reputation',
        ]

    def get_reputation(self, obj):
        if obj.user is None:
            return 0
        return obj.user.reputation


class UserSerializer(rest_framework_serializers.ModelSerializer):
    author_profile = AuthorSerializer()

    class Meta:
        model = User
        exclude = ['password']


class RegisterSerializer(rest_auth_serializers.RegisterSerializer):
    username = rest_auth_serializers.serializers.CharField(
        max_length=rest_auth_serializers.get_username_max_length(),
        min_length=rest_auth_serializers.allauth_settings.USERNAME_MIN_LENGTH,
        required=False,
        allow_blank=True
    )

    def validate_username(self, username):
        if username:
            username = rest_auth_serializers.get_adapter().clean_username(
                username
            )
        return username

    def save(self, request):
        return super().save(request)
