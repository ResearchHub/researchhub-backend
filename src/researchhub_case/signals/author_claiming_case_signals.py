import logging

from django.db.models.signals import post_save
from django.dispatch import receiver

from researchhub_case.constants.case_constants import APPROVED, INITIATED
from researchhub_case.models import AuthorClaimCase
from researchhub_case.utils.author_claim_case_utils import (
  get_new_validation_token,
  reward_author_claim_case,
  send_validation_email,
)
from user.utils import merge_author_profiles


@receiver(
    post_save,
    sender=AuthorClaimCase,
    dispatch_uid='author_claim_case_post_create_signal',
)
def author_claim_case_post_create_signal(
    created,
    instance,
    sender,
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


@receiver(
    post_save,
    sender=AuthorClaimCase,
    dispatch_uid='merge_author_upon_approval',
)
def merge_author_upon_approval(
    created,
    instance,
    sender,
    update_fields,
    **kwargs
):
    if (
        created is not True
        and instance.status == APPROVED
        and instance.validation_token is not None
        and instance.target_author.user is None
    ):
        try:
            requestor_author = instance.requestor.author_profile
            target_author_papers = instance.target_author.authored_papers
            merge_author_profiles(requestor_author, instance.target_author)
            reward_author_claim_case(requestor_author, target_author_papers)
        except Exception as exception:
            logging.warning(exception)
