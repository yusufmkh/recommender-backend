from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework import status

from backend import recommendermodel

from .models import MyUser, Company, Job, WorkExperience, Skill, Preference, SavedJob, SavedCandidate, Match, Application, ApplicationQuestion, ApplicationAnswer, AttachmentRequirement, AttachmentAnswer, Conversation, Message, MessageFile

from .serializers import MyUserSerializer, CompanySerializer, JobSerializer, WorkExperienceSerializer, SkillSerializer, PreferenceSerializer, SavedJobSerializer, SavedCandidateSerializer, MatchSerializer, ApplicationSerializer, ApplicationQuestionSerializer, ApplicationAnswerSerializer, AttachmentRequirementSerializer, AttachmentAnswerSerializer, ConversationSerializer, MessageSerializer, MessageFileSerializer

@api_view(['POST'])
def user_register(request):
  user = MyUser.objects.create_user(**request.data)
  user_data_serializer = MyUserSerializer(user)
  # if user_data_serializer.is_valid():
    # user_data_serializer.save()
    
  return Response(user_data_serializer.data, status=status.HTTP_201_CREATED)

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

@api_view(['GET', 'POST'])
@permission_classes([IsAuthenticated])
def user_work_experiences(request):
  if request.method == 'GET':
    work_experiences = WorkExperience.objects.filter(user=request.user)

    work_experiences_serializer = WorkExperienceSerializer(work_experiences, many=True)

    return Response(work_experiences_serializer.data)
  
  elif request.method == 'POST':
      work_skills_data = request.data.pop('skills')
      work_experience = WorkExperience.objects.create(user=request.user, **request.data)

      for work_skill_data in work_skills_data:
        try:
          skill = Skill.objects.get(name=work_skill_data)
        except Skill.DoesNotExist:
          skill = Skill(name=work_skill_data)
          skill.save()
        work_experience.skills.add(skill)
      
      work_experience_serializer = WorkExperienceSerializer(work_experience)

      return Response(work_experience_serializer.data, status=status.HTTP_201_CREATED)

@api_view(['GET', 'POST'])
@permission_classes([IsAuthenticated])
def user_skills(request):
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
    user_preferences = Preference.objects.filter(user=request.user)

    user_preferences_serializer = PreferenceSerializer(user_preferences, many=True)

    return Response(user_preferences_serializer.data)
  
  elif request.method == 'POST':
    user_preferences_serializer = PreferenceSerializer(data={'user': request.user.id, **request.data})

    if user_preferences_serializer.is_valid():
      user_preferences_serializer.save()

      return Response(user_preferences_serializer.data, status=status.HTTP_201_CREATED)
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

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def company_dashboard(request, format=None):
  company_info = Company.objects.get(user=request.user)
  company_jobs = Job.objects.filter(company=company_info)
  job_applicants = Application.objects.filter(job__in=company_jobs)
  candidate_matches = Match.objects.filter(job__in=company_jobs)
  candidate_invites = Match.objects.filter(job__in=company_jobs, is_invited__exact=True)
  saved_candidates = SavedCandidate.objects.filter(company=company_info)

  company_info_serializer = CompanySerializer(company_info)
  company_jobs_serializer = JobSerializer(company_jobs, many=True)
  job_applicants_serializer = ApplicationSerializer(job_applicants, many=True)
  candidate_matches_serializer = MatchSerializer(candidate_matches, many=True)
  candidate_invites_serializer = MatchSerializer(candidate_invites, many=True)
  saved_candidates_serializer = SavedCandidateSerializer(saved_candidates, many=True)

  return Response(
    {
      'company_info': company_info_serializer.data,
      'company_jobs': company_jobs_serializer.data,
      'job_applicants': job_applicants_serializer.data,
      'candidate_matches': candidate_matches_serializer.data,
      'candidate_invites': candidate_invites_serializer.data,
      'saved_candidates': saved_candidates_serializer.data
    }
  )

