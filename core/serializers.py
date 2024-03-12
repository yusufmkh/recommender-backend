from rest_framework import serializers
from .models import MyUser, Company, Job, WorkExperience, Skill, Preference, SavedJob, SavedCandidate, Match, Application, ApplicationQuestion, ApplicationAnswer, AttachmentRequirement, AttachmentAnswer, Conversation, Message, MessageFile

class MyUserSerializer(serializers.ModelSerializer):
  class Meta:
    model = MyUser
    fields = ['id', 'first_name', 'last_name', 'email', 'user_name', 'photo', 'phone_number', 'dob', 'address', 'postcode', 'city', 'state', 'country', 'is_staff', 'is_active', 'created_at', 'updated_at']

class CompanySerializer(serializers.ModelSerializer):
  class Meta:
    model = Company
    fields = ['id', 'user', 'name', 'legal_name', 'email', 'photo', 'type', 'size', 'phone_number', 'website', 'address', 'postcode', 'city', 'state', 'country', 'created_at', 'updated_at']

class JobSerializer(serializers.ModelSerializer):
  class Meta:
    model = Job
    fields = ['id', 'company', 'title', 'description', 'job_type', 'pay', 'pay_range', 'status', 'contact', 'created_at', 'updated_at']

class WorkExperienceSerializer(serializers.ModelSerializer):
  class Meta:
    model = WorkExperience
    fields = ['id', 'user', 'company', 'job_title', 'description', 'company_name', 'company_address', 'company_website', 'start_date', 'end_date', 'created_at', 'updated_at']

class SkillSerializer(serializers.ModelSerializer):
  class Meta:
    model = Skill
    fields = ['id', 'work_experience', 'name', 'created_at', 'updated_at']

class PreferenceSerializer(serializers.ModelSerializer):
  class Meta:
    model = Preference
    fields = ['id', 'user', 'job_type', 'company_type', 'company_size', 'pay_range', 'created_at', 'updated_at']

class SavedJobSerializer(serializers.ModelSerializer):
  class Meta:
    model = SavedJob
    fields = ['id', 'user', 'job']

class SavedCandidateSerializer(serializers.ModelSerializer):
  class Meta:
    model = SavedCandidate
    fields = ['id', 'company', 'job', 'user']

class MatchSerializer(serializers.ModelSerializer):
  class Meta:
    model = Match
    fields = ['id', 'user', 'job', 'is_invited', 'created_at', 'updated_at']

class ApplicationSerializer(serializers.ModelSerializer):
  class Meta:
    model = Application
    fields = ['id', 'user', 'job', 'status', 'created_at', 'updated_at']

class ApplicationQuestionSerializer(serializers.ModelSerializer):
  class Meta:
    model = ApplicationQuestion
    fields = ['id', 'application', 'question']

class ApplicationAnswerSerializer(serializers.ModelSerializer):
  class Meta:
    model = ApplicationAnswer
    fields = ['id', 'application_question', 'answer']

class AttachmentRequirementSerializer(serializers.ModelSerializer):
  class Meta:
    model = AttachmentRequirement
    fields = ['id', 'application', 'requirement', 'attachment_type']

class AttachmentAnswerSerializer(serializers.ModelSerializer):
  class Meta:
    model = ApplicationAnswer
    fields = ['id', 'attachment_requirement', 'attachment']

class ConversationSerializer(serializers.ModelSerializer):
  class Meta:
    model = Conversation
    fields = ['id', 'creator', 'recipient', 'job', 'created_at']

class MessageSerializer(serializers.ModelSerializer):
  class Meta:
    model = Message
    fields = ['id', 'conversation', 'sender', 'message', 'created_at', 'updated_at']

class MessageFileSerializer(serializers.ModelSerializer):
  class Meta:
    model = MessageFile
    fields = ['id', 'message', 'file_link']