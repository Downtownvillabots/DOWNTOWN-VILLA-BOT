from config import ADMINS

def is_admin(user_id):
    return user_id in ADMINS
