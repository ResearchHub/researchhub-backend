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


CreatePaper = Distribution(
    'CREATE_PAPER', 1
)
CreateAuthoredPaper = Distribution(
    'CREATE_AUTHORED_PAPER', 9
)
VoteOnPaper = Distribution(
    'VOTE_ON_PAPER', 1
)

CreateComment = Distribution(
    'CREATE_COMMENT', 1
)
VoteOnComment = Distribution(
    'VOTE_ON_COMMENT', 1
)
CommentEndorsed = Distribution(
    'COMMENT_ENDORSED', 15
)
CommentFlagged = Distribution(
    'COMMENT_FLAGGED', -2
)
CommentUpvoted = Distribution(
    'COMMENT_UPVOTED', 5
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
ReplyEndorsed = Distribution(
    'REPLY_ENDORSED', 15
)
ReplyFlagged = Distribution(
    'REPLY_FLAGGED', -2
)
ReplyUpvoted = Distribution(
    'REPLY_UPVOTED', 5
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
ThreadEndorsed = Distribution(
    'THREAD_ENDORSED', 15
)
ThreadFlagged = Distribution(
    'THREAD_FLAGGED', -2
)
ThreadUpvoted = Distribution(
    'THREAD_UPVOTED', 5
)
ThreadDownvoted = Distribution(
    'THREAD_DOWNVOTED', -1
)

CreateSummary = Distribution(
    'CREATE_SUMMARY', 1
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
        CreatePaper.name,
        CreatePaper.name
    ),
    (
        VoteOnPaper.name,
        VoteOnPaper.name
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
        CommentEndorsed.name,
        CommentEndorsed.name
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
        ReplyEndorsed.name,
        ReplyEndorsed.name
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
        ThreadEndorsed.name,
        ThreadEndorsed.name
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
