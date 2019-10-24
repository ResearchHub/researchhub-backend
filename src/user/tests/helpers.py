from rest_framework.authtoken.models import Token

from user.models import User


class TestData:
    first_name = 'Regulus'
    last_name = 'Black'
    author_first_name = 'R. A.'
    author_last_name = 'Black'

    invalid_email = 'testuser@gmail'
    invalid_password = 'pass'
    valid_email = 'testuser@gmail.com'
    valid_password = 'ReHub940'

    university_name = 'Hogwarts'
    university_country = 'England'
    university_state = 'London'
    university_city = 'London'


def create_random_authenticated_user(unique_value):
    user = create_random_default_user(unique_value)
    Token.objects.create(user=user)
    return user


def create_random_default_user(unique_value):
    '''
    Returns an instance of User with name and email based on `unique_value`.
    '''
    first_name = TestData.first_name + str(unique_value)
    last_name = TestData.last_name + str(unique_value)
    email = str(unique_value) + TestData.valid_email
    user = create_user(
        first_name=first_name,
        last_name=last_name,
        email=email
    )
    return user


def create_user(
    first_name=TestData.first_name,
    last_name=TestData.last_name,
    email=TestData.valid_email,
    password=TestData.valid_password
):
    return User.objects.create(
        first_name=first_name,
        last_name=last_name,
        email=email,
        password=password
    )


def create_random_authenticated_user_with_reputation(unique_value, reputation):
    user = create_random_authenticated_user(unique_value)
    user.reputation = reputation
    user.save()
    return user
