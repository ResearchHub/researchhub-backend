import os


def get_env_var(name, default=''):
    return os.environ.get(name, default)
