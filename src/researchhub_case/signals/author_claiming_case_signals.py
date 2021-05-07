from django.db.models.signals import post_save
from django.dispatch import receiver

from researchhub_case.constants.case_constants import AUTHOR_CLAIM_CASE_STATUS
from researchhub_case.models import AuthorClaimCase
from researchhub_case.utils import (
  encode_validation_token,
  format_valid_ids,
  send_validation_email
)


@receiver(
    post_save,
    dispatch_uid='author_claim_case_post_save_signal',
    sender=AuthorClaimCase,
)
def author_claim_case_post_save_signal(
    sender,
    instance,
    created,
    update_fields,
    **kwargs
):
    if (
      created
      and instance.status == AUTHOR_CLAIM_CASE_STATUS.OPEN
      and instance.validation_token is None
    ):
        target_author = instance.target_author
        requestor = instance.requestor
        new_token = encode_validation_token(
          format_valid_ids(instance, requestor, target_author)
        )
        instance.new_token = new_token
        send_validation_email(instance)
        instance.validation_attempt_count += 1
        instance.save()
