from reputation.models import Withdrawal

from user.tests.helpers import create_random_default_user

ADDRESS_1 = '0x0000000000000000000000000000000000000000'
ADDRESS_2 = '0x1123581321345589144233377610987159725844'


def create_withdrawals(count):
    for x in range(count):
        user = create_random_default_user('withdrawal_user_' + x)
        create_withdrawal(user)


def create_withdrawal(
    user,
    amount_integer_part=1,
    amount_decimal_part=0,
    from_address=ADDRESS_1,
    to_address=ADDRESS_2,
):
    Withdrawal.objects.create(
        user=user,
        amount_integer_part=amount_integer_part,
        amount_decimal_part=amount_decimal_part,
        from_address=from_address,
        to_address=to_address
    )
