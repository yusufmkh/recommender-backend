from django.contrib.auth.tokens import PasswordResetTokenGenerator


class EmailVerificationTokenGenerator(PasswordResetTokenGenerator):
  """Like the password reset generator, but keyed off is_active instead of
  password so a token is invalidated once the account has been verified
  rather than once the password changes."""

  def _make_hash_value(self, user, timestamp):
    return f'{user.pk}{timestamp}{user.is_active}'


email_verification_token = EmailVerificationTokenGenerator()
