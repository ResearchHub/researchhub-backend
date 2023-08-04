from .follow_model import Follow
from .gatekeeper_model import Gatekeeper
from .organization_model import Organization
from .profile_image_storage import ProfileImageStorage
from .school_model import Major, University
from .user_api_token_model import UserApiToken
from .user_model import User
from .verdict_model import Verdict
from .verification_model import Verification

migratables = (
    Follow,
    Major,
    ProfileImageStorage,
    University,
    User,
    Verification,
    Organization,
    Gatekeeper,
    UserApiToken,
    Verdict,
)
