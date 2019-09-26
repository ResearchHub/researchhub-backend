import rest_framework.serializers as serializers

from .models import Summary
from user.models import User

class SummarySerializer(serializers.ModelSerializer):
    user = serializers.PrimaryKeyRelatedField(
        queryset=User.objects.all(),
        read_only=False,
        default=serializers.CurrentUserDefault()
    )

    class Meta:
        fields = '__all__'
        model = Summary