class Distribution:
    def __init__(self, name, amount, give_rep=True, reputation=1):
        self._name = name
        self._amount = amount
        self._reputation = reputation
        self._give_rep = give_rep

    @property
    def reputation(self):
        return self._reputation

    @property
    def name(self):
        return self._name

    @property
    def amount(self):
        return self._amount

    @property
    def gives_rep(self):
        return self._give_rep


FlagPaper = Distribution("FLAG_PAPER", -1, give_rep=True, reputation=-1)
PaperUpvoted = Distribution("PAPER_UPVOTED", 1, give_rep=True, reputation=1)
PaperDownvoted = Distribution("PAPER_Downvoted", -1, give_rep=True, reputation=-1)

CreateBulletPoint = Distribution("CREATE_BULLET_POINT", 1, give_rep=True, reputation=1)
BulletPointCensored = Distribution(
    "BULLET_POINT_CENSORED", -2, give_rep=True, reputation=-2
)
BulletPointFlagged = Distribution(
    "BULLET_POINT_FLAGGED", -2, give_rep=True, reputation=-2
)
BulletPointUpvoted = Distribution(
    "BULLET_POINT_UPVOTED", 1, give_rep=True, reputation=1
)
BulletPointDownvoted = Distribution(
    "BULLET_POINT_DOWNVOTED", -1, give_rep=True, reputation=-1
)

RhCommentCensored = Distribution("RhCOMMENT_CENSORED", -2, give_rep=True, reputation=-2)
RhCommentFlagged = Distribution("RhCOMMENT_FLAGGED", -2, give_rep=True, reputation=-2)
RhCommentUpvoted = Distribution("RhCOMMENT_UPVOTED", 1, give_rep=True, reputation=1)
RhCommentDownvoted = Distribution(
    "RhCOMMENT_DOWNVOTED", -1, give_rep=True, reputation=-1
)

CommentCensored = Distribution("COMMENT_CENSORED", -2, give_rep=True, reputation=-2)
CommentFlagged = Distribution("COMMENT_FLAGGED", -2, give_rep=True, reputation=-2)
CommentUpvoted = Distribution("COMMENT_UPVOTED", 1, give_rep=True, reputation=1)
CommentDownvoted = Distribution("COMMENT_DOWNVOTED", -1, give_rep=True, reputation=-1)

ReplyCensored = Distribution("REPLY_CENSORED", -2, give_rep=True, reputation=-2)
ReplyFlagged = Distribution("REPLY_FLAGGED", -2, give_rep=True, reputation=-2)
ReplyUpvoted = Distribution("REPLY_UPVOTED", 1, give_rep=True, reputation=2)
ReplyDownvoted = Distribution("REPLY_DOWNVOTED", -1, True, -1)

ThreadCensored = Distribution("THREAD_CENSORED", -2, give_rep=True, reputation=-2)
ThreadFlagged = Distribution("THREAD_FLAGGED", -2, give_rep=True, reputation=-2)
ThreadUpvoted = Distribution("THREAD_UPVOTED", 1, give_rep=True, reputation=-2)
ThreadDownvoted = Distribution("THREAD_DOWNVOTED", -1, give_rep=True, reputation=-1)

HypothesisUpvoted = Distribution("HYPOTHESIS_UPVOTED", 1, give_rep=True, reputation=-1)
HypothesisDownvoted = Distribution(
    "HYPOTHESIS_DOWNVOTED", -1, give_rep=True, reputation=-1
)
CitationUpvoted = Distribution("CITATION_UPVOTED", 1, give_rep=True, reputation=-1)
CitationDownvoted = Distribution("CITATION_DOWNVOTED", -1, give_rep=True, reputation=-1)

CreateSummary = Distribution("CREATE_SUMMARY", 1, give_rep=True, reputation=-1)
CreateFirstSummary = Distribution(
    "CREATE_FIRST_SUMMARY", 5, give_rep=True, reputation=5
)
SummaryApproved = Distribution("SUMMARY_APPROVED", 15, give_rep=True, reputation=15)
SummaryRejected = Distribution("SUMMARY_REJECTED", -2, give_rep=True, reputation=-2)
SummaryFlagged = Distribution("SUMMARY_FLAGGED", -5, give_rep=True, reputation=-5)
SummaryUpvoted = Distribution("SUMMARY_UPVOTED", 1, give_rep=True, reputation=-1)
SummaryDownvoted = Distribution("SUMMARY_DOWNVOTED", -1, give_rep=True, reputation=-1)
ResearchhubPostUpvoted = Distribution(
    "RESEARCHHUB_POST_UPVOTED", 1, give_rep=True, reputation=1
)
ResearchhubPostDownvoted = Distribution(
    "RESEARCHHUB_POST_DOWNVOTED", -1, give_rep=True, reputation=-1
)
ResearchhubPostCensored = Distribution(
    "RESEARCHHUB_POST_CENSORED", -2, give_rep=True, reputation=-2
)
NeutralVote = Distribution("NEUTRAL_VOTE", 0, give_rep=False, reputation=0)


