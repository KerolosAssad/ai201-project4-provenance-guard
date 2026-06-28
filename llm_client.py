import os
from groq import Groq
from dotenv import load_dotenv

load_dotenv()

_client = None


def get_client():
    """
    Lazily initializes and returns a singleton Groq client.
    Kept separate from signal logic so the client/credentials can be
    mocked or swapped in tests without touching classification code.
    """
    global _client
    if _client is None:
        api_key = os.environ.get("GROQ_API_KEY")
        if not api_key:
            raise RuntimeError(
                "GROQ_API_KEY is not set. Check your .env file."
            )
        _client = Groq(api_key=api_key)
    return _client