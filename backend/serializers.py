import datetime

from rest_framework import serializers
from .models import MyUser, Company, CompanyBranch, Job, WorkExperience, Skill, Preference, SavedJob, SavedCandidate, Match, Application, ApplicationEvent, ApplicationQuestion, ApplicationAnswer, AttachmentRequirement, AttachmentAnswer, Message, MessageFile

class MyUserSerializer(serializers.ModelSerializer):
  class Meta:
    model = MyUser
    fields = ['id', 'first_name', 'last_name', 'email', 'pending_email', 'user_name', 'photo', 'phone_number', 'dob', 'address', 'postcode', 'city', 'state', 'country', 'email_notifications', 'is_staff', 'is_active', 'is_superuser', 'created_at', 'updated_at']
    # user_profile PATCH feeds request.data straight into this serializer, so the
    # privilege/lifecycle flags must never be client-writable. `email` only
    # changes through the verified flow (account_email_request/confirm).
    read_only_fields = ['id', 'email', 'pending_email', 'is_staff', 'is_active', 'is_superuser', 'created_at', 'updated_at']

class CompanyBranchSerializer(serializers.ModelSerializer):
  class Meta:
    model = CompanyBranch
    fields = '__all__'

class CompanySerializer(serializers.ModelSerializer):
  branches = CompanyBranchSerializer(many=True, read_only=True)

  class Meta:
    model = Company
    fields = '__all__'

class SkillSerializer(serializers.ModelSerializer):
  class Meta:
    model = Skill
    fields = '__all__'

class JobSerializer(serializers.ModelSerializer):
  skills = SkillSerializer(many=True, read_only=True)

  class Meta:
    model = Job
    fields = '__all__'
    depth = 1

class WorkExperienceSerializer(serializers.ModelSerializer):
  skills = SkillSerializer(many=True, read_only=True)

  class Meta:
    model = WorkExperience
    fields = '__all__'
    depth = 1

class PreferenceSerializer(serializers.ModelSerializer):
  class Meta:
    model = Preference
    fields = '__all__'

class SavedJobSerializer(serializers.ModelSerializer):
  class Meta:
    model = SavedJob
    fields = '__all__'

class SavedCandidateSerializer(serializers.ModelSerializer):
  # Write path. Explicit fields (not '__all__') so created_at can't be spoofed
  # and the note stays bounded. `company` is set by the view from the token.
  note = serializers.CharField(required=False, allow_blank=True, max_length=2000)

  class Meta:
    model = SavedCandidate
    fields = ['id', 'company', 'user', 'note']

class MatchSerializer(serializers.ModelSerializer):
  class Meta:
    model = Match
    fields = '__all__'

def current_role_for(user):
  # Prefer an ongoing role (no end date), else the most recent one. Callers MUST
  # prefetch `work_experiences` - this scans the cached list, it does not query.
  experiences = user.work_experiences.all()
  pool = [we for we in experiences if we.end_date is None] or list(experiences)
  return max(pool, key=lambda we: we.start_date).job_title if pool else None

# Lean, safe subset of MyUser for showing a candidate to an employer
# (no email / permission flags).
class CandidateBriefSerializer(serializers.ModelSerializer):
  class Meta:
    model = MyUser
    fields = ['id', 'first_name', 'last_name', 'user_name', 'photo', 'address', 'city']

# A match seen from inside a candidate - `user` lives on the parent, so it is
# deliberately absent here. `job` stays a scalar id: the frontend already resolves
# titles and branches from `company_jobs` in the same payload.
class MatchSummarySerializer(serializers.ModelSerializer):
  class Meta:
    model = Match
    fields = ['id', 'job', 'is_invited', 'score', 'created_at']

# Shortlist metadata. Doubles as the POST/PATCH response body, so the client can
# drop it straight into the `saved` slot it already renders.
class SavedMetaSerializer(serializers.ModelSerializer):
  class Meta:
    model = SavedCandidate
    fields = ['id', 'note', 'created_at']

# One candidate as this company sees them: profile + every match on the company's
# jobs + shortlist metadata. Backs BOTH the matched-candidates page (`saved` is
# null) and the saved-candidates page (`saved` is set), so the two lists share one
# shape. Built from the plain dicts `_company_candidates` assembles - DRF reads
# Mappings as readily as model instances.
class CompanyCandidateSerializer(serializers.Serializer):
  user = CandidateBriefSerializer(read_only=True)
  matches = MatchSummarySerializer(many=True, read_only=True)
  # DRF renders a None attribute as null on its own; allow_null additionally keeps
  # a missing key from raising.
  saved = SavedMetaSerializer(read_only=True, allow_null=True)
  current_role = serializers.SerializerMethodField()
  top_score = serializers.SerializerMethodField()
  matched_at = serializers.SerializerMethodField()

  def get_current_role(self, obj):
    return current_role_for(obj['user'])

  def get_top_score(self, obj):
    scores = [m.score for m in obj['matches'] if m.score is not None]
    return max(scores) if scores else None

  def get_matched_at(self, obj):
    latest = max((m.created_at for m in obj['matches']), default=None)
    # Coerced explicitly so it matches the ISO string the nested `created_at`
    # fields render, rather than leaning on the JSON renderer to encode a datetime.
    return serializers.DateTimeField().to_representation(latest) if latest else None