def create_purchase_distribution(user, amount):
    return Distribution("PURCHASE", amount, False)


def create_fundraise_rh_fee_distribution(amount):
    distribution = Distribution("FUNDRAISE_RH_FEE", amount, give_rep=False)
    return distribution


def create_fundraise_dao_fee_distribution(amount):
    distribution = Distribution("FUNDRAISE_DAO_FEE", amount, give_rep=False)
    return distribution


def create_fundraise_distribution(amount):
    distribution = Distribution("FUNDRAISE_PAYOUT", amount, give_rep=False)
    return distribution


def create_support_rh_fee_distribution(amount):
    distribution = Distribution("SUPPORT_RH_FEE", amount, give_rep=False)
    return distribution


def create_support_dao_fee_distribution(amount):
    distribution = Distribution("SUPPORT_DAO_FEE", amount, give_rep=False)
    return distribution


def create_bounty_rh_fee_distribution(amount):
    distribution = Distribution("BOUNTY_RH_FEE", amount, give_rep=False)
    return distribution


def create_bounty_dao_fee_distribution(amount):
    distribution = Distribution("BOUNTY_DAO_FEE", amount, give_rep=False)
    return distribution


def create_bounty_distriution(amount):
    distribution = Distribution("BOUNTY_PAYOUT", amount, give_rep=False)
    return distribution


def create_bounty_refund_distribution(amount):
    distribution = Distribution("BOUNTY_REFUND", amount, give_rep=False)
    return distribution


def create_stored_paper_pot(amount):
    distribution = Distribution("STORED_PAPER_POT", amount, give_rep=False)
    return distribution


def create_paper_reward_distribution(amount):
    distribution = Distribution("PAPER_REWARD", amount, give_rep=False)
    return distribution


DISTRIBUTION_TYPE_CHOICES = [
    (FlagPaper.name, FlagPaper.name),
    (PaperUpvoted.name, PaperUpvoted.name),
    (PaperDownvoted.name, PaperDownvoted.name),
    (CreateBulletPoint.name, CreateBulletPoint.name),
    (BulletPointFlagged.name, BulletPointFlagged.name),
    (BulletPointUpvoted.name, BulletPointUpvoted.name),
    (BulletPointDownvoted.name, BulletPointDownvoted.name),
    (CommentCensored.name, CommentCensored.name),
    (CommentFlagged.name, CommentFlagged.name),
    (CommentUpvoted.name, CommentUpvoted.name),
    (CommentDownvoted.name, CommentDownvoted.name),
    (ReplyCensored.name, ReplyCensored.name),
    (ReplyFlagged.name, ReplyFlagged.name),
    (ReplyUpvoted.name, ReplyUpvoted.name),
    (ReplyDownvoted.name, ReplyDownvoted.name),
    (ThreadCensored.name, ThreadCensored.name),
    (ThreadFlagged.name, ThreadFlagged.name),
    (ThreadUpvoted.name, ThreadUpvoted.name),
    (ThreadDownvoted.name, ThreadDownvoted.name),
    (CreateSummary.name, CreateSummary.name),
    (SummaryUpvoted.name, SummaryUpvoted.name),
    (SummaryDownvoted.name, SummaryDownvoted.name),
    (HypothesisUpvoted.name, HypothesisUpvoted.name),
    (HypothesisDownvoted.name, HypothesisDownvoted.name),
    ("UPVOTE_RSC_POT", "UPVOTE_RSC_POT"),
    ("STORED_PAPER_POT", "STORED_PAPER_POT"),
    ("PAPER_REWARD", "PAPER_REWARD"),
    ("REWARD", "REWARD"),
    ("PURCHASE", "PURCHASE"),
    (
        "EDITOR_COMPENSATION",
        "EDITOR_COMPENSATION",
    ),
    (
        "EDITOR_PAYOUT",
        "EDITOR_PAYOUT",
    ),
]
