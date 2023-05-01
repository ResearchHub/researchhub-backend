from typing import Mapping, List, Union, Set

from celery.utils.log import get_task_logger
from jsonschema import validate

logger = get_task_logger(__name__)


class UserFilter:
    """
    A wrapper around an allow-list/block-list configuration which determines whether a user id should be allowed or not
    from a specific feature. When releasing a new feature, this class can be used for gradual rollouts. For example, a
    list of specific users is first allow-listed (e.g. ids [7, 15, 21]); then, 1% of all users, then 10%, 50%, and
    finally 100%.
    """

    FILTER_SCHEMA: Mapping = {
        "type": "object",
        "oneOf": [
            {
                "type": "object",
                "properties": {
                    "allow": {
                        # "type": "integer"
                        "$ref": "#/$defs/allowlist"
                    }
                },
                "additionalProperties": False,
                "required": ["allow"]
            },
            {
                "type": "object",
                "properties": {
                    "deny": {
                        "$ref": "#/$defs/allowlist"
                    }
                },
                "additionalProperties": False,
                "required": ["deny"]
            }
        ],
        "$defs": {
            "allowlist": {
                "type": "object",
                "properties": {
                    "ids_or_emails": {
                        "type": "array",
                        "items": {
                            "type": ["integer", "string"]
                        }
                    },
                    "percent": {
                        "type": "object",
                        "properties": {
                            "intervals": {
                                "type": "array",
                                "items": {
                                    "type": "array",
                                    "minItems": 2,
                                    "maxItems": 2,
                                    "items": {
                                        "type": "integer"
                                    }
                                }
                            },
                            "except": {
                                "type": "array",
                                "items": {
                                    "type": ["integer", "string"]
                                }
                            },
                        },
                        "additionalProperties": False,
                    }
                },
                "additionalProperties": False,
            }
        }
    }
    """
    Defines a JSON Schema that enforces the rules of a user filter.
    """

    @staticmethod
    def create(config: dict):
        """
        Validates the given user filter configuration and creates a UserFilter instance.
        """
        validate(instance=config, schema=UserFilter.FILTER_SCHEMA)
        return UserFilter(config)

    def __init__(self, config: dict):
        self._config = config
        self._usernameToIdMapping: dict = {}

    def is_allowed(self, user_id: int):
        """
        Returns True if the given user id is allowed in the user filter configuration, and False otherwise.
        """
        filter_action_is_allow = self._config.get("allow") is not None
        config_data = self._config.get("allow", self._config.get("deny"))
        ids_or_emails = config_data.get("ids_or_emails")

        if ids_or_emails is not None:
            ids = self._ids_or_emails_to_ids(ids_or_emails)
            if user_id in ids:
                return filter_action_is_allow

        percent = config_data.get("percent")
        if percent is not None:
            except_ids_or_emails = percent.get("except")
            if except_ids_or_emails is not None:
                except_ids = self._ids_or_emails_to_ids(except_ids_or_emails)
                if user_id in except_ids:
                    return not filter_action_is_allow

            intervals = percent.get("intervals")
            if intervals is None:
                return not filter_action_is_allow

            pc = UserFilter._user_id_to_percent(user_id)
            for interval in intervals:
                if interval[0] <= pc < interval[1]:
                    return filter_action_is_allow
            return not filter_action_is_allow

    def _ids_or_emails_to_ids(self, ids_or_emails: List[Union[int, str]]) -> Set[int]:
        from user.models import User
        ids = set()
        for entry in ids_or_emails:
            # entry is a numeric id
            if isinstance(entry, int):
                ids.add(entry)
                continue

            # entry is an email address; we need to resolve the corresponding id
            email_id = self._usernameToIdMapping.get(entry)
            if email_id is None:
                user_query = User.objects.filter(email=entry)
                if user_query.exists():
                    email_id = user_query.first().id
                    self._usernameToIdMapping[entry] = email_id
            if email_id is not None:
                ids.add(email_id)
        return ids

    @staticmethod
    def _user_id_to_percent(user_id: int):
        """
        Returns the last two digits of the given number in reverse. Examples: 123->32, 7->70, 21->12.
        This is done so that the ids are more uniformly distributed across percentage intervals. For
        example, one effect is that consecutive user ids are distributed across different percentage
        intervals.
        """
        last_digit = user_id % 10
        penultimate_digit = int(user_id / 10) % 10
        return last_digit * 10 + penultimate_digit
