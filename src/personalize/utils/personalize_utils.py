from datetime import datetime


def build_session_id_for_user(user_id: int, timestamp: datetime) -> str:
    date_str = timestamp.strftime("%Y_%m_%d")
    return f"sess_user_{user_id}_{date_str}"


def build_session_id_for_anonymous(external_user_id: str) -> str:
    return f"sess_anon_{external_user_id}"
