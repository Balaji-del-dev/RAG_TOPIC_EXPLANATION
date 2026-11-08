"""
STEP 2 - Query length / size validation                          Tool: Pydantic
==============================================================================

What it protects against
    Very long input costs memory, model time and LLM tokens, and long text is
    where attackers hide instructions. Limits are checked at three levels:

    1. Raw HTTP body  (MAX_BODY_BYTES, default 32 KB)
       Checked by the web framework *before* the JSON is parsed, so a 50 MB body
       is refused without reading it into memory.
         - FastAPI: services/fastapi_service/app/middleware.py
         - Django : DATA_UPLOAD_MAX_MEMORY_SIZE in services/django_service/config/settings.py
    2. Characters     (MAX_QUERY_CHARS, default 4000)   -> Pydantic max_length
       What the user sees and types.
    3. UTF-8 bytes    (MAX_QUERY_BYTES, default 12000)  -> Pydantic AfterValidator
       4000 emoji are 4000 characters but 16000 bytes. Bytes are what storage,
       logs and tokenizers actually pay for. 12000 = 3 bytes x 4000, so every
       script gets the full character limit (Tamil and Hindi use 3 bytes per
       character) while 4-byte floods are cut. A byte limit of 4 x MAX_QUERY_CHARS
       or more could never trigger.

How it works
    `QueryText` is an annotated string type. Step 1's request model declares
    `query: QueryText`, so Pydantic runs these checks automatically:

        Annotated[str,
                  Field(min_length=1, max_length=MAX_QUERY_CHARS),   # characters
                  AfterValidator(check_utf8_size)]                   # bytes

Example
    {"query": "a" * 5000}  ->  REJECT (HTTP 422), error type "string_too_long"
"""

from typing import Annotated

from pydantic import AfterValidator, Field
from pydantic_core import PydanticCustomError

from input_security.settings import get_settings

_settings = get_settings()
MAX_QUERY_CHARS = _settings.max_query_chars
MAX_QUERY_BYTES = _settings.max_query_bytes
MAX_BODY_BYTES = _settings.max_body_bytes

# Pydantic error types that belong to this step (everything else is step 1).
SIZE_ERROR_TYPES = {"string_too_long", "query_too_many_bytes", "body_too_large"}


def utf8_size(text: str) -> int:
    # "surrogatepass" so a broken surrogate is measured here and rejected in step 3.
    return len(text.encode("utf-8", errors="surrogatepass"))


def check_utf8_size(value: str) -> str:
    size = utf8_size(value)
    if size > MAX_QUERY_BYTES:
        raise PydanticCustomError(
            "query_too_many_bytes",
            "Query is {size} bytes in UTF-8; the limit is {limit} bytes.",
            {"size": size, "limit": MAX_QUERY_BYTES},
        )
    return value


QueryText = Annotated[
    str,
    Field(min_length=1, max_length=MAX_QUERY_CHARS),
    AfterValidator(check_utf8_size),
]


def body_too_large(content_length: int, limit: int = MAX_BODY_BYTES) -> bool:
    """Used by the FastAPI and Django adapters before they parse the body."""
    return content_length > limit
