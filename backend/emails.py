import logging
from urllib.parse import urlsplit

from django.conf import settings
from django.contrib.auth.tokens import default_token_generator
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode

from .tokens import email_verification_token

logger = logging.getLogger(__name__)


def _uid(user):
  return urlsafe_base64_encode(force_bytes(user.pk))


def _send(*, subject, to, text, html_context):
  # Every email is multipart: the plain-text body is the source of truth (and
  # what tests assert on); the HTML alternative renders the same content in the
  # shared templates/emails/base.html layout. Raises on failure - callers that
  # must not fail the request wrap this themselves.
  html = render_to_string('emails/base.html', {
    'subject': subject,
    'website_name': settings.WEBSITE_NAME,
    'frontend_url': settings.FRONTEND_URL,
    'frontend_host': urlsplit(settings.FRONTEND_URL).netloc or settings.FRONTEND_URL,
    **html_context,
  })
  email = EmailMultiAlternatives(subject=subject, body=text, from_email=settings.DEFAULT_FROM_EMAIL, to=[to])
  email.attach_alternative(html, 'text/html')
  email.send(fail_silently=False)


def send_verification_email(user):
  uid = _uid(user)
  token = email_verification_token.make_token(user)
  link = f'{settings.FRONTEND_URL}/verify-email?uid={uid}&token={token}'

  _send(
    subject=f'Verify your {settings.WEBSITE_NAME} email address',
    to=user.email,
    text=(
      f'Hi {user.first_name},\n\n'
      f'Please confirm your email address by clicking the link below:\n\n'
      f'{link}\n\n'
      f"If you didn't create a {settings.WEBSITE_NAME} account, you can ignore this email."
    ),
    html_context={
      'preheader': 'One click to confirm your email address.',
      'greeting': f'Hi {user.first_name},',
      'intro': ['Thanks for signing up. Please confirm your email address to activate your account.'],
      'cta': {'label': 'Verify email address', 'url': link},
      'outro': [],
      'footer_note': f"You're receiving this because a {settings.WEBSITE_NAME} account was created with this address. If that wasn't you, you can ignore this email.",
    },
  )


def send_password_reset_email(user):
  uid = _uid(user)
  token = default_token_generator.make_token(user)
  link = f'{settings.FRONTEND_URL}/reset-password?uid={uid}&token={token}'

  _send(
    subject=f'Reset your {settings.WEBSITE_NAME} password',
    to=user.email,
    text=(
      f'Hi {user.first_name},\n\n'
      f'We received a request to reset your password. Click the link below to choose a new one:\n\n'
      f'{link}\n\n'
      f"If you didn't request this, you can safely ignore this email."
    ),
    html_context={
      'preheader': f'Choose a new password for your {settings.WEBSITE_NAME} account.',
      'greeting': f'Hi {user.first_name},',
      'intro': ['We received a request to reset your password. Use the button below to choose a new one.'],
      'cta': {'label': 'Reset password', 'url': link},
      'outro': [],
      'footer_note': "If you didn't request a password reset, you can safely ignore this email - your password won't change.",
    },
  )


def send_new_message_email(candidate, sender_name, job_title, conversation_id, body, sender_photo=''):
  # Mirrors every employer-authored in-app message (manual, invite, status
  # change) to the candidate's inbox, with a deep link into the thread.
  # `sender_name`/`sender_photo` are the job's branch when it has one, else
  # the company (see views._job_display_identity). Best-effort by design: a mail-provider
  # outage must never turn a message send into a 500 or roll the row back, so
  # failures are logged and swallowed - unlike the verification/reset emails,
  # the in-app thread is the source of truth and the badge still lights up.
  link = f'{settings.FRONTEND_URL}/candidate/messages/{conversation_id}'
  try:
    _send(
      subject=f'New message from {sender_name} about {job_title}',
      to=candidate.email,
      text=(
        f'Hi {candidate.first_name},\n\n'
        f'{sender_name} sent you a message about {job_title}:\n\n'
        f'{body}\n\n'
        f'Reply here: {link}\n'
      ),
      html_context={
        'preheader': body[:120],
        'greeting': f'Hi {candidate.first_name},',
        'intro': [f'{sender_name} sent you a message about {job_title}:'],
        # The message box is headed by the sender's identity - branch/company
        # photo (absolute S3 url, or an initial when there is none) + name.
        'quote': {
          'label': sender_name,
          'photo': sender_photo or '',
          'initial': (sender_name[:1] or '?').upper(),
          'body': body,
          'meta': f'Re: {job_title}',
        },
        'cta': {'label': f'Reply on {settings.WEBSITE_NAME}', 'url': link},
        'outro': [],
        'footer_note': f"You're receiving this because an employer messaged you on {settings.WEBSITE_NAME}. Replies to this email aren't monitored - use the button above to respond.",
      },
    )
  except Exception:
    logger.exception('Failed to email candidate %s about conversation %s', candidate.pk, conversation_id)
