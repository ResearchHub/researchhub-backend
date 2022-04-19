from django.core.management.base import BaseCommand
from researchhub_document.models import ResearchhubUnifiedDocument
from user.models import User
from peer_review.models import PeerReviewRequest
from dateutil import parser


class Command(BaseCommand):

    def add_arguments(self, parser):
        parser.add_argument(
            '--uni_doc',
            default=False,
            help='ID of the unified doc in reference'
        )


    def handle(self, *args, **options):
        uni_doc = ResearchhubUnifiedDocument.objects.get(id=options['uni_doc'])
        print('UniDoc:', uni_doc)
        requested_by = User.objects.get(id=uni_doc.authors.first().user.id)
        print('Requesting author:', requested_by)
        post = uni_doc.get_document()
        print('Related post:', post)
        note = post.note
        print('Related note:', note)
        organization = note.organization
        print('Related org:', organization)
        doc_version = note.latest_version
        print('Latest version:', doc_version)

        review_req = PeerReviewRequest.objects.create(
            unified_document=uni_doc,
            requested_by_user=requested_by,
            doc_version=doc_version,
        )

        print('-------------------------------')
        print('Peer Review Request:', review_req.__dict__)
