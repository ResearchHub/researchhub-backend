class Distribution:
    def __init__(self, name, amount, give_rep=True):
        self._name = name
        self._amount = amount
        self._give_rep = give_rep

    @property
    def name(self):
        return self._name

    @property
    def amount(self):
        return self._amount

    @property
    def gives_rep(self):
        return self._give_rep


FlagPaper = Distribution(
    'FLAG_PAPER', 1
)
PaperUpvoted = Distribution(
    'PAPER_UPVOTED', 1
)

CreateBulletPoint = Distribution(
    'CREATE_BULLET_POINT', 1
)
BulletPointCensored = Distribution(
    'BULLET_POINT_CENSORED', -2
)
BulletPointFlagged = Distribution(
    'BULLET_POINT_FLAGGED', -2
)
BulletPointUpvoted = Distribution(
    'BULLET_POINT_UPVOTED', 1
)
BulletPointDownvoted = Distribution(
    'BULLET_POINT_DOWNVOTED', -1
)

CommentCensored = Distribution(
    'COMMENT_CENSORED', -2
)
CommentFlagged = Distribution(
    'COMMENT_FLAGGED', -2
)
CommentUpvoted = Distribution(
    'COMMENT_UPVOTED', 1
)
CommentDownvoted = Distribution(
    'COMMENT_DOWNVOTED', -1
)

ReplyCensored = Distribution(
    'REPLY_CENSORED', -2
)
ReplyFlagged = Distribution(
    'REPLY_FLAGGED', -2
)
ReplyUpvoted = Distribution(
    'REPLY_UPVOTED', 1
)
ReplyDownvoted = Distribution(
    'REPLY_DOWNVOTED', -1
)

ThreadCensored = Distribution(
    'THREAD_CENSORED', -2
)
ThreadFlagged = Distribution(
    'THREAD_FLAGGED', -2
)
ThreadUpvoted = Distribution(
    'THREAD_UPVOTED', 1
)
ThreadDownvoted = Distribution(
    'THREAD_DOWNVOTED', -1
)

CreateSummary = Distribution(
    'CREATE_SUMMARY', 1
)
CreateFirstSummary = Distribution(
    'CREATE_FIRST_SUMMARY', 5
)
SummaryApproved = Distribution(
    'SUMMARY_APPROVED', 15
)
SummaryRejected = Distribution(
    'SUMMARY_REJECTED', -2
)
SummaryFlagged = Distribution(
    'SUMMARY_FLAGGED', -5
)
SummaryUpvoted = Distribution(
    'SUMMARY_UPVOTED', 1
)
SummaryDownvoted = Distribution(
    'SUMMARY_DOWNVOTED', -1
)
Referral = Distribution(
    'REFERRAL', 50, False
)

ReferralApproved = Distribution(
    'REFERRAL_APPROVED', 1000, False
)


def create_purchase_distribution(amount):
    return Distribution(
        'PURCHASE', amount
    )


DISTRIBUTION_TYPE_CHOICES = [
    (
        FlagPaper.name,
        FlagPaper.name
    ),
    (
        PaperUpvoted.name,
        PaperUpvoted.name
    ),
    (
        CreateBulletPoint.name,
        CreateBulletPoint.name
    ),
    (
        BulletPointFlagged.name,
        BulletPointFlagged.name
    ),
    (
        BulletPointUpvoted.name,
        BulletPointUpvoted.name
    ),
    (
        BulletPointDownvoted.name,
        BulletPointDownvoted.name
    ),
    (
        CommentCensored.name,
        CommentCensored.name
    ),
    (
        CommentFlagged.name,
        CommentFlagged.name
    ),
    (
        CommentUpvoted.name,
        CommentUpvoted.name
    ),
    (
        CommentDownvoted.name,
        CommentDownvoted.name
    ),
    (
        ReplyCensored.name,
        ReplyCensored.name
    ),
    (
        ReplyFlagged.name,
        ReplyFlagged.name
    ),
    (
        ReplyUpvoted.name,
        ReplyUpvoted.name
    ),
    (
        ReplyDownvoted.name,
        ReplyDownvoted.name
    ),
    (
        ThreadCensored.name,
        ThreadCensored.name
    ),
    (
        ThreadFlagged.name,
        ThreadFlagged.name
    ),
    (
        ThreadUpvoted.name,
        ThreadUpvoted.name
    ),
    (
        ThreadDownvoted.name,
        ThreadDownvoted.name
    ),
    (
        CreateSummary.name,
        CreateSummary.name
    ),
    (
        SummaryUpvoted.name,
        SummaryUpvoted.name
    ),
    (
        SummaryDownvoted.name,
        SummaryDownvoted.name
    ),
    (
        'REWARD',
        'REWARD'
    ),
    (
        'PURCHASE',
        'PURCHASE'
    ),
    (
        Referral.name,
        Referral.name
    )
]
