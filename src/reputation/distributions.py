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


UPVOTE_RSC = 0.01
DOWNVOTE_RSC = -0.01
FLAG_RSC = -0.02
CENSOR_RSC = -0.02

FlagPaper = Distribution("FLAG_PAPER", FLAG_RSC, give_rep=True, reputation=-1)


RhCommentCensored = Distribution(
    "RhCOMMENT_CENSORED", CENSOR_RSC, give_rep=True, reputation=-2
)
RhCommentFlagged = Distribution(
    "RhCOMMENT_FLAGGED", FLAG_RSC, give_rep=True, reputation=-2
)


CommentCensored = Distribution(
    "COMMENT_CENSORED", CENSOR_RSC, give_rep=True, reputation=-2
)
CommentFlagged = Distribution("COMMENT_FLAGGED", FLAG_RSC, give_rep=True, reputation=-2)


ReplyCensored = Distribution("REPLY_CENSORED", CENSOR_RSC, give_rep=True, reputation=-2)
ReplyFlagged = Distribution("REPLY_FLAGGED", FLAG_RSC, give_rep=True, reputation=-2)


ThreadCensored = Distribution(
    "THREAD_CENSORED", CENSOR_RSC, give_rep=True, reputation=-2
)
ThreadFlagged = Distribution("THREAD_FLAGGED", FLAG_RSC, give_rep=True, reputation=-2)


ResearchhubPostCensored = Distribution(
    "RESEARCHHUB_POST_CENSORED", CENSOR_RSC, give_rep=True, reputation=-2
)


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
    (CommentCensored.name, CommentCensored.name),
    (CommentFlagged.name, CommentFlagged.name),
    (ReplyCensored.name, ReplyCensored.name),
    (ReplyFlagged.name, ReplyFlagged.name),
    (ThreadCensored.name, ThreadCensored.name),
    (ThreadFlagged.name, ThreadFlagged.name),
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
