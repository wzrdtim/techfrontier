class AdminLoginRequired(Exception):
    """Raised when an admin HTML page is requested without a valid admin session."""
