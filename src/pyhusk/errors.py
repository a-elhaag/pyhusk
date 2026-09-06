class PyhuskError(Exception):
    """Base for every error pyhusk raises deliberately.

    The CLI catches this and prints the message without a traceback. Anything
    that is not a PyhuskError is a bug and should surface its traceback.
    """
