VERSION = "v2"


def after_save(fail_confirmation, audit):
    """Simulate the confirmation step after SQLite has committed."""
    if fail_confirmation:
        audit("confirmation_failed", 503)
        return 503
    audit("confirmation_sent", 201)
    return 201
