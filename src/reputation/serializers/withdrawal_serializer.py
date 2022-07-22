from rest_framework import serializers

import ethereum.lib
from reputation.models import Withdrawal
from user.serializers import UserSerializer


class WithdrawalSerializer(serializers.ModelSerializer):
    user = UserSerializer(default=serializers.CurrentUserDefault())
    token_address = serializers.CharField(default=ethereum.lib.RSC_CONTRACT_ADDRESS)

    class Meta:
        model = Withdrawal
        fields = "__all__"
        read_only_fields = [
            "amount",
            "token_address",
            "from_address",
            "transaction_hash",
            "paid_date",
            "paid_status",
            "is_removed",
            "is_removed_date",
        ]
