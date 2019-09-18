import json

from django.test import Client

from paper.models import Paper
from user.models import Author, University, User


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

    paper_title = ('Messrs Moony, Wormtail, Padfoot, and Prongs Purveyors of'
                   ' Aids to Magical Mischief-Makers are proud to present THE'
                   ' MARAUDER\'S MAP'
                   )


class TestHelper:
    test_data = TestData()

    def create_user(
        self,
        first_name=test_data.first_name,
        last_name=test_data.last_name,
        email=test_data.valid_email,
        password=test_data.valid_password
    ):
        return User.objects.create(
            first_name=first_name,
            last_name=last_name,
            email=email,
            password=password
        )

    def create_author(
        self,
        user,
        university,
        first_name=test_data.author_first_name,
        last_name=test_data.author_last_name
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
        first_name=test_data.author_first_name,
        last_name=test_data.author_last_name
    ):
        return Author.objects.create(
            first_name=first_name,
            last_name=last_name,
            university=university
        )

    def create_university(
        self,
        name=test_data.university_name,
        country=test_data.university_country,
        state=test_data.university_state,
        city=test_data.university_city
    ):
        return University.objects.create(
            name=name,
            country=country,
            state=state,
            city=city
        )

    def create_paper_without_authors(self, title=test_data.paper_title):
        return Paper.objects.create(
            title=title
        )


class IntegrationTestHelper:
    client = Client()

    def post_response(self, path, data, client=client):
        return client.post(
            path,
            data=json.dumps(data),
            content_type='application/json'
        )
