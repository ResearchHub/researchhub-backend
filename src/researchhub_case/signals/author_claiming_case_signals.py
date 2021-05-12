import logging

from django.db.models.signals import post_save
from django.dispatch import receiver

from researchhub_case.constants.case_constants import INITIATED
from researchhub_case.models import AuthorClaimCase
from researchhub_case.utils.author_claim_case_utils import (
  get_new_validation_token,
  send_validation_email,
)


@receiver(
    post_save,
    sender=AuthorClaimCase,
    dispatch_uid='author_claim_case_post_create_signal',
)
def author_claim_case_post_create_signal(
    sender,
    instance,
    created,
    update_fields,
    **kwargs
):
    if (
      created
      and instance.status == INITIATED
      and instance.validation_token is None
    ):
        try:
            [generated_time, token] = get_new_validation_token()
            instance.token_generated_time = generated_time
            instance.validation_token = token
            # Note: intentionally sending email before incrementing attempt
            send_validation_email(instance)
            instance.validation_attempt_count += 1
            instance.save()
        except Exception as exception:
            logging.warning(exception)
