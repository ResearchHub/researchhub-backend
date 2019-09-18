import json

from django.test import Client

from user.models import Author, University, User


class TestHelper:
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

    def create_user(
        self,
        first_name=first_name,
        last_name=last_name,
        email=valid_email,
        password=valid_password
    ):
        return User.objects.create(
            email=email,
            password=password
        )

    def create_author(
        self,
        user,
        university,
        first_name=author_first_name,
        last_name=author_last_name
    ):
        return Author.objects.create(
            user=user,
            first_name=first_name,
            last_name=last_name,
            university=university
        )

    def create_author_without_user(
        self,
        university,
        first_name=author_first_name,
        last_name=author_last_name
    ):
        return Author.objects.create(
            first_name=first_name,
            last_name=last_name,
            university=university
        )

    def create_university(
        self,
        name=university_name,
        country=university_country,
        state=university_state,
        city=university_city
    ):
        return University.objects.create(
            name=name,
            country=country,
            state=state,
            city=city
        )


class IntegrationTestHelper:
    client = Client()

    def post_response(self, path, data, client=client):
        return client.post(
            path,
            data=json.dumps(data),
            content_type='application/json'
        )
