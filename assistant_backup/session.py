"""Anonymous ownership of conversations through the Django session."""


def get_owner_key(request):
    """
    Return this browser's session key, creating the session first if needed.
    Conversations are stored with this key and only found again with it.
    """
    session = request.session
    if not session.session_key:
        # Store a marker so the session is saved and its cookie is sent back.
        session["ecommerceai"] = True
        session.save()
    return session.session_key
