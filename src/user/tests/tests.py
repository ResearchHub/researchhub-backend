import json

from django.test import TestCase, Client

from user.models import User, Author, University


class BaseTests(TestCase):
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
        email=valid_email,
        password=valid_password,
        reputation=0,
        first_name=author_first_name,
        last_name=author_last_name,
    ):
        return User.objects.create(
            email=email,
            password=password,
            reputation=reputation,
            first_name=first_name,
            last_name=last_name,
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

    def create_author_without_university(
        self,
        user,
        first_name=author_first_name,
        last_name=author_last_name
    ):
        return Author.objects.create(
            user=user,
            first_name=first_name,
            last_name=last_name
        )

    def create_author_without_user_or_university(
        self,
        first_name=author_first_name,
        last_name=author_last_name
    ):
        return Author.objects.create(
            first_name=first_name,
            last_name=last_name
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

    def create_university_without_state(
        self,
        name=university_name,
        country=university_country,
        city=university_city
    ):
        return University.objects.create(
            name=name,
            country=country,
            city=city
        )


class UserTests(BaseTests):

    def test_string_representation(self):
        user = self.create_user()
        expected = (
            f'{self.valid_email} / {self.author_first_name}'
            f' {self.author_last_name}'
        )
        self.assertEqual(str(user), expected)

    def test_username_is_set_to_email(self):
        user = self.create_user()
        self.assertEqual(user.username, self.valid_email)

    def test_username_is_set_to_email_when_username_is_specified(self):
        username = 'test_username'
        user = User.objects.create(
            username=username,
            email=self.valid_email,
            password=self.valid_password
        )
        self.assertEqual(user.username, self.valid_email)


class AuthenticationTests(BaseTests):
    """
    Status code reference:
        https://www.iana.org/assignments/http-status-codes/http-status-codes.xhtml
    """

    def setUp(self):
        self.client = Client()

    def test_signup_with_username(self):
        response = self.valid_signup('test_username')
        self.assertContainsToken(response, 201)

    def test_signup_without_username(self):
        response = self.valid_signup()
        self.assertContainsToken(response, 201)

    def test_signup_with_duplicate_email(self):
        self.valid_signup()
        response2 = self.valid_signup()
        response_text = 'A user is already registered with this e-mail'
        self.assertContains(response2, response_text, status_code=400)

    def test_signup_with_duplicate_username_and_different_email(self):
        username = 'test_username'
        self.valid_signup(username)
        response2 = self.signup(
            username,
            'different@gmail.com',
            self.valid_password
        )
        self.assertContainsToken(response2, 201)

    def test_signup_with_duplicate_blank_username_and_different_email(self):
        self.valid_signup()
        response2 = self.signup(
            None,
            'different@gmail.com',
            self.valid_password
        )
        self.assertContainsToken(response2, 201)

    def test_valid_login(self):
        response = self.valid_login()
        self.assertContainsToken(response, 200)

    def assertContainsToken(self, response, status_code):
        self.assertContains(response, 'key', status_code=status_code)
        token = response.json()['key']
        self.assertTrue(len(token) > 0)

    def valid_signup(self, username=None):
        return self.signup(username, self.valid_email, self.valid_password)

    def valid_login(self):
        return self.login(self.valid_email, self.valid_password)

    def signup(self, username, email, password):
        url = '/auth/signup/'
        body = {
            "username": username,
            "email": email,
            "password1": password,
            "password2": password
        }
        if not username:
            del body['username']
        return self.post_response(url, body)

    def login(self, email, password):
        self.signup(email, email, password)
        url = '/auth/login/'
        body = {"email": email, "password": password}
        return self.post_response(url, body)

    def post_response(self, path, data):
        return self.client.post(
            path,
            data=json.dumps(data),
            content_type='application/json'
        )


class AuthorTests(BaseTests):

    def test_string_representation(self):
        university = self.create_university()
        user = self.create_user()
        author = user.author_profile
        author.university = university
        text = 'R. A._Black_Hogwarts_London'
        self.assertEqual(str(author), text)

    def test_string_representation_without_user_or_university(self):
        author = self.create_author_without_user_or_university()
        text = 'R. A._Black__'
        self.assertEqual(str(author), text)

    def test_string_representation_without_university(self):
        user = self.create_user()
        author = user.author_profile
        text = 'R. A._Black__'
        self.assertEqual(str(author), text)

    def test_string_representation_without_user(self):
        university = self.create_university()
        author = self.create_author_without_user(university)
        text = 'R. A._Black_Hogwarts_London'
        self.assertEqual(str(author), text)


class UniversityTests(BaseTests):

    def test_string_representation(self):
        name = 'Cornell University'
        country = 'USA'
        state = 'NY'
        city = 'Ithaca'
        university = self.create_university(
            name=name,
            country=country,
            state=state,
            city=city
        )
        text = f'{name}_{city}'
        self.assertEqual(str(university), text)

    def test_string_representation_without_state(self):
        university = self.create_university_without_state()
        text = 'Hogwarts_London'
        self.assertEqual(str(university), text)
