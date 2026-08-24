from django.conf import settings
from django.db import IntegrityError, transaction
from django.db.models import Count, F, Max, Q
from django.contrib.auth.tokens import default_token_generator
from django.utils import timezone
from django.utils.encoding import force_str
from django.utils.http import urlsafe_base64_decode

from rest_framework.decorators import api_view, permission_classes, throttle_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework import status

from .models import MyUser, Company, CompanyBranch, Job, WorkExperience, Skill, Preference, SavedJob, SavedCandidate, Match, Application, ApplicationQuestion, ApplicationAnswer, AttachmentRequirement, AttachmentAnswer, Conversation, Message

from .serializers import MyUserSerializer, CompanySerializer, CompanyBranchSerializer, JobSerializer, WorkExperienceSerializer, SkillSerializer, PreferenceSerializer, SavedJobSerializer, SavedCandidateSerializer, SavedMetaSerializer, MatchSerializer, CompanyCandidateSerializer, ApplicationSerializer, ApplicationQuestionSerializer, ApplicationAnswerSerializer, AttachmentRequirementSerializer, AttachmentAnswerSerializer, MessageSerializer

from .s3_utils import generate_presigned_post, delete_object
from .tokens import email_verification_token
from .emails import send_verification_email, send_password_reset_email

# The only user fields registration accepts from a client. create_user passes
# **kwargs straight onto the model, so an unfiltered body could set is_staff /
# is_superuser (privilege escalation) or is_active (skipping email verification),
# and any unknown key would be a TypeError -> 500.
USER_SELF_FIELDS = {
  'first_name', 'last_name', 'email', 'user_name', 'password', 'photo',
  'phone_number', 'dob', 'address', 'postcode', 'city', 'state', 'country',
}

def _delete_old_photo_if_replaced(old_photo, new_photo):
  if old_photo and old_photo != new_photo:
    try:
      delete_object(old_photo)
    except Exception:
      pass

def _user_from_uid(uid):
  try:
    return MyUser.objects.get(pk=force_str(urlsafe_base64_decode(uid)))
  except (MyUser.DoesNotExist, ValueError, TypeError, OverflowError):
    return None

def _company_candidates(company):
  # Every candidate this company can see, one row each: their matches on the
  # company's jobs plus shortlist metadata. Four queries - matches, saved, users,
  # work experiences - flat regardless of how many candidates there are.
  company_jobs = Job.objects.filter(company=company)
  matches = Match.objects.filter(job__in=company_jobs)
  saved = SavedCandidate.objects.filter(company=company)

  # Union the ids first so an overlapping candidate is fetched once, and their
  # work experiences prefetched once, rather than once per queryset. Neither
  # queryset needs select_related('user') as a result.
  user_ids = {m.user_id for m in matches} | {s.user_id for s in saved}
  users_by_id = {u.id: u for u in MyUser.objects.filter(pk__in=user_ids).prefetch_related('work_experiences')}

  rows = {uid: {'user': users_by_id[uid], 'matches': [], 'saved': None} for uid in user_ids}
  for match in matches:
    rows[match.user_id]['matches'].append(match)
  for saved_candidate in saved:
    # A shortlisted candidate stays listed even once their matches are gone.
    rows[saved_candidate.user_id]['saved'] = saved_candidate

  return company_jobs, matches, rows

def _company_can_view_candidate(employer, candidate_id):
  # An employer may see a candidate matched to, applied to, or shortlisted by
  # their company - and nobody else. Without this, saving would be an oracle for
  # enumerating user ids.
  return (
    Match.objects.filter(user_id=candidate_id, job__company__user=employer).exists()
    or Application.objects.filter(user_id=candidate_id, job__company__user=employer).exists()
    or SavedCandidate.objects.filter(user_id=candidate_id, company__user=employer).exists()
  )

def _get_or_create_skills(skill_names):
  # Skills are sent as a list of names; names are normalized (trimmed and
  # matched case-insensitively) so "Python", "python" and " python " all
  # resolve to a single Skill row, and the rest are created. Duplicates
  # within one request are collapsed. New skills are stored in sentence case:
  # first letter uppercase, the rest lowercased ("SQL" -> "Sql").
  skills = []
  seen = set()
  for raw in skill_names:
    name = (raw or '').strip()
    if not name:
      continue
    key = name.casefold()
    if key in seen:
      continue
    seen.add(key)
    name = name[:1].upper() + name[1:].lower()
    skill, _ = Skill.objects.get_or_create(name__iexact=name, defaults={'name': name})
    skills.append(skill)
  return skills

@api_view(['POST'])
def user_register(request):
  # Whitelist, don't blacklist: privilege flags are never trusted from the
  # client, and every new account starts inactive until the verification link
  # is used, regardless of what the request body contains.
  user_fields = {k: v for k, v in request.data.items() if k in USER_SELF_FIELDS}

  try:
    user = MyUser.objects.create_user(**user_fields)
  except IntegrityError:
    return Response({'error': 'An account with this email or username already exists.'}, status=status.HTTP_400_BAD_REQUEST)

  send_verification_email(user)

  user_data_serializer = MyUserSerializer(user)
  return Response(user_data_serializer.data, status=status.HTTP_201_CREATED)

