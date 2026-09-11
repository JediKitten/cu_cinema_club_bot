from app.models.achievement import Achievement
from app.models.base import Base
from app.models.catalog import Film, FilmRequest, Referral, TmdbSyncState, Watch
from app.models.cycle import (
    Attendance,
    AutopilotProposal,
    Availability,
    CancelRequest,
    Confirmation,
    Feedback,
    FilmVote,
    Hall,
    Round,
    Screening,
    ShortlistItem,
    Slot,
)
from app.models.interest import Interest
from app.models.rating import FilmRating
from app.models.skip import FilmSkip
from app.models.social import Favourite, Friendship
from app.models.system import AuditLog, InviteCode, Notification, Setting
from app.models.tournament import (
    Tournament,
    TournamentMatch,
    TournamentOption,
    TournamentVote,
)
from app.models.user import User

__all__ = [
    "Achievement",
    "Attendance",
    "AuditLog",
    "AutopilotProposal",
    "Availability",
    "Base",
    "CancelRequest",
    "Confirmation",
    "Favourite",
    "Feedback",
    "Film",
    "FilmRating",
    "FilmRequest",
    "FilmSkip",
    "FilmVote",
    "Friendship",
    "Hall",
    "Interest",
    "InviteCode",
    "Notification",
    "Referral",
    "Round",
    "Screening",
    "Setting",
    "ShortlistItem",
    "Slot",
    "TmdbSyncState",
    "Tournament",
    "TournamentMatch",
    "TournamentOption",
    "TournamentVote",
    "User",
    "Watch",
]
