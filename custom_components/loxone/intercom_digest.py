"""
RFC 2617 MD5 digest auth for the Loxone intercom video proxy.

Reimplements the algorithm the official app uses for the Miniserver's
``/proxy/`` MJPEG endpoint (``com.loxone.videoproxy.shared.DigestAuthKt`` /
``AuthState``): MD5 or MD5-sess, ``qop=auth``, with the digest ``uri``
stripped of the ``/proxy/<uuid>`` prefix on a Remote Connect (dyndns) relay.
"""

from __future__ import annotations

import hashlib
import os
import re

# The app matches ``/proxy/<uuid>`` (optional) followed by the rest of the
# path; group 2 of the regex is the digest URI for a Remote Connect relay.
_PROXY_PREFIX_RE = re.compile(
    r"(/proxy/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})?(/?.*)",
    re.IGNORECASE,
)
_CHALLENGE_RE = re.compile(r'(\w+)\s*=\s*(?:"((?:[^"\\]|\\.)*)"|([^\s,]+))')


def _md5(text: str) -> str:
    return hashlib.md5(text.encode("utf-8")).hexdigest()


def parse_digest_challenge(header: str) -> dict[str, str]:
    """Parse a ``WWW-Authenticate: Digest …`` header into a params dict.

    Returns ``{}`` if ``header`` is not a Digest challenge.
    """
    if not header or "digest" not in header.lower():
        return {}
    body = re.sub(r"^\s*digest\s+", "", header, flags=re.IGNORECASE)
    params: dict[str, str] = {}
    for match in _CHALLENGE_RE.finditer(body):
        key = match.group(1).lower()
        value = match.group(2) if match.group(2) is not None else (match.group(3) or "")
        params[key] = value.replace('\\"', '"').replace("\\\\", "\\")
    params.setdefault("algorithm", "MD5")
    return params


def digest_uri(path_and_query: str, is_remote: bool) -> str:
    """The ``uri`` field of the digest response.

    Matches the app's ``adoptUri``: on a Remote Connect (dyndns) relay the
    ``/proxy/<uuid>`` prefix is dropped, otherwise the full path is kept.
    """
    if not is_remote:
        return path_and_query
    match = _PROXY_PREFIX_RE.match(path_and_query)
    if match:
        rest = match.group(2)
        return rest or "/"
    return path_and_query


def build_digest_header(
    username: str,
    password: str,
    method: str,
    uri: str,
    challenge: dict[str, str],
    *,
    nc: int = 1,
    cnonce: str | None = None,
) -> str:
    """Build ``Authorization: Digest …`` for ``challenge`` (MD5 / MD5-sess)."""
    realm = challenge.get("realm", "")
    nonce = challenge.get("nonce", "")
    qop = challenge.get("qop")
    opaque = challenge.get("opaque")
    algorithm = challenge.get("algorithm", "MD5")
    if cnonce is None:
        cnonce = hashlib.md5(os.urandom(16)).hexdigest()
    nc_hex = f"{nc:08x}"

    ha1 = _md5(f"{username}:{realm}:{password}")
    if algorithm.lower().endswith("-sess"):
        ha1 = _md5(f"{ha1}:{nonce}:{cnonce}")
    ha2 = _md5(f"{method}:{uri}")
    if qop is not None:
        response = _md5(f"{ha1}:{nonce}:{nc_hex}:{cnonce}:auth:{ha2}")
    else:
        response = _md5(f"{ha1}:{nonce}:{ha2}")

    parts = [
        f'username="{username}"',
        f'realm="{realm}"',
        f'nonce="{nonce}"',
        f'uri="{uri}"',
        f'response="{response}"',
    ]
    if opaque:
        parts.append(f'opaque="{opaque}"')
    if qop is not None:
        parts.append("qop=auth")
    parts.append(f"algorithm={algorithm}")
    parts.append(f"nc={nc_hex}")
    parts.append(f'cnonce="{cnonce}"')
    return "Digest " + ", ".join(parts)