class ApplicationSerializer(serializers.ModelSerializer):
  # Read shape for the candidate dashboard/list and the create response.
  # `user` and `job` stay scalar ids (no depth) - both frontends join them
  # against rows they already hold in the same payload.
  cover_letter = serializers.CharField(required=False, allow_blank=True, max_length=4000)

  class Meta:
    model = Application
    fields = ['id', 'user', 'job', 'status', 'cover_letter', 'created_at', 'updated_at']
    # Lifecycle fields have dedicated write paths (application_detail PATCH);
    # nothing client-supplied may set them on create. `user` always comes from
    # the token via save(user=...), never from the body.
    read_only_fields = ['user', 'status', 'created_at', 'updated_at']

# Candidate-safe event shape: no `note` (employer-internal) and no actor
# identity. `application` stays a scalar id so the flat list in GET
# /api/applications/ can be joined client-side like its sibling lists.
class ApplicationEventSerializer(serializers.ModelSerializer):
  class Meta:
    model = ApplicationEvent
    fields = ['id', 'application', 'from_status', 'to_status', 'created_at']

class EmployerApplicationEventSerializer(serializers.ModelSerializer):
  class Meta:
    model = ApplicationEvent
    fields = ['id', 'application', 'from_status', 'to_status', 'note', 'created_at']

# One applicant row as the employer's applications table renders it: the
# application fields plus the same lean candidate brief the rest of the
# employer UI uses, and the recommender score for the exact job they applied
# to (passed via context as {(user_id, job_id): score} to stay query-flat).
class ApplicantRowSerializer(serializers.ModelSerializer):
  candidate = CandidateBriefSerializer(source='user', read_only=True)
  score = serializers.SerializerMethodField()
  total_experience_months = serializers.SerializerMethodField()

  class Meta:
    model = Application
    fields = ['id', 'user', 'job', 'status', 'cover_letter', 'employer_viewed_at', 'created_at', 'updated_at', 'candidate', 'score', 'total_experience_months']

  def get_score(self, obj):
    return self.context.get('scores', {}).get((obj.user_id, obj.job_id))

  def get_total_experience_months(self, obj):
    # Sum of whole months across the candidate's roles (open roles count up to
    # today) - the same math as the frontend's deriveStats, so the table's
    # "(2 years 8 months)" agrees with the review modal's total. None (not 0)
    # when they have no work history at all, so "no experience listed" is
    # distinguishable from "less than a month". Callers MUST prefetch
    # `user__work_experiences` - this scans the cached list, it does not query.
    experiences = obj.user.work_experiences.all()
    if not experiences:
      return None
    today = datetime.date.today()
    total = 0
    for we in experiences:
      end = we.end_date or today
      months = (end.year - we.start_date.year) * 12 + (end.month - we.start_date.month)
      if months > 0:
        total += months
    return total

class ApplicationQuestionSerializer(serializers.ModelSerializer):
  class Meta:
    model = ApplicationQuestion
    fields = '__all__'

class ApplicationAnswerSerializer(serializers.ModelSerializer):
  class Meta:
    model = ApplicationAnswer
    fields = '__all__'

class AttachmentRequirementSerializer(serializers.ModelSerializer):
  class Meta:
    model = AttachmentRequirement
    fields = '__all__'

class AttachmentAnswerSerializer(serializers.ModelSerializer):
  class Meta:
    model = AttachmentAnswer
    fields = '__all__'

# One chat message. `sender` stays a bare user id - the thread payload carries
# `me`, so the client tells its own messages apart by comparing the two, and no
# per-message identity (name/email) ever leaves the server. Conversation payloads
# have no ModelSerializer: the views assemble them per-viewer, because what the
# counterpart looks like depends on which side is asking.
class MessageSerializer(serializers.ModelSerializer):
  class Meta:
    model = Message
    fields = ['id', 'sender', 'body', 'created_at']

class MessageFileSerializer(serializers.ModelSerializer):
  class Meta:
    model = MessageFile
    fields = '__all__'