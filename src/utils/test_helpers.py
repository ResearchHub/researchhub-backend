import json
import threading
import time

from django.db import connection
from django.test import Client
from rest_framework.authtoken.models import Token
from rest_framework.test import APIClient

from bullet_point.models import BulletPoint
from discussion.models import Thread
from hub.models import Hub
from paper.models import Paper, Vote
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
    paper_titles = [
        'Engendering Extroverted Murder: Hamlet Revenge and/in the Oppressed',
        'Freedom Of Speech',
        'How Films Relate To Criminology',
        'Constructing Reliable Vision',
        'Self-Organization of Associative Database and Its Applications',
        'Family Discovery',
        'Learning the Structure of Similarity',
        'Forward-backward retraining of recurrent neural networks',
        'Stable Dynamic Parameter Adaption',
        'Improving Elevator Performance Using Reinforcement Learning',
        'Softassign versus Softmax: Benchmarks in Combinatorial Optimization',
    ]
    paper_publish_date = '1990-10-01'


# REFACTOR: Instead of having to inherit this class, test cases should import
# the needed functions from a test_helper module that is defined in each app.

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

    def create_random_authenticated_user(self, unique_value):
        user = self.create_random_default_user(unique_value)
        Token.objects.create(user=user)
        return user

    def create_random_default_user(self, unique_value):
        first_name = self.test_data.first_name + str(unique_value)
        last_name = self.test_data.last_name + str(unique_value)
        email = str(unique_value) + self.test_data.valid_email
        user = self.create_user(
            first_name=first_name,
            last_name=last_name,
            email=email
        )
        return user

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

    def create_paper_without_authors(
        self,
        title=test_data.paper_title
    ):
        return Paper.objects.create(
            title=title,
            paper_publish_date=self.test_data.paper_publish_date
        )

    def create_hub(
        self,
        name
    ):
        return Hub.objects.create(
            name=name
        )

    def create_upvote(
        self,
        user,
        paper
    ):
        return Vote.objects.create(
            paper=paper,
            created_by=user,
            vote_type=Vote.UPVOTE
        )

    def create_downvote(
        self,
        user,
        paper
    ):
        return Vote.objects.create(
            paper=paper,
            created_by=user,
            vote_type=Vote.DOWNVOTE
        )

    def create_thread(
        self,
        user,
        paper,
        text='thread'
    ):
        return Thread.objects.create(
            created_by=user,
            paper=paper,
            text={'text': text},
            plain_text=text
        )

    def create_bulletpoint(
        self,
        user,
        paper,
        text='bulletpoint'
    ):
        return BulletPoint.objects.create(
            created_by=user,
            paper=paper,
            plain_text=text
        )


class IntegrationTestHelper(TestData):
    client = Client()

    def get_default_authenticated_client(self):
        response = self.signup_default_user()
        response_content = self.bytes_to_json(response.content)
        token = response_content.get('key')
        client = self._create_authenticated_client(token)
        return client

    def signup_default_user(self):
        url = '/auth/signup/'
        body = {
            "username": self.valid_email,
            "email": self.valid_email,
            "password1": self.valid_password,
            "password2": self.valid_password
        }
        return self.get_post_response(url, body)

    def bytes_to_json(self, data_bytes):
        data_string = data_bytes.decode('utf-8')
        json_dict = json.loads(data_string)
        return json_dict

    def get_get_response(
        self,
        path,
        query_data=None,
        follow_redirects=True,
        client=client
    ):
        """
        Returns the response of a `GET` request made by `client`.

        query_data {'param1': ['value1', 'value2'], 'param2': ['value3']}
        """
        return client.get(
            path,
            data=query_data,
            follow=follow_redirects,
            content_type='application/json'
        )

    def get_post_response(
        self,
        path,
        data,
        client=client,
        content_type='application/json',
        follow_redirects=True
    ):
        return client.post(
            path,
            data=json.dumps(data),
            follow=follow_redirects,
            content_type=content_type
        )

    def get_authenticated_get_response(
        self,
        user,
        url,
        content_type
    ):
        csrf = False

        if content_type == 'application/json':
            content_format = 'json'
        elif content_type == 'multipart/form-data':
            content_format = 'multipart'
            csrf = True

        client = APIClient(enforce_csrf_checks=csrf)
        client.force_authenticate(user=user, token=user.auth_token)
        response = client.get(url, format=content_format)
        return response

    def _create_authenticated_client(self, auth_token):
        return Client(HTTP_AUTHORIZATION=f'Token {auth_token}')


