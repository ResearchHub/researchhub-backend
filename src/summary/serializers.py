import rest_framework.serializers as serializers

from .models import Summary
from user.models import User
from user.serializers import UserSerializer

class SummarySerializer(serializers.ModelSerializer):
    proposed_by = UserSerializer(
        read_only=False,
        default=serializers.CurrentUserDefault()
    )

    class Meta:
        fields = '__all__'
        model = Summary