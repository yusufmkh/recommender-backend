from django.contrib.auth.tokens import PasswordResetTokenGenerator
from django.utils.crypto import constant_time_compare
from django.utils.http import base36_to_int


class TimeoutTokenGenerator(PasswordResetTokenGenerator):
  """A PasswordResetTokenGenerator with its own lifetime. Django's check_token
  reads the global PASSWORD_RESET_TIMEOUT (1 hour here, for reset/email-change
  links); subclasses set `timeout` for links that must live longer."""

  timeout = 60 * 60 * 24 * 3

  def check_token(self, user, token):
    if not (user and token):
      return False
    try:
      ts_b36, _ = token.split('-')
      ts = base36_to_int(ts_b36)
    except ValueError:
      return False
    for secret in [self.secret, *self.secret_fallbacks]:
      if constant_time_compare(self._make_token_with_timestamp(user, ts, secret), token):
        break
    else:
      return False
    return (self._num_seconds(self._now()) - ts) <= self.timeout


class EmailVerificationTokenGenerator(TimeoutTokenGenerator):
  """Keyed off is_active instead of password so a token is invalidated once
  the account has been verified rather than once the password changes. 3-day
  lifetime: a sign-up verification email is routinely opened much later."""

  timeout = 60 * 60 * 24 * 3

  def _make_hash_value(self, user, timestamp):
    return f'{user.pk}{timestamp}{user.is_active}'


email_verification_token = EmailVerificationTokenGenerator()


class EmailChangeTokenGenerator(PasswordResetTokenGenerator):
  """Keyed off pending_email, so the link dies as soon as the request is
  cancelled, replaced by another address, or confirmed (pending cleared).
  Lifetime = settings.PASSWORD_RESET_TIMEOUT (1 hour)."""

  def _make_hash_value(self, user, timestamp):
    return f'{user.pk}{timestamp}{user.pending_email}'


email_change_token = EmailChangeTokenGenerator()
