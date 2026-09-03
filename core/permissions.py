from config import OWNER_IDS, ADMIN_IDS, SUDO_IDS

def is_owner(user_id):
    return user_id in OWNER_IDS

def is_admin(user_id):
    return user_id in OWNER_IDS or user_id in ADMIN_IDS or user_id in SUDO_IDS

def is_sudo(user_id):
    return user_id in OWNER_IDS or user_id in SUDO_IDS

def has_permission(user_id, level="admin"):
    if is_owner(user_id):
        return True
    if level == "owner":
        return False
    if level == "sudo":
        return is_sudo(user_id)
    return is_admin(user_id)