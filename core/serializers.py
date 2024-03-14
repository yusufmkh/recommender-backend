from rest_framework import serializers
from .models import MyUser, Company, Job, WorkExperience, Skill, Preference, SavedJob, SavedCandidate, Match, Application, ApplicationQuestion, ApplicationAnswer, AttachmentRequirement, AttachmentAnswer, Conversation, Message, MessageFile

class MyUserSerializer(serializers.ModelSerializer):
  class Meta:
    model = MyUser
    fields = '__all__'

class CompanySerializer(serializers.ModelSerializer):
  class Meta:
    model = Company
    fields = '__all__'

class JobSerializer(serializers.ModelSerializer):
  class Meta:
    model = Job
    fields = '__all__'

class WorkExperienceSerializer(serializers.ModelSerializer):
  class Meta:
    model = WorkExperience
    fields = '__all__'

class SkillSerializer(serializers.ModelSerializer):
  class Meta:
    model = Skill
    fields = '__all__'

class PreferenceSerializer(serializers.ModelSerializer):
  class Meta:
    model = Preference
    fields = '__all__'

class SavedJobSerializer(serializers.ModelSerializer):
  class Meta:
    model = SavedJob
    fields = '__all__'

class SavedCandidateSerializer(serializers.ModelSerializer):
  class Meta:
    model = SavedCandidate
    fields = '__all__'

class MatchSerializer(serializers.ModelSerializer):
  class Meta:
    model = Match
    fields = '__all__'

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