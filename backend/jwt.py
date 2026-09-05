"""Dedicated-key JWT signing with a dual-verify transition shim.

Tokens are SIGNED with JWT_SIGNING_KEY (a secret of its own, so the frontend
edge can verify signatures without ever holding SECRET_KEY - the key behind
password-reset/email-change links and sessions). Tokens are VERIFIED with the
dedicated key first, then - transition only - with the legacy SECRET_KEY, so
sessions issued before the key switch keep working until their refresh token
rotates onto the new key.

REMOVE the legacy fallback (the second backend in _backends) once every
pre-switch refresh token has aged out: >= REFRESH_TOKEN_LIFETIME (10 days)
after the key ships.

Settings are read per call (not cached at import) so override_settings works
in tests; building an HS256 TokenBackend is trivially cheap.
"""

from django.conf import settings
from rest_framework_simplejwt import tokens as simplejwt_tokens
from rest_framework_simplejwt.backends import TokenBackend
from rest_framework_simplejwt.exceptions import TokenBackendError


def _signing_key():
  # Unset/empty falls back to SECRET_KEY: dev and CI keep working with no env,
  # and the dual verify degenerates to a single backend.
  return getattr(settings, 'JWT_SIGNING_KEY', '') or settings.SECRET_KEY


def _backends():
  primary = TokenBackend(algorithm='HS256', signing_key=_signing_key())
  legacy = TokenBackend(algorithm='HS256', signing_key=settings.SECRET_KEY)
  return primary, legacy


class DualHS256Backend:
  """Encode with the dedicated key; decode with it, falling back to the
  legacy SECRET_KEY during the rotation window.

  Duck-types the TokenBackend surface simplejwt actually calls on a token's
  backend: encode, decode and get_leeway (Token.check_exp)."""

  def get_leeway(self):
    primary, _ = _backends()
    return primary.get_leeway()

  def encode(self, payload):
    primary, _ = _backends()
    return primary.encode(payload)

  def decode(self, token, verify=True):
    primary, legacy = _backends()
    try:
      return primary.decode(token, verify)
    except TokenBackendError:
      if legacy.signing_key == primary.signing_key:
        raise
      return legacy.decode(token, verify)


class AccessToken(simplejwt_tokens.AccessToken):
  _token_backend = DualHS256Backend()


class RefreshToken(simplejwt_tokens.RefreshToken):
  _token_backend = DualHS256Backend()
  access_token_class = AccessToken
