from rest_framework import serializers
from rest_framework.exceptions import AuthenticationFailed
from rest_framework.throttling import ScopedRateThrottle
from rest_framework_simplejwt.serializers import (
  TokenBlacklistSerializer,
  TokenObtainPairSerializer,
  TokenRefreshSerializer,
)
from rest_framework_simplejwt.settings import api_settings
from rest_framework_simplejwt.views import TokenBlacklistView, TokenObtainPairView, TokenRefreshView

from .jwt import RefreshToken
from .models import MyUser
from .roles import ROLE_CLAIM, user_role


class EmailAwareTokenObtainPairSerializer(TokenObtainPairSerializer):
  """Same as the default serializer, but distinguishes "correct password,
  unverified account" from "wrong email/password" so the frontend can point
  the user at the verification flow instead of a generic auth error.

  Also stamps the requester's role into the refresh token (get_token) - from
  where simplejwt copies it into every access token, rotation included - and
  returns it top-level so the sign-in proxy can route without decoding."""

  # Dedicated-key signing with the legacy-verify shim (backend/jwt.py).
  token_class = RefreshToken

  @classmethod
  def get_token(cls, user):
    token = super().get_token(user)
    token[ROLE_CLAIM] = user_role(user)
    return token

  def validate(self, attrs):
    email = attrs.get(self.username_field)
    password = attrs.get('password')
    user = MyUser.objects.filter(email__iexact=email).first()

    if user and not user.is_active and user.check_password(password):
      raise serializers.ValidationError({'detail': 'unverified', 'email': user.email})

    data = super().validate(attrs)
    data['role'] = user_role(self.user)
    return data


class RoleStampingTokenRefreshSerializer(TokenRefreshSerializer):
  """Re-derives the role claim from the DB on every refresh (simplejwt copies
  claims verbatim otherwise), so:
  - refresh tokens minted before the claim existed self-heal on their first
    exchange instead of forcing a re-login, and
  - a role edit can never outlive one access-token lifetime.

  Mirrors TokenRefreshSerializer.validate (simplejwt 5.5.0) - super() can't be
  used because it mints the access token before the claim could be stamped.
  Wired via SIMPLE_JWT['TOKEN_REFRESH_SERIALIZER'] and the view below."""

  token_class = RefreshToken

  def validate(self, attrs):
    refresh = self.token_class(attrs['refresh'])

    user = None
    user_id = refresh.payload.get(api_settings.USER_ID_CLAIM, None)
    if user_id and (user := MyUser.objects.get(**{api_settings.USER_ID_FIELD: user_id})):
      if not api_settings.USER_AUTHENTICATION_RULE(user):
        raise AuthenticationFailed(self.error_messages['no_active_account'], 'no_active_account')
      # Stamp BEFORE minting the access token: claims copy refresh -> access,
      # so both tokens leave here carrying the user's CURRENT role.
      refresh[ROLE_CLAIM] = user_role(user)

    data = {'access': str(refresh.access_token)}

    if api_settings.ROTATE_REFRESH_TOKENS:
      if api_settings.BLACKLIST_AFTER_ROTATION:
        try:
          refresh.blacklist()
        except AttributeError:
          pass

      refresh.set_jti()
      refresh.set_exp()
      refresh.set_iat()
      refresh.outstand()

      data['refresh'] = str(refresh)

    if user is not None:
      data['role'] = user_role(user)

    return data


class SignOutTokenBlacklistSerializer(TokenBlacklistSerializer):
  # The dual backend must verify legacy-signed tokens here too, or a session
  # from before the key rotation couldn't revoke itself on sign-out.
  token_class = RefreshToken


class EmailAwareTokenObtainPairView(TokenObtainPairView):
  serializer_class = EmailAwareTokenObtainPairSerializer
  # Brute-force guard, keyed per IP for anonymous requests. Failed attempts
  # count too - that's the point.
  throttle_classes = [ScopedRateThrottle]
  throttle_scope = 'login'


class RoleStampingTokenRefreshView(TokenRefreshView):
  serializer_class = RoleStampingTokenRefreshSerializer
  # Sized well above the middleware's single-flight cadence (one exchange per
  # session per access lifetime) - this only stops runaway loops.
  throttle_classes = [ScopedRateThrottle]
  throttle_scope = 'token_refresh'


class SignOutTokenBlacklistView(TokenBlacklistView):
  serializer_class = SignOutTokenBlacklistSerializer
