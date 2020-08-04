class Distribution:
    def __init__(self, name, amount):
        self._name = name
        self._amount = amount

    @property
    def name(self):
        return self._name

    @property
    def amount(self):
        return self._amount


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
]
