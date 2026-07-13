from django.conf import settings
from django.contrib.auth.tokens import default_token_generator
from django.core.mail import send_mail
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode

from .tokens import email_verification_token


def _uid(user):
  return urlsafe_base64_encode(force_bytes(user.pk))


def send_verification_email(user):
  uid = _uid(user)
  token = email_verification_token.make_token(user)
  link = f'{settings.FRONTEND_URL}/verify-email?uid={uid}&token={token}'

  send_mail(
    subject='Verify your Recommender App email address',
    message=(
      f'Hi {user.first_name},\n\n'
      f'Please confirm your email address by clicking the link below:\n\n'
      f'{link}\n\n'
      f"If you didn't create an Recommender App account, you can ignore this email."
    ),
    from_email=settings.DEFAULT_FROM_EMAIL,
    recipient_list=[user.email],
    fail_silently=False,
  )


def send_password_reset_email(user):
  uid = _uid(user)
  token = default_token_generator.make_token(user)
  link = f'{settings.FRONTEND_URL}/reset-password?uid={uid}&token={token}'

  send_mail(
    subject='Reset your Recommender App password',
    message=(
      f'Hi {user.first_name},\n\n'
      f'We received a request to reset your password. Click the link below to choose a new one:\n\n'
      f'{link}\n\n'
      f"If you didn't request this, you can safely ignore this email."
    ),
    from_email=settings.DEFAULT_FROM_EMAIL,
    recipient_list=[user.email],
    fail_silently=False,
  )
