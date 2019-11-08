from allauth.socialaccount.models import SocialAccount
import rest_framework.serializers as rest_framework_serializers
import rest_auth.registration.serializers as rest_auth_serializers

from .models import User, Author, University


class UniversitySerializer(rest_framework_serializers.ModelSerializer):
    class Meta:
        model = University
        fields = '__all__'


class AuthorSerializer(rest_framework_serializers.ModelSerializer):
    university = UniversitySerializer(required=False)
    profile_image = rest_framework_serializers.SerializerMethodField()
    reputation = rest_framework_serializers.SerializerMethodField()

    class Meta:
        model = Author
        fields = '__all__'

    def get_profile_image(self, obj):
        try:
            url = obj.profile_image.url
        except ValueError:
            url = self._get_google_image_url(obj)
        return url

    def _get_google_image_url(self, obj):
        try:
            queryset = SocialAccount.objects.filter(
                provider='google',
                user=obj.user
            )

            num_accounts = len(queryset)
            if num_accounts < 1:
                return None
            if num_accounts > 1:
                # TODO: Make this exception more descriptive
                raise Exception(
                    f'Expected 1 item in the queryset. Found {num_accounts}.'
                )

            google_account = queryset[0]
            url = google_account.extra_data.get('picture', None)
            return url

        except Exception as e:
            print(e)
            return None

    def get_reputation(self, obj):
        if obj.user == None:
            return 0
        return obj.user.reputation

    # def get_authored_papers(self, obj):
    #     papers = obj.authored_papers.all()
    #     return PaperSerializer(papers, many=True)


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
