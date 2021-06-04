from django.db import models

from researchhub_document.related_models.constants.document_type \
    import DISCUSSION, DOCUMENT_TYPES
from researchhub_document.related_models.researchhub_unified_document_model \
  import ResearchhubUnifiedDocument
from researchhub_document.related_models.constants.editor_type import (
  CK_EDITOR, EDITOR_TYPES,
)
from utils.models import DefaultModel


class ResearchhubPost(DefaultModel):
    discussion_src = models.FileField(
        blank=True,
        default=None,
        max_length=512,
        null=True,
        upload_to='uploads/post_discussion/%Y/%m/%d/',
    )
    document_type = models.CharField(
        choices=DOCUMENT_TYPES,
        default=DISCUSSION,
        max_length=32,
        null=False,
    )
    editor_type = models.CharField(
        choices=EDITOR_TYPES,
        default=CK_EDITOR,
        max_length=32,
        help_text='Editor used to compose the post',
    )
    eln_src = models.FileField(
        blank=True,
        default=None,
        max_length=512,
        null=True,
        upload_to='uploads/post_eln/%Y/%m/%d/',
    )
    prev_version = models.OneToOneField(
        'self',
        blank=True,
        default=None,
        null=True,
        on_delete=models.SET_NULL,
        related_name='next_version',
    )
    renderable_text = models.TextField(
        blank=True,
        default='',
    )
    title = models.TextField(
        blank=True,
        default=''
    )
    unified_document = models.ForeignKey(
        ResearchhubUnifiedDocument,
        db_index=True,
        on_delete=models.CASCADE,
        related_name='posts',
    )
    version_number = models.IntegerField(
        blank=False,
        default=1,
        null=False,
    )

    @property
    def is_latest_version(self):
        return self.next_version is None

    @property
    def is_root_version(self):
        return self.version_number == 1