def bytes_to_json(data_bytes):
    """Returns `json_dict` representation of `data_bytes`."""
    data_string = data_bytes.decode('utf-8')
    json_dict = json.loads(data_string)
    return json_dict


def get_authenticated_get_response(
    user,
    url,
    content_type='application/json'
):
    '''
    Sends a get request authenticated with `user` and returns the response.
    '''
    client, content_format = _get_authenticated_client_config(
        user,
        url,
        content_type
    )

    response = client.get(url, format=content_format)
    return response


def get_get_response(
    path,
    query_data=None,
    follow_redirects=True,
    csrf=False,
    http_origin=None
):
    """
    Returns the response of a `GET` request made by `client`.

    query_data {'param1': ['value1', 'value2'], 'param2': ['value3']}
    """
    client = APIClient(enforce_csrf_checks=csrf, HTTP_ORIGIN=http_origin)
    return client.get(
        path,
        data=query_data,
        follow=follow_redirects,
        content_type='application/json'
    )


def get_authenticated_post_response(
    user,
    url,
    data,
    content_type='application/json',
    follow=False,
    headers=None
):
    '''
    Sends a post request authenticated with `user` and returns the response.
    '''
    client, content_format = _get_authenticated_client_config(
        user,
        url,
        content_type,
        http_origin=headers and headers.get('HTTP_ORIGIN', None)
    )
    response = client.post(url, data, format=content_format, follow=follow)
    return response


def get_authenticated_patch_response(
    user,
    url,
    data,
    content_type
):
    '''
    Sends a patch request authenticated with `user` and returns the response.
    '''
    client, content_format = _get_authenticated_client_config(
        user,
        url,
        content_type
    )
    response = client.patch(url, data, format=content_format)
    return response


def get_authenticated_put_response(
    user,
    url,
    data,
    content_type
):
    '''
    Sends a put request authenticated with `user` and returns the response.
    '''
    client, content_format = _get_authenticated_client_config(
        user,
        url,
        content_type
    )
    response = client.put(url, data, format=content_format)
    return response


def get_authenticated_delete_response(
    user,
    url,
    data,
    content_type
):
    '''
    Sends a delete request authenticated with `user` and returns the response.
    '''
    client, content_format = _get_authenticated_client_config(
        user,
        url,
        content_type
    )
    response = client.delete(url, data, format=content_format)
    return response


def _get_authenticated_client_config(
    user,
    url,
    content_type,
    http_origin=None
):
    csrf = False

    if content_type == 'multipart/form-data':
        content_format = 'multipart'
        csrf = True
    elif content_type == 'plain/text':
        content_format = 'txt'
    else:
        content_format = 'json'

    client = APIClient(enforce_csrf_checks=csrf, HTTP_ORIGIN=http_origin)
    client.force_authenticate(user=user, token=user.auth_token)
    return client, content_format


def get_user_from_response(response):
    return response.wsgi_request.user


class DatabaseThread(threading.Thread):

    def run(self):
        super().run()
        connection.close()


# Copied from
# https://www.caktusgroup.com/blog/2009/05/26/testing-django-views-for-concurrency-issues/
def test_concurrently(runs, delay=None):
    """
    Add this decorator to small pieces of code that you want to test
    concurrently to make sure they don't raise exceptions when run at the
    same time.  E.g., some Django views that do a SELECT and then a subsequent
    INSERT might fail when the INSERT assumes that the data has not changed
    since the SELECT.
    """
    def test_concurrently_decorator(test_func):
        def wrapper(*args, **kwargs):
            exceptions = []

            def call_test_func():
                try:
                    test_func(*args, **kwargs)
                except Exception as e:
                    exceptions.append(e)
                    raise

            threads = []
            for i in range(runs):
                threads.append(DatabaseThread(target=call_test_func))
            for t in threads:
                if delay is not None:
                    time.sleep(delay)
                t.start()
            for t in threads:
                if delay is not None:
                    time.sleep(delay)
                t.join()
            if exceptions:
                raise Exception(
                    'test_concurrently intercepted %s exceptions: %s'
                    % (len(exceptions), exceptions)
                )

        return wrapper
    return test_concurrently_decorator
