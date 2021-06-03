from django.db import models

from researchhub_document.related_models.researchhub_unified_document_model \
  import ResearchhubUnifiedDocument
from researchhub_document.related_models.constants.document_type import (
  DISCUSSION, POST_TYPES
)


class ResearchhubPost(models.Model):
    post_type = models.CharField(
      blank=False,
      choices=POST_TYPES,
      default=DISCUSSION,
      max_length=32,
      null=False,
    )
    prev_version = models.OneToOneField(
        'self',
        blank=True,
        default=None,
        null=True,
        on_delete=models.SET_NULL,
        related_name="next_version",
    )
    unified_document = models.ForeignKey(
        ResearchhubUnifiedDocument,
        db_index=True,
        on_delete=models.CASCADE,
        related_name="posts",
    )
    version_number = models.IntegerField(
        blank=False,
        default=1,
        null=False,
    )

    def is_latest_version(self):
        return self.next_version is None

    def is_root_version(self):
        return self.version_number == 1