@api_view(['POST'])
@transaction.atomic
def employer_register(request):
  # Creates the user and their company together, atomically, without
  # requiring the caller to already be authenticated - the account is
  # inactive until email verification, so no JWT can be issued yet.
  company_fields = ('company_name', 'legal_name', 'company_email', 'company_size', 'phone_number', 'website', 'address', 'postcode', 'city', 'state', 'country')
  user_fields = {k: v for k, v in request.data.items() if k in USER_SELF_FIELDS and k not in company_fields}

  try:
    user = MyUser.objects.create_user(**user_fields)
  except IntegrityError:
    return Response({'error': 'An account with this email or username already exists.'}, status=status.HTTP_400_BAD_REQUEST)

  company_data_serializer = CompanySerializer(data={
    'user': user.id,
    'name': request.data.get('company_name'),
    'legal_name': request.data.get('legal_name') or '',
    'email': request.data.get('company_email'),
    'company_size': request.data.get('company_size'),
    'phone_number': request.data.get('phone_number'),
    'website': request.data.get('website') or '',
    'address': request.data.get('address'),
    'postcode': request.data.get('postcode'),
    'city': request.data.get('city'),
    'state': request.data.get('state'),
    'country': request.data.get('country'),
  })

  if not company_data_serializer.is_valid():
    transaction.set_rollback(True)
    return Response(company_data_serializer.errors, status=status.HTTP_400_BAD_REQUEST)

  company_data_serializer.save()
  send_verification_email(user)

  return Response(MyUserSerializer(user).data, status=status.HTTP_201_CREATED)

@api_view(['POST'])
@throttle_classes([ScopedRateThrottle])
def password_reset_request(request):
  email = (request.data.get('email') or '').strip()

  user = MyUser.objects.filter(email__iexact=email).first()
  if user:
    send_password_reset_email(user)

  # Always return the same response, whether or not the email exists,
  # so this endpoint can't be used to enumerate registered accounts.
  return Response({'ok': True})

password_reset_request.cls.throttle_scope = 'password_reset'

@api_view(['POST'])
def password_reset_confirm(request):
  user = _user_from_uid(request.data.get('uid'))
  token = request.data.get('token')
  new_password = request.data.get('password')

  if not user or not token or not default_token_generator.check_token(user, token):
    return Response({'error': 'This reset link is invalid or has expired.'}, status=status.HTTP_400_BAD_REQUEST)

  if not new_password or len(new_password) < 8:
    return Response({'error': 'Password must be at least 8 characters.'}, status=status.HTTP_400_BAD_REQUEST)

  user.set_password(new_password)
  user.save()

  return Response({'ok': True})

@api_view(['POST'])
def email_verify_confirm(request):
  user = _user_from_uid(request.data.get('uid'))
  token = request.data.get('token')

  if not user or not token or not email_verification_token.check_token(user, token):
    return Response({'error': 'This verification link is invalid or has expired.'}, status=status.HTTP_400_BAD_REQUEST)

  if not user.is_active:
    user.is_active = True
    user.save()

  return Response({'ok': True})

@api_view(['POST'])
@throttle_classes([ScopedRateThrottle])
def email_verify_resend(request):
  email = (request.data.get('email') or '').strip()

  user = MyUser.objects.filter(email__iexact=email, is_active=False).first()
  if user:
    send_verification_email(user)

  return Response({'ok': True})

email_verify_resend.cls.throttle_scope = 'email_verify'

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def user_dashboard(request, format=None):
  user_info = MyUser.objects.filter(pk=request.user.id)
  job_matches = Match.objects.filter(user=request.user)
  invited_jobs = Match.objects.filter(user=request.user, is_invited__exact=True)
  all_jobs = Job.objects.all()
  applied_jobs = Application.objects.filter(user=request.user)
  saved_jobs = SavedJob.objects.filter(user=request.user)

  user_data_serializer = MyUserSerializer(user_info[0])
  job_matches_serializer = MatchSerializer(job_matches, many=True)
  invited_jobs_serializer = MatchSerializer(invited_jobs, many=True)
  all_jobs_serializer = JobSerializer(all_jobs, many=True)
  applied_jobs_serializer = ApplicationSerializer(applied_jobs, many=True)
  saved_jobs_serializer = SavedJobSerializer(saved_jobs, many=True)
  
  return Response(
    {
      'user_data': user_data_serializer.data,
      'job_matches': job_matches_serializer.data,
      'invited_jobs': invited_jobs_serializer.data,
      'all_jobs': all_jobs_serializer.data,
      'applied_jobs': applied_jobs_serializer.data,
      'saved_jobs': saved_jobs_serializer.data
    }
  )

