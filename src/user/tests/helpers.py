import random

from django.contrib.contenttypes.models import ContentType
from rest_framework.authtoken.models import Token

from hub.models import Hub
from hub.tests.helpers import create_hub
from reputation.related_models.score import Score
from researchhub_access_group.constants import ASSOCIATE_EDITOR
from researchhub_access_group.models import Permission
from user.models import Action, Author, University, User
from user.related_models.organization_model import Organization
from utils.test_helpers import generate_password


class TestData:
    first_name = "Regulus"
    last_name = "Black"
    author_first_name = "R. A."
    author_last_name = "Black"

    author_description = "The youngest Black"
    author_facebook = "facebook.com/rablack"
    author_twitter = "twitter.com/therealrab"
    author_linkedin = "linkedin.com/in/regulusblack"

    invalid_email = "testuser@gmail"
    invalid_password = "pass"  # NOSONAR
    valid_email = "testuser@gmail.com"
    valid_password = generate_password()

    university_name = "Hogwarts"
    university_country = "England"
    university_state = "London"
    university_city = "London"


def create_random_authenticated_user(unique_value, moderator=False):
    user = create_random_default_user(unique_value, moderator)
    Token.objects.create(user=user)
    return user


def create_hub_editor(unique_value, hub_name, moderator=False):
    user = create_random_default_user(unique_value, moderator)
    hub = create_hub(hub_name)
    Permission.objects.create(
        access_type=ASSOCIATE_EDITOR,
        content_type=ContentType.objects.get_for_model(Hub),
        object_id=hub.id,
        user=user,
    )
    return [user, hub]


def create_random_default_user(unique_value, moderator=False):
    """
    Returns an instance of User with name and email based on `unique_value`.
    """
    first_name = TestData.first_name + str(unique_value)
    last_name = TestData.last_name + str(unique_value)
    email = str(unique_value) + str(random.random()) + TestData.valid_email
    user = create_user(
        first_name=first_name, last_name=last_name, email=email, moderator=moderator
    )
    return user


def create_organization(
    name="Organization", description="Organization description", slug="org"
):
    return Organization.objects.create(name=name, description=description, slug=slug)


def create_user(
    first_name=TestData.first_name,
    last_name=TestData.last_name,
    email=TestData.valid_email,
    password=TestData.valid_password,
    moderator=False,
):
    return User.objects.create(
        first_name=first_name,
        last_name=last_name,
        email=email,
        password=password,
        moderator=moderator,
    )


def create_moderator(
    first_name=TestData.first_name,
    last_name=TestData.last_name,
    email=TestData.valid_email,
    password=TestData.valid_password,
):
    return User.objects.create(
        first_name=first_name,
        last_name=last_name,
        email=email,
        password=password,
        moderator=True,
    )


def create_random_authenticated_user_with_reputation(unique_value, reputation):
    user = create_random_authenticated_user(unique_value)
    user.reputation = reputation
    hub = Hub.objects.create(name="Hub")
    Score.objects.create(author=user.author_profile, hub=hub, score=reputation)
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
    linkedin=TestData.author_linkedin,
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
        linkedin=linkedin,
    )


def create_university(
    name=TestData.university_name,
    country=TestData.university_country,
    state=TestData.university_state,
    city=TestData.university_city,
):
    return University.objects.create(name=name, country=country, state=state, city=city)


def create_actions(count, item=None, hub=None):
    return [create_action(item=item, hub=hub) for idx in range(count)]


def create_action(user=None, item=None, hub=None):
    if item is None:
        item = create_university()

    action = Action.objects.create(user=user, item=item, display=True)
    if hub:
        action.hubs.add(hub)

    return action
