from .related_models.action_model import Action
from .related_models.author_model import Author
from .related_models.follow_model import Follow
from .related_models.profile_image_storage import ProfileImageStorage
from .related_models.school_model import Major, University
from .related_models.user_model import User
from .related_models.verification_model import Verification

migratables = (
    Action,
    Author,
    Follow,
    Major,
    ProfileImageStorage,
    University,
    User,
    Verification
)
