from rest_framework import serializers

import ethereum.lib
from reputation.models import Withdrawal
from user.serializers import UserSerializer


class WithdrawalSerializer(serializers.ModelSerializer):
    user = UserSerializer()
    token_address = serializers.CharField(
        default=ethereum.lib.RESEARCHCOIN_CONTRACT_ADDRESS
    )

    # def __init__(self, *args, **kwargs):
    #     super(WithdrawalSerializer, self).__init__(*args, **kwargs)
    #     import pdb; pdb.set_trace()
    #     self.fields['user'].default = self.context

    class Meta:
        model = Withdrawal
        fields = '__all__'
        read_only_fields = [
            'amount',
            'token_address',
            'from_address',
            'transaction_hash',
            'paid_date',
            'paid_status',
            'is_removed',
            'is_removed_date',
        ]


def get_model_serializer(model_arg):
    class GenericSerializer(serializers.ModelSerializer):
        class Meta:
            model = model_arg
            fields = '__all__'

    return GenericSerializer