@api_view(['GET', 'PATCH'])
@permission_classes([IsAuthenticated])
def user_profile(request, format=None):
  user = MyUser.objects.get(pk=request.user.id)

  if request.method == 'GET':
    serializer = MyUserSerializer(user)
    return Response(serializer.data)

  elif request.method == 'PATCH':
    old_photo = user.photo
    serializer = MyUserSerializer(user, data=request.data, partial=True)
    if serializer.is_valid():
      serializer.save()
      _delete_old_photo_if_replaced(old_photo, serializer.data.get('photo'))
      return Response(serializer.data)
    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

@api_view(['GET', 'POST'])
@permission_classes([IsAuthenticated])
def user_work_experiences(request):
  if request.method == 'GET':
    work_experiences = WorkExperience.objects.filter(user=request.user)

    work_experiences_serializer = WorkExperienceSerializer(work_experiences, many=True)

    return Response(work_experiences_serializer.data)
  
  elif request.method == 'POST':
      we_data = request.data.dict() if hasattr(request.data, 'dict') else dict(request.data)
      we_skills = we_data.pop('skills', [])

      work_experience = WorkExperience.objects.create(user=request.user, **we_data)
      work_experience.skills.set(_get_or_create_skills(we_skills))

      work_experience_serializer = WorkExperienceSerializer(work_experience)

      return Response(work_experience_serializer.data, status=status.HTTP_201_CREATED)

@api_view(['GET', 'PATCH', 'DELETE'])
@permission_classes([IsAuthenticated])
def user_work_experience_details(request, id, format=None):
  # Scoped to the requesting user so a candidate can only read or edit
  # their own work experience, mirroring how job_details scopes to owner.
  try:
    work_experience = WorkExperience.objects.get(pk=id, user=request.user)
  except WorkExperience.DoesNotExist:
    return Response(status=status.HTTP_404_NOT_FOUND)

  if request.method == 'GET':
    return Response(WorkExperienceSerializer(work_experience).data)

  if request.method == 'PATCH':
    we_data = request.data.dict() if hasattr(request.data, 'dict') else dict(request.data)
    we_skills = we_data.pop('skills', None)

    editable_fields = ('job_title', 'description', 'company_name', 'company_address', 'company_website', 'start_date', 'end_date')
    for field in editable_fields:
      if field in we_data:
        setattr(work_experience, field, we_data[field])
    work_experience.save()

    # None means "skills not supplied, leave them"; a list (even []) replaces the set.
    if we_skills is not None:
      work_experience.skills.set(_get_or_create_skills(we_skills))

    return Response(WorkExperienceSerializer(work_experience).data)

  elif request.method == 'DELETE':
    work_experience.delete()
    return Response(status=status.HTTP_204_NO_CONTENT)

@api_view(['GET', 'POST'])
@permission_classes([IsAuthenticated])
def skills(request):
  if request.method == 'GET':
    skills = Skill.objects.all()
    skills_serializer = SkillSerializer(skills, many=True)

    return Response({ 'skills': skills_serializer.data })
  
  elif request.method == 'POST':
    skill_serializer = SkillSerializer(data=request.data)

    if skill_serializer.is_valid():
      skill_serializer.save()

      return Response(skill_serializer.data, status=status.HTTP_201_CREATED)

@api_view(['GET', 'POST'])
@permission_classes([IsAuthenticated])
def user_preferences(request):
  if request.method == 'GET':
    preference = Preference.objects.filter(user=request.user).first()

    if not preference:
      return Response(None)

    return Response(PreferenceSerializer(preference).data)
  
  elif request.method == 'POST':
    existing = Preference.objects.filter(user=request.user).first()

    user_preferences_serializer = PreferenceSerializer(
      existing,
      data={'user': request.user.id, **request.data},
      partial=bool(existing)
    )

    if user_preferences_serializer.is_valid():
      user_preferences_serializer.save()

      status_code = status.HTTP_200_OK if existing else status.HTTP_201_CREATED
      return Response(user_preferences_serializer.data, status=status_code)
    else:
      return Response(user_preferences_serializer.errors, status=status.HTTP_400_BAD_REQUEST)

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def company_register(request):
  company_data_serializer = CompanySerializer(data={'user': request.user.id, **request.data})

  if company_data_serializer.is_valid():
    company_data_serializer.save()

    return Response(company_data_serializer.data, status=status.HTTP_201_CREATED)
  else:
    return Response(company_data_serializer.errors, status=status.HTTP_400_BAD_REQUEST)

@api_view(['GET', 'PATCH'])
@permission_classes([IsAuthenticated])
def company_profile(request, format=None):
  try:
    company = Company.objects.get(user=request.user)
  except Company.DoesNotExist:
    return Response(status=status.HTTP_404_NOT_FOUND)

  if request.method == 'GET':
    serializer = CompanySerializer(company)
    return Response(serializer.data)

  elif request.method == 'PATCH':
    old_photo = company.photo
    serializer = CompanySerializer(company, data=request.data, partial=True)
    if serializer.is_valid():
      serializer.save()
      _delete_old_photo_if_replaced(old_photo, serializer.data.get('photo'))
      return Response(serializer.data)
    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