@api_view(['GET', 'POST'])
@permission_classes([IsAuthenticated])
def jobs(request, format=None):

  jobs = Job.objects.all()
  jobs_data = JobSerializer(jobs, many=True).data

  if request.method == 'GET':
    jobs_serializer = JobSerializer(jobs, many=True)
    return Response(jobs_serializer.data)
  
  if request.method == 'POST':
    job_data = request.data
    job_skills = job_data.pop('skills')
    job = Job.objects.create(**job_data)

    company = Company.objects.get(user_id=request.user)
    company_data = CompanySerializer(company).data

    for job_skill in job_skills:
      try:
        skill = Skill.objects.get(name=job_skill)
      except Skill.DoesNotExist:
        skill = Skill(name=job_skill)
        skill.save()
        
      job.skills.add(skill)
    
    job_serializer = JobSerializer(job)

    candidate_predictions = recommendermodel.predict(
      data={
        "id": len(jobs_data) + 1,
        "company_type": company_data['company_type'],
        "company_size": company_data['company_size'],
        "job_type": job_data['job_type'],
        "pay_range": job_data['pay_range'],
        "skills": job_skills
      },
      input_type='job',
      current_user=request.user
    )

    return Response({
      "job": job_serializer.data,
      "candidate_predictions": candidate_predictions
      }, status=status.HTTP_201_CREATED)

@api_view(['GET', 'PUT', 'DELETE'])
@permission_classes([IsAuthenticated])
def job_details(request, id, format=None):
  try:
    job = Job.objects.get(pk=id)
  except Job.DoesNotExist:
    return Response(status=status.HTTP_404_NOT_FOUND)

  if request.method == 'GET':
    job_serializer = JobSerializer(job)
    return Response(job_serializer.data)
  
  elif request.method == 'PUT':

    job_skills = request.data.pop('skills')
    updated_job = Job.objects.create(**request.data)

    for job_skill in job_skills:
      try:
        skill = Skill.objects.get(name=job_skill)
      except Skill.DoesNotExist:
        skill = Skill(name=job_skill)
        skill.save()
        
      updated_job.skills.add(skill)

    job_serializer = JobSerializer(job, data=updated_job)
    if job_serializer.is_valid():
      job_serializer.save()
      return Response(job_serializer.data)
    
    else:
      return Response(job_serializer.errors, status=status.HTTP_400_BAD_REQUEST)
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

@api_view(['GET', 'POST'])
@permission_classes([IsAuthenticated])
def saved_candidates(request, company_id):
  if request.method == 'GET':
    # Validate if the user has the company with the "company_id"
    saved_candidates = SavedCandidate.objects.filter(company=company_id)
    saved_candidates_serializer = SavedCandidateSerializer(saved_candidates, many=True)

    return Response(saved_candidates_serializer.data)
  
  elif request.method == 'POST':
    saved_candidate_serializer = SavedCandidateSerializer(data={'company': company_id, **request.data})
    if saved_candidate_serializer.is_valid():
      saved_candidate_serializer.save()

      return Response(saved_candidate_serializer.data, status=status.HTTP_201_CREATED)
    else:
      return Response(saved_candidate_serializer.errors, status=status.HTTP_400_BAD_REQUEST)

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
    application_job = application.pop('job')
    application_serializer = ApplicationSerializer(data={'user': request.user.id, 'job': application_job})
    
    if application_serializer.is_valid(raise_exception=True):
      application_serializer.save()

      if len(application['questions']) > 0:
        application_questions = application.pop('questions')
        for application_question in application_questions:
          application_question_serializer = ApplicationQuestionSerializer(data={'application': application_serializer, 'question': application_question['question']})

          if application_question_serializer.is_valid():
            application_question_serializer.save()

            application_answer_serializer = ApplicationAnswerSerializer(data={'application_question': application_question_serializer, 'answer': application_question['answer']})

            if application_answer_serializer.is_valid():
              application_answer_serializer.save()

      if len(application['attachment_requirements']) > 0:
        attachment_requirements = application.pop('attachment_requirements')
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