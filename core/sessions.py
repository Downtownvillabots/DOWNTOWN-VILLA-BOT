import time

_sessions = {}

def set_session(user_id, data, timeout=1800):
    data["created_at"] = time.time()
    data["timeout"] = timeout
    _sessions[user_id] = data

def get_session(user_id):
    session = _sessions.get(user_id)
    if session and (time.time() - session["created_at"] > session["timeout"]):
        _sessions.pop(user_id, None)
        return None
    return session

def clear_session(user_id):
    _sessions.pop(user_id, None)
