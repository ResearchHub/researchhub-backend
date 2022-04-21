from peer_review.models import PeerReview
from hypothesis.models import Hypothesis, Citation
from researchhub_document.models import ResearchhubPost
from paper.models import Paper

RELATED_DISCUSSION_MODELS = {
    'peer_review': PeerReview,
    'citation': Citation,
    'hypothesis': Hypothesis,
    'Hypothesis': Hypothesis,
    'paper': Paper,
    'Paper': Paper,
    'post': ResearchhubPost,
    'ResearchhubPost': ResearchhubPost,
}