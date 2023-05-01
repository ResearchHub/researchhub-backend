from unittest import TestCase
from unittest.mock import patch, Mock

from jsonschema.exceptions import ValidationError
from utils.user_filter import UserFilter


class UserFilterTest(TestCase):
    @staticmethod
    def test_create_valid_user_filter():
        UserFilter.create({
            "allow": {
                "ids_or_emails": [1, 2, "bot@researchhub.com"],
                "percent": {
                    "intervals": [
                        [0, 10],
                        [20, 100]
                    ],
                    "except": [23, 24, "foo@researchhub.com"]
                }
            }
        })

        UserFilter.create({
            "deny": {
                "ids_or_emails": [1, 2, "bot@researchhub.com"],
                "percent": {
                    "intervals": [
                        [0, 10],
                        [20, 100]
                    ],
                    "except": [23, 24, "foo@researchhub.com"]
                }
            }
        })

    def test_create_invalid_user_filter_fails(self):
        # allow or deny are required
        with self.assertRaises(ValidationError):
            UserFilter.create({})

        # only one of allow or deny
        with self.assertRaises(ValidationError):
            UserFilter.create({
                "allow": {},
                "deny": {}
            })

        # nothing else except allow or deny
        with self.assertRaises(ValidationError):
            UserFilter.create({
                "foo": {}
            })

    @patch('user.models.User.objects')
    def test_filter_correct(self, objects):
        filter_result = Mock()
        filter_result.exists.return_value = True

        bot = Mock()
        bot.id = 1071

        foo = Mock()
        foo.id = 1052

        filter_result.first.side_effect = [bot, foo]
        objects.filter.return_value = filter_result

        f = UserFilter.create({
            "allow": {
                # allowed ids: 1001, 1002, 1071
                "ids_or_emails": [1001, 1002, "bot@researchhub.com"],
                "percent": {
                    # all ids with the reversed last two digits in range [0, 10) or [20, 100) are also allowed,
                    # except ids 1023, 1024 and 1052
                    "intervals": [
                        [0, 10],
                        [20, 100]
                    ],
                    "except": [1023, 1024, "foo@researchhub.com"]
                }
            }
        })
        for i in range(1000, 1100):
            if (i % 10 == 1 and i not in [bot.id, 1001]) or (i in [foo.id, 1023, 1024]):
                self.assertFalse(f.is_allowed(i), f"{i} shouldn't be allowed")
            else:
                self.assertTrue(f.is_allowed(i), f"{i} should be allowed")


