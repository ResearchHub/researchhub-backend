from .related_models.action_model import Action
from .related_models.author_model import Author
from .related_models.follow_model import Follow
from .related_models.gatekeeper_model import Gatekeeper
from .related_models.organization_model import Organization
from .related_models.profile_image_storage import ProfileImageStorage
from .related_models.school_model import Major, University
from .related_models.user_api_token_model import UserApiToken
from .related_models.user_model import User
from .related_models.verdict_model import Verdict

migratables = (
    Action,
    Author,
    Follow,
    Major,
    ProfileImageStorage,
    University,
    User,
    Organization,
    Gatekeeper,
    UserApiToken,
    Verdict,
)
