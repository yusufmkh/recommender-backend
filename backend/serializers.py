from rest_framework import serializers
from .models import MyUser, Company, CompanyBranch, Job, WorkExperience, Skill, Preference, SavedJob, SavedCandidate, Match, Application, ApplicationQuestion, ApplicationAnswer, AttachmentRequirement, AttachmentAnswer, Conversation, Message, MessageFile

class MyUserSerializer(serializers.ModelSerializer):
  class Meta:
    model = MyUser
    fields = ['id', 'first_name', 'last_name', 'email', 'user_name', 'photo', 'phone_number', 'dob', 'address', 'postcode', 'city', 'state', 'country', 'is_staff', 'is_active', 'is_superuser', 'created_at', 'updated_at']
    # user_profile PATCH feeds request.data straight into this serializer, so the
    # privilege/lifecycle flags must never be client-writable.
    read_only_fields = ['id', 'is_staff', 'is_active', 'is_superuser', 'created_at', 'updated_at']

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
  class Meta:
    model = Application
    fields = '__all__'

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

class ConversationSerializer(serializers.ModelSerializer):
  class Meta:
    model = Conversation
    fields = '__all__'

class MessageSerializer(serializers.ModelSerializer):
  class Meta:
    model = Message
    fields = '__all__'

class MessageFileSerializer(serializers.ModelSerializer):
  class Meta:
    model = MessageFile
    fields = '__all__'