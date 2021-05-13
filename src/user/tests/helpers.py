import random

from rest_framework.authtoken.models import Token

from user.models import Action, Author, University, User


class TestData:
    first_name = 'Regulus'
    last_name = 'Black'
    author_first_name = 'R. A.'
    author_last_name = 'Black'

    author_description = 'The youngest Black'
    author_facebook = 'facebook.com/rablack'
    author_twitter = 'twitter.com/therealrab'
    author_linkedin = 'linkedin.com/in/regulusblack'

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
    email = str(unique_value) + str(random.random()) + TestData.valid_email
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


def create_author(
    user=None,
    first_name=TestData.first_name,
    last_name=TestData.last_name,
    description=TestData.author_description,
    profile_image=None,
    university=None,
    facebook=TestData.author_facebook,
    twitter=TestData.author_twitter,
    linkedin=TestData.author_linkedin
):
    if user is None:
        user = create_random_default_user(first_name)
    if university is None:
        university = create_university(name=last_name)
    return Author.objects.create(
        user=user,
        first_name=first_name,
        last_name=last_name,
        description=description,
        profile_image=profile_image,
        university=university,
        facebook=facebook,
        twitter=twitter,
        linkedin=linkedin
    )


def create_university(
    name=TestData.university_name,
    country=TestData.university_country,
    state=TestData.university_state,
    city=TestData.university_city
):
    return University.objects.create(
        name=name,
        country=country,
        state=state,
        city=city
    )


def create_actions(count, item=None, hub=None):
    return [create_action(item=item, hub=hub) for idx in range(count)]


def create_action(user=None, item=None, hub=None):
    if item is None:
        item = create_university()

    action = Action.objects.create(
        user=user,
        item=item,
        display=True
    )
    if hub:
        action.hubs.add(hub)

    return action