@api_view(['GET', 'POST'])
@permission_classes([IsAuthenticated])
def company_branches(request, format=None):
  company = Company.objects.get(user=request.user)

  if request.method == 'GET':
    branches = CompanyBranch.objects.filter(company=company)
    serializer = CompanyBranchSerializer(branches, many=True)
    return Response(serializer.data)

  elif request.method == 'POST':
    branch_data = request.data.dict() if hasattr(request.data, 'dict') else request.data
    serializer = CompanyBranchSerializer(data={'company': company.id, **branch_data})
    if serializer.is_valid():
      serializer.save()
      return Response(serializer.data, status=status.HTTP_201_CREATED)
    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

@api_view(['GET', 'PATCH', 'DELETE'])
@permission_classes([IsAuthenticated])
def company_branch_details(request, id, format=None):
  try:
    branch = CompanyBranch.objects.get(pk=id, company__user=request.user)
  except CompanyBranch.DoesNotExist:
    return Response(status=status.HTTP_404_NOT_FOUND)

  if request.method == 'GET':
    serializer = CompanyBranchSerializer(branch)
    return Response(serializer.data)

  elif request.method == 'PATCH':
    old_photo = branch.photo
    serializer = CompanyBranchSerializer(branch, data=request.data, partial=True)
    if serializer.is_valid():
      serializer.save()
      _delete_old_photo_if_replaced(old_photo, serializer.data.get('photo'))
      return Response(serializer.data)
    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

  elif request.method == 'DELETE':
    if branch.photo:
      try:
        delete_object(branch.photo)
      except Exception:
        pass
    branch.delete()
    return Response(status=status.HTTP_204_NO_CONTENT)

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def photo_presign(request, format=None):
  filename = request.data.get('filename')
  content_type = request.data.get('content_type')

  if not filename or not content_type:
    return Response(
      {'error': 'filename and content_type are required.'},
      status=status.HTTP_400_BAD_REQUEST,
    )

  if content_type not in settings.AWS_S3_ALLOWED_CONTENT_TYPES:
    return Response({'error': 'Unsupported file type.'}, status=status.HTTP_400_BAD_REQUEST)

  try:
    presign_data = generate_presigned_post(
      user_id=request.user.id, filename=filename, content_type=content_type,
    )
  except Exception:
    return Response({'error': 'Could not generate upload URL.'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

  return Response(presign_data, status=status.HTTP_200_OK)

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def company_dashboard(request, format=None):
  company_info = Company.objects.get(user=request.user)
  company_jobs, all_matches, rows = _company_candidates(company_info)
  job_applicants = Application.objects.filter(job__in=company_jobs)

  # Saving a candidate moves them off the matched list and onto the shortlist.
  # Both keys carry the same shape, so the two pages share one serializer.
  unsaved = [row for row in rows.values() if row['saved'] is None]
  shortlisted = [row for row in rows.values() if row['saved'] is not None]

  # Explicit ordering: dict insertion order follows the database's, which is
  # arbitrary. Best match first for triage, most recently saved first for the
  # shortlist.
  unsaved.sort(key=lambda row: max((m.score or 0) for m in row['matches']) if row['matches'] else -1, reverse=True)
  shortlisted.sort(key=lambda row: row['saved'].created_at, reverse=True)

  company_info_serializer = CompanySerializer(company_info)
  company_jobs_serializer = JobSerializer(company_jobs.select_related('branch', 'company').prefetch_related('skills'), many=True)
  job_applicants_serializer = ApplicationSerializer(job_applicants, many=True)

  return Response(
    {
      'company_info': company_info_serializer.data,
      'company_jobs': company_jobs_serializer.data,
      'job_applicants': job_applicants_serializer.data,
      'candidate_matches': CompanyCandidateSerializer(unsaved, many=True).data,
      'saved_candidates': CompanyCandidateSerializer(shortlisted, many=True).data,
      # Filtered from the rows already in memory - no second query, and always
      # consistent with candidate_matches. Invites are deliberately NOT filtered
      # by shortlist status: the two axes are independent.
      'candidate_invites': MatchSerializer([m for m in all_matches if m.is_invited], many=True).data,
    }
  )

@api_view(['PATCH'])
@permission_classes([IsAuthenticated])
def match_invite(request, id, format=None):
  try:
    match = Match.objects.get(pk=id)
  except Match.DoesNotExist:
    return Response(status=status.HTTP_404_NOT_FOUND)

  # Only the company that owns the matched job may invite the candidate.
  if match.job.company is None or match.job.company.user_id != request.user.id:
    return Response(status=status.HTTP_403_FORBIDDEN)

  match.is_invited = True
  match.save()

  return Response(MatchSerializer(match).data)

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def candidate_profile(request, user_id, format=None):
  if not _company_can_view_candidate(request.user, user_id):
    return Response(status=status.HTTP_403_FORBIDDEN)

  try:
    candidate = MyUser.objects.get(pk=user_id)
  except MyUser.DoesNotExist:
    return Response(status=status.HTTP_404_NOT_FOUND)

  work_experiences = WorkExperience.objects.filter(user=candidate).order_by('-start_date')
  preference = Preference.objects.filter(user=candidate).first()

  return Response({
    'work_experiences': WorkExperienceSerializer(work_experiences, many=True).data,
    'preferences': PreferenceSerializer(preference).data if preference else None,
    'contact': {'email': candidate.email, 'phone_number': candidate.phone_number},
  })

@api_view(['GET', 'POST'])
@permission_classes([IsAuthenticated])
def jobs(request, format=None):
  if request.method == 'GET':
    jobs = Job.objects.all()
    jobs_serializer = JobSerializer(jobs, many=True)
    return Response(jobs_serializer.data)

  if request.method == 'POST':
    company = Company.objects.get(user=request.user)

    job_data = request.data.dict() if hasattr(request.data, 'dict') else dict(request.data)
    job_skills = job_data.pop('skills', [])

    branch_id = job_data.pop('branch', None) or None
    if branch_id is not None and not CompanyBranch.objects.filter(pk=branch_id, company=company).exists():
      return Response({'error': 'Branch does not belong to your company.'}, status=status.HTTP_400_BAD_REQUEST)

    job = Job.objects.create(company=company, branch_id=branch_id, **job_data)
    job.skills.set(_get_or_create_skills(job_skills))

    job_serializer = JobSerializer(job)

    return Response({
      "job": job_serializer.data,
      "candidate_predictions": 'Candidate predictions here',
      }, status=status.HTTP_201_CREATED)

@api_view(['GET', 'PATCH', 'DELETE'])
@permission_classes([IsAuthenticated])
def job_details(request, id, format=None):
  try:
    job = Job.objects.get(pk=id)
  except Job.DoesNotExist:
    return Response(status=status.HTTP_404_NOT_FOUND)

  if request.method == 'GET':
    job_serializer = JobSerializer(job)
    return Response(job_serializer.data)

  # Editing or deleting a job is only allowed for the company that owns it.
  if job.company is None or job.company.user_id != request.user.id:
    return Response(status=status.HTTP_403_FORBIDDEN)

  if request.method == 'PATCH':
    job_data = request.data.dict() if hasattr(request.data, 'dict') else dict(request.data)
    job_skills = job_data.pop('skills', None)

    if 'branch' in job_data:
      branch_id = job_data.pop('branch') or None
      if branch_id is not None and not CompanyBranch.objects.filter(pk=branch_id, company=job.company).exists():
        return Response({'error': 'Branch does not belong to your company.'}, status=status.HTTP_400_BAD_REQUEST)
      job.branch_id = branch_id

    editable_fields = ('title', 'description', 'job_type', 'pay', 'pay_range', 'status', 'contact')
    for field in editable_fields:
      if field in job_data:
        setattr(job, field, job_data[field])
    job.save()

    if job_skills is not None:
      job.skills.set(_get_or_create_skills(job_skills))

    job_serializer = JobSerializer(job)
    return Response(job_serializer.data)

  elif request.method == 'DELETE':
    job.delete()
    return Response(status=status.HTTP_204_NO_CONTENT)

@api_view(['GET', 'POST'])
@permission_classes([IsAuthenticated])
def saved_jobs(request):
  if request.method == 'GET':
    saved_jobs = SavedJob.objects.filter(user=request.user)
    saved_jobs_serializer = SavedJobSerializer(saved_jobs, many=True)

    return Response(saved_jobs_serializer.data)
  
  elif request.method == 'POST':
    saved_job_serializer = SavedJobSerializer(data={'user': request.user.id, **request.data})
    if saved_job_serializer.is_valid():
      saved_job_serializer.save()

      return Response(saved_job_serializer.data, status=status.HTTP_201_CREATED)
    else:
      return Response(saved_job_serializer.errors, status=status.HTTP_400_BAD_REQUEST)

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def company_saved_candidates(request):
  # The company is always derived from the token - never taken from the client -
  # so one employer can't read or write another's shortlist.
  try:
    company = Company.objects.get(user=request.user)
  except Company.DoesNotExist:
    return Response(status=status.HTTP_404_NOT_FOUND)

  candidate_id = request.data.get('user')
  if not candidate_id:
    return Response({'error': 'user is required.'}, status=status.HTTP_400_BAD_REQUEST)

  if not _company_can_view_candidate(request.user, candidate_id):
    return Response(status=status.HTTP_403_FORBIDDEN)

  note = request.data.get('note') or ''
  if len(note) > 2000:
    return Response({'error': 'Note is too long.'}, status=status.HTTP_400_BAD_REQUEST)

  # Idempotent: saving twice returns the existing row rather than erroring, and the
  # unique constraint makes the race safe.
  saved_candidate, created = SavedCandidate.objects.get_or_create(
    company=company, user_id=candidate_id, defaults={'note': note},
  )

  serializer = SavedMetaSerializer(saved_candidate)
  return Response(serializer.data, status=status.HTTP_201_CREATED if created else status.HTTP_200_OK)

@api_view(['PATCH', 'DELETE'])
@permission_classes([IsAuthenticated])
def company_saved_candidate_details(request, id, format=None):
  # Scoped to the requesting employer's own company, so another company's row is
  # indistinguishable from one that doesn't exist.
  try:
    saved_candidate = SavedCandidate.objects.get(pk=id, company__user=request.user)
  except SavedCandidate.DoesNotExist:
    return Response(status=status.HTTP_404_NOT_FOUND)

  if request.method == 'PATCH':
    if 'note' in request.data:
      note = request.data.get('note') or ''
      if len(note) > 2000:
        return Response({'error': 'Note is too long.'}, status=status.HTTP_400_BAD_REQUEST)
      saved_candidate.note = note
      saved_candidate.save(update_fields=['note', 'updated_at'])

    return Response(SavedMetaSerializer(saved_candidate).data)

  elif request.method == 'DELETE':
    saved_candidate.delete()
    return Response(status=status.HTTP_204_NO_CONTENT)

@api_view(['GET', 'POST'])
@permission_classes([IsAuthenticated])
def job_applications(request):
  if request.method == 'GET':
    user_applications = Application.objects.filter(user=request.user)
    user_application_questions = ApplicationQuestion.objects.filter(application__in=user_applications)
    user_application_answers = ApplicationAnswer.objects.filter(application_question__in=user_application_questions)
    attachment_requirements = AttachmentRequirement.objects.filter(application__in=user_applications)
    attachment_answers = AttachmentAnswer.objects.filter(attachment_requirement__in=attachment_requirements)

    user_applications_serializer = ApplicationSerializer(user_applications, many=True)
    user_application_questions_serializer = ApplicationQuestionSerializer(user_application_questions, many=True)
    user_application_answers_serializer = ApplicationAnswerSerializer(user_application_answers, many=True)
    attachment_requirements_serializer = AttachmentRequirementSerializer(attachment_requirements, many=True)
    attachment_answers_serializer = AttachmentAnswerSerializer(attachment_answers, many=True)

    return Response({
      "user_applications": user_applications_serializer.data,
      "user_application_questions": user_application_questions_serializer.data,
      "user_application_answers": user_application_answers_serializer.data,
      "attachment_requirements": attachment_requirements_serializer.data,
      "attachment_answers": attachment_answers_serializer.data,
    })
  
  elif request.method == 'POST':
    application = request.data
    # .get, not ['...']: the old unconditional reads ran AFTER the Application
    # row was saved, so a body missing 'questions'/'attachment_requirements'
    # 500ed while still creating an orphaned application.
    application_job = application.get('job')
    if application_job is None:
      return Response({'error': 'job is required.'}, status=status.HTTP_400_BAD_REQUEST)
    application_questions = application.get('questions') or []
    attachment_requirements = application.get('attachment_requirements') or []
    application_serializer = ApplicationSerializer(data={'user': request.user.id, 'job': application_job})

    if application_serializer.is_valid(raise_exception=True):
      application_serializer.save()

      if len(application_questions) > 0:
        for application_question in application_questions:
          application_question_serializer = ApplicationQuestionSerializer(data={'application': application_serializer, 'question': application_question['question']})

          if application_question_serializer.is_valid():
            application_question_serializer.save()

            application_answer_serializer = ApplicationAnswerSerializer(data={'application_question': application_question_serializer, 'answer': application_question['answer']})

            if application_answer_serializer.is_valid():
              application_answer_serializer.save()

      if len(attachment_requirements) > 0:
        for attachment_requirement in attachment_requirements:
          attachment_requirement_serializer = AttachmentRequirementSerializer(data={'application': application_serializer, 'attachment_requirement': attachment_requirement['requirement'], 'attachment_type': attachment_requirement['type']})

          if attachment_requirement_serializer.is_valid():
            attachment_requirement_serializer.save()

            attachment_answer_serializer = AttachmentAnswerSerializer(data={'attachment_requirement': attachment_requirement_serializer, 'attachment': attachment_requirement['attachment']})

            if attachment_answer_serializer.is_valid():
              attachment_answer_serializer.save()
    
      return Response(application_serializer.data, status=status.HTTP_201_CREATED)

    else:
      return Response(application_serializer.errors, status=status.HTTP_400_BAD_REQUEST)

# --- Messaging -------------------------------------------------------------
#
# Threads are anchored on (job, candidate). Only the employer that owns the job
# may open one - and only with a candidate they invited to that job or who
# applied to it - and it is always created together with its first message, so
# a candidate having a conversation at all means an employer messaged them
# first, which is exactly the condition for them being allowed to reply.

MESSAGE_MAX_LENGTH = 4000

class PostScopedRateThrottle(ScopedRateThrottle):
  # Rate-limits writes only, so the GET half of a shared view (the inbox) and
  # the thread view's polling are never throttled alongside sends.
  def allow_request(self, request, view):
    if request.method in ('GET', 'HEAD', 'OPTIONS'):
      return True
    return super().allow_request(request, view)

def _employer_can_message(employer_user, candidate_id, job):
  # Stricter than _company_can_view_candidate, and deliberately per-job:
  # shortlisting is not enough, and an application to one job doesn't open
  # messaging about another (inviting the candidate there does).
  if job.company is None or job.company.user_id != employer_user.id:
    return False
  return (
    Match.objects.filter(user_id=candidate_id, job=job, is_invited=True).exists()
    or Application.objects.filter(user_id=candidate_id, job=job).exists()
  )

def _member_conversations(user):
  # Every thread the requester belongs to, on whichever side. All reads and
  # writes below go through this scope, so someone else's conversation is
  # indistinguishable from one that doesn't exist.
  return Conversation.objects.filter(Q(candidate=user) | Q(job__company__user=user))

def _conversation_role(conversation, user):
  # Callers only pass members (see _member_conversations), so not-the-candidate
  # means the requester owns the job's company.
  return 'candidate' if conversation.candidate_id == user.id else 'employer'

def _mark_read(conversation, role):
  field = 'candidate_last_read_at' if role == 'candidate' else 'employer_last_read_at'
  setattr(conversation, field, timezone.now())
  conversation.save(update_fields=[field, 'updated_at'])

def _clean_message_body(raw):
  body = raw.strip() if isinstance(raw, str) else ''
  if not body:
    return None, 'Message cannot be empty.'
  if len(body) > MESSAGE_MAX_LENGTH:
    return None, f'Message is too long (max {MESSAGE_MAX_LENGTH} characters).'
  return body, None

def _job_summary(job):
  return {'id': job.id, 'title': job.title, 'status': job.status}

def _conversation_counterpart(conversation, role):
  # The other side of the thread, shaped identically for both roles so the
  # frontend renders either with one component. Candidates see the company,
  # never the employer user's personal identity; employers see the same lean
  # candidate subset as CandidateBriefSerializer (no email, no DOB).
  if role == 'candidate':
    company = conversation.job.company
    if company is None:
      return {'id': None, 'name': 'Company', 'photo': None, 'subtitle': None}
    return {'id': company.id, 'name': company.name, 'photo': company.photo, 'subtitle': company.city}
  candidate = conversation.candidate
  return {
    'id': candidate.id,
    'name': f'{candidate.first_name} {candidate.last_name}'.strip(),
    'photo': candidate.photo,
    'subtitle': candidate.city,
  }

def _thread_payload(conversation, user, role, after_id=None):
  messages = conversation.messages.all()
  if after_id is not None:
    # Ids are monotonic and messages append-only, so id-gt matches the
    # created_at ordering and gives the poller a cheap incremental cursor.
    messages = messages.filter(pk__gt=after_id)
  return {
    'me': user.id,
    'conversation': {
      'id': conversation.id,
      'job': _job_summary(conversation.job),
      'counterpart': _conversation_counterpart(conversation, role),
    },
    'messages': MessageSerializer(messages, many=True).data,
  }

def _unread_counts(user, conv_ids, read_field):
  # One query per side: counterpart-sent messages newer than the requester's
  # read cursor (or all of them where the side has never opened the thread).
  if not conv_ids:
    return {}
  rows = (
    Message.objects
    .filter(conversation_id__in=conv_ids)
    .exclude(sender=user)
    .filter(
      Q(created_at__gt=F(f'conversation__{read_field}'))
      | Q(**{f'conversation__{read_field}__isnull': True})
    )
    .values('conversation_id')
    .annotate(n=Count('id'))
  )
  return {row['conversation_id']: row['n'] for row in rows}

def _unread_by_conversation(user, conversations):
  as_candidate = [c.id for c in conversations if c.candidate_id == user.id]
  as_employer = [c.id for c in conversations if c.candidate_id != user.id]
  unread = _unread_counts(user, as_candidate, 'candidate_last_read_at')
  unread.update(_unread_counts(user, as_employer, 'employer_last_read_at'))
  return unread

@api_view(['GET', 'POST'])
@permission_classes([IsAuthenticated])
@throttle_classes([PostScopedRateThrottle])
def conversations(request, format=None):
  if request.method == 'GET':
    convs = list(_member_conversations(request.user).select_related('job__company', 'candidate'))
    conv_ids = [c.id for c in convs]

    # Latest message per thread in two flat queries (ids, then rows), plus two
    # for unread counts - the inbox stays at five queries however long it gets.
    last_ids = (
      Message.objects.filter(conversation_id__in=conv_ids)
      .values('conversation_id').annotate(last_id=Max('id'))
    ) if conv_ids else []
    last_by_conv = {
      m.conversation_id: m
      for m in Message.objects.filter(pk__in=[row['last_id'] for row in last_ids])
    }
    unread = _unread_by_conversation(request.user, convs)

    def last_activity(conversation):
      last = last_by_conv.get(conversation.id)
      return last.created_at if last else conversation.created_at

    convs.sort(key=last_activity, reverse=True)

    summaries = []
    for conversation in convs:
      role = _conversation_role(conversation, request.user)
      last = last_by_conv.get(conversation.id)
      summaries.append({
        'id': conversation.id,
        'job': _job_summary(conversation.job),
        'counterpart': _conversation_counterpart(conversation, role),
        'last_message': MessageSerializer(last).data if last else None,
        'unread_count': unread.get(conversation.id, 0),
      })

    return Response({'me': request.user.id, 'conversations': summaries})

  elif request.method == 'POST':
    # Employer-only: opening a thread requires owning the job, so a candidate
    # body fails the gate below. The first message travels in the same request
    # (and transaction) - threads are never born empty.
    try:
      candidate_id = int(request.data.get('candidate'))
      job_id = int(request.data.get('job'))
    except (TypeError, ValueError):
      return Response({'error': 'candidate and job ids are required.'}, status=status.HTTP_400_BAD_REQUEST)

    body, error = _clean_message_body(request.data.get('body'))
    if error:
      return Response({'error': error}, status=status.HTTP_400_BAD_REQUEST)

    try:
      job = Job.objects.select_related('company').get(pk=job_id)
    except Job.DoesNotExist:
      return Response(status=status.HTTP_404_NOT_FOUND)

    if not _employer_can_message(request.user, candidate_id, job):
      return Response(status=status.HTTP_403_FORBIDDEN)

    with transaction.atomic():
      # Idempotent: a second "Message" tap appends to the existing thread (the
      # unique constraint makes the get_or_create race safe).
      conversation, created = Conversation.objects.get_or_create(job=job, candidate_id=candidate_id)
      Message.objects.create(conversation=conversation, sender=request.user, body=body)
      _mark_read(conversation, 'employer')

    return Response(
      _thread_payload(conversation, request.user, 'employer'),
      status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
    )

conversations.cls.throttle_scope = 'messages'

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def conversation_details(request, id, format=None):
  try:
    conversation = _member_conversations(request.user).select_related('job__company', 'candidate').get(pk=id)
  except Conversation.DoesNotExist:
    return Response(status=status.HTTP_404_NOT_FOUND)

  after_id = None
  after_raw = request.query_params.get('after')
  if after_raw is not None:
    try:
      after_id = int(after_raw)
    except (TypeError, ValueError):
      return Response({'error': 'after must be a message id.'}, status=status.HTTP_400_BAD_REQUEST)

  role = _conversation_role(conversation, request.user)
  # Fetching a thread IS reading it - so the read cursor advances here rather
  # than through a separate mark-read endpoint. EXCEPT under ?peek=1: the inbox
  # auto-opens the newest thread in its desktop pane, and that pane is hidden on
  # mobile - marking it read there would clear an unread badge for messages the
  # user never saw. A peeked thread gets marked read by the pane's poll loop,
  # which only runs while the pane is genuinely visible.
  if request.query_params.get('peek') not in ('1', 'true'):
    _mark_read(conversation, role)

  return Response(_thread_payload(conversation, request.user, role, after_id=after_id))

@api_view(['POST'])
@permission_classes([IsAuthenticated])
@throttle_classes([PostScopedRateThrottle])
def conversation_messages(request, id, format=None):
  # Membership is the whole permission here: an employer-side thread only
  # exists if the gate passed at creation, and being its candidate means an
  # employer has already messaged you (threads are born with a message).
  try:
    conversation = _member_conversations(request.user).select_related('job__company', 'candidate').get(pk=id)
  except Conversation.DoesNotExist:
    return Response(status=status.HTTP_404_NOT_FOUND)

  body, error = _clean_message_body(request.data.get('body'))
  if error:
    return Response({'error': error}, status=status.HTTP_400_BAD_REQUEST)

  message = Message.objects.create(conversation=conversation, sender=request.user, body=body)
  _mark_read(conversation, _conversation_role(conversation, request.user))

  return Response(MessageSerializer(message).data, status=status.HTTP_201_CREATED)

conversation_messages.cls.throttle_scope = 'messages'

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def conversations_unread_count(request, format=None):
  # Lightweight badge feed - polled by the nav on both sides.
  convs = list(_member_conversations(request.user).only('id', 'candidate_id'))
  unread = _unread_by_conversation(request.user, convs)
  counts = [n for n in unread.values() if n]
  return Response({
    'unread_conversations': len(counts),
    'unread_messages': sum(counts),
  })