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


SignUp = Distribution(
    'SIGN_UP', 25
)

CreatePaper = Distribution(
    'CREATE_PAPER', 1
)
FlagPaper = Distribution(
    'FLAG_PAPER', 1
)
VoteOnPaper = Distribution(
    'VOTE_ON_PAPER', 1
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

CreateComment = Distribution(
    'CREATE_COMMENT', 1
)
VoteOnComment = Distribution(
    'VOTE_ON_COMMENT', 1
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

CreateReply = Distribution(
    'CREATE_REPLY', 1
)
VoteOnReply = Distribution(
    'VOTE_ON_REPLY', 1
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

CreateThread = Distribution(
    'CREATE_THREAD', 1
)
VoteOnThread = Distribution(
    'VOTE_ON_THREAD', 1
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
        SignUp.name,
        SignUp.name
    ),
    (
        CreatePaper.name,
        CreatePaper.name
    ),
    (
        FlagPaper.name,
        FlagPaper.name
    ),
    (
        VoteOnPaper.name,
        VoteOnPaper.name
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
        CreateComment.name,
        CreateComment.name
    ),
    (
        VoteOnComment.name,
        VoteOnComment.name
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
        CreateReply.name,
        CreateReply.name
    ),
    (
        VoteOnReply.name,
        VoteOnReply.name
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
        CreateThread.name,
        CreateThread.name
    ),
    (
        VoteOnThread.name,
        VoteOnThread.name
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
