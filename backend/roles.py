"""Role-separation contract (backend half).

A user's role is the `MyUser.role` column - 'candidate' or 'employer' - set at
sign-up (user_register vs employer_register) and never client-writable (it is
outside USER_SELF_FIELDS and read-only on MyUserSerializer). Employers
additionally own a Company row (their profile); candidates never do, and
roles are exclusive and fixed for the life of the account.

Enforcement layers:
- These permission classes are THE gate: every role-specific view declares one.
  They read the column, never the JWT claim - the DB is the truth, and the
  test suite's force_authenticate fixtures carry no token payload at all.
- The JWT carries a ROLE_CLAIM stamped at login and re-stamped from the DB on
  every refresh (token_views.py), so the claim's staleness is bounded by one
  access-token lifetime. The frontend middleware decodes it (unsigned) purely
  to route each role to its own tree - advisory, never authorisation.
- Views serving both roles stay requester/row-scoped (user_profile,
  conversations, application_detail); their per-row roles are derived from the
  row, not the token, because e.g. an employer can legitimately be the
  applicant side of a legacy application.
"""

import logging

from rest_framework.permissions import SAFE_METHODS, BasePermission

logger = logging.getLogger(__name__)

ROLE_CANDIDATE = 'candidate'
ROLE_EMPLOYER = 'employer'
ROLE_CHOICES = ((ROLE_CANDIDATE, 'Candidate'), (ROLE_EMPLOYER, 'Employer'))
# Claim name in the JWT payload; mirrored by the frontend
ROLE_CLAIM = 'role'


def is_employer(user):
  return user.role == ROLE_EMPLOYER


def user_role(user):
  return user.role


def company_for(user):
  # The employer's Company via the reverse one-to-one. Only valid behind
  # IsEmployer (or an is_employer check): a candidate raises
  # Company.DoesNotExist here, which used to surface as a 500 from the views
  # that inlined Company.objects.get(user=...).
  return user.company


def _log_denial(request, required):
  # The audit trail for cross-role attempts: an authenticated token refused
  # for being on the wrong side. Anonymous 401s are not logged here (DRF
  # handles those before permissions run).
  logger.warning(
    'role_denied user=%s role=%s required=%s method=%s path=%s',
    request.user.id, request.user.role, required, request.method, request.path,
  )


class IsCandidate(BasePermission):
  message = 'This action is only available to candidate accounts.'

  def has_permission(self, request, view):
    # is_authenticated first: DRF turns a credential-less request into a 401
    # before permissions run, and the short-circuit keeps AnonymousUser (which
    # has no .role) away from is_employer.
    if not (request.user and request.user.is_authenticated):
      return False
    if is_employer(request.user):
      _log_denial(request, ROLE_CANDIDATE)
      return False
    return True


class IsEmployer(BasePermission):
  message = 'This action is only available to employer accounts.'

  def has_permission(self, request, view):
    if not (request.user and request.user.is_authenticated):
      return False
    if not is_employer(request.user):
      _log_denial(request, ROLE_EMPLOYER)
      return False
    return True


class IsEmployerOrReadOnly(IsEmployer):
  """Reads for any authenticated user, writes for employers only. (Unlike
  DRF's IsAuthenticatedOrReadOnly, reads are NOT anonymous.) Fits the shared
  views whose write half is employer-owned - jobs, job_details, conversations -
  whose per-row ownership checks remain in the views themselves."""

  def has_permission(self, request, view):
    if request.method in SAFE_METHODS:
      return bool(request.user and request.user.is_authenticated)
    return super().has_permission(request, view)
