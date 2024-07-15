import pandas as pd
import numpy as np
import tensorflow as tf
import keras

from sklearn.preprocessing import OneHotEncoder

from .models import MyUser, Company, Job, WorkExperience, Preference
from .serializers import MyUserSerializer, CompanySerializer, JobSerializer, WorkExperienceSerializer, PreferenceSerializer

ohe = OneHotEncoder(handle_unknown='ignore')

def preprocess_input(data, input_type, current_user):
  if input_type == 'job':

    job_skills = data.pop('skills')
    
    # new_job_model_data = {}

    # for job_skill in job_skills:
    #   job_skill_number = 1
    #   new_job_model_data[f"skill_{job_skill_number}"] = job_skill
    #   job_skill_number += 1

    new_job_model_data = {
      "skill_1": job_skills[0],
      "skill_2": job_skills[1],
      "skill_3": job_skills[2],
      "company_type": data['company_type'],
      "company_size": data['company_size'],
      "job_type": data['job_type'],
      "pay_range": data['pay_range']
    }

    new_job_df = pd.DataFrame([new_job_model_data])

    users_unserialized = MyUser.objects.all()
    work_experiences_unserialized = WorkExperience.objects.all()
    user_preferences_unserialized = Preference.objects.all()

    users = MyUserSerializer(users_unserialized, many=True).data
    work_experiences = WorkExperienceSerializer(work_experiences_unserialized, many=True).data
    user_preferences = PreferenceSerializer(user_preferences_unserialized, many=True).data

    users_data = []

    for user in users:
      item = 0

      for i in range(len(user_preferences)):
        if user_preferences[i]['user'] == user['id']:
          item = i
      
      user_data = {
        "company_type": user_preferences[item]['company_type'],
        "company_size": user_preferences[item]['company_size'],
        "job_type": user_preferences[item]['job_type'],
        "pay_range": user_preferences[item]['pay_range']
      }

      for we_i in range(len(work_experiences)):
        if user['id'] == work_experiences[we_i]['user']['id']:
          skill_number = 1
          for skill in work_experiences[we_i]['skills']:
            print(skill)

            user_data[f'skill_{skill_number}'] = skill['name']

            skill_number += 1
      
      users_data.append(user_data)

    users_df = pd.DataFrame(users_data)

    # candidate_ids = users_df.pop('user_id')

    candidate_samples_enc = pd.get_dummies(users_df, dtype=float)
    # candidate_samples_enc = ohe.fit_transform(users_df).toarray()
    # candidate_samples_enc_features = ohe.get_feature_names_out(users_df.columns)
    # candidate_samples_enc_data = pd.DataFrame(candidate_samples_enc, columns=candidate_samples_enc_features)

    job_vecs_df = pd.DataFrame(np.tile(new_job_df, (len(users_data), 1)), columns=new_job_df.columns)

    # job_vecs_ids = job_vecs_df.pop('job_id')

    job_vecs_enc = pd.get_dummies(job_vecs_df, dtype=float)
    # job_vecs_enc = ohe.transform(job_vecs_df).toarray()
    # job_vecs_enc_features = ohe.get_feature_names_out(job_vecs_df.columns)
    # job_vecs_enc_data = pd.DataFrame(job_vecs_enc, columns=job_vecs_enc_features)


    print(candidate_samples_enc)
    print(job_vecs_enc)
    return [candidate_samples_enc, job_vecs_enc]
  
  elif input_type == 'candidate':
    candidate_skills = data.pop('skills')

    new_candidate_model_data = {
      # "user_id": current_user['id'],
      "skill_1": candidate_skills[0],
      "skill_2": candidate_skills[1],
      "skill_3": candidate_skills[2],
      "company_type": data['company_type'],
      "company_size": data['company_size'],
      "job_type": data['job_type'],
      "pay_range": data['pay_range']
    }

    for candidate_skill in candidate_skills:
      candidate_skill_number = 1
      new_candidate_model_data['skill_{candidate_skill_number}'] = candidate_skill
      candidate_skill_number += 1

    new_candidate_df = pd.DataFrame([new_candidate_model_data])

    jobs_unserialized = Job.objects.all()
    companies_unserialized = Company.objects.all()

    jobs = JobSerializer(jobs_unserialized, many=True)
    companies = CompanySerializer(companies_unserialized, many=True)

    jobs_data = []

    for job in jobs:
      job_data = {
        # "job_id": job['id'],
        "skill_1": job['skills'][0]['name'],
        "skill_2": job['skills'][1]['name'],
        "skill_3": job['skills'][2]['name'],
        "job_type": job['job_type'],
        "pay_range": job['pay_range'],
      }
      
      for company in companies:
        if job['company_id'] == company['id']:
          job_data['company_type'] = company['company_type'],
          job_data['company_size'] = company['company_size']
      
      jobs_data.append(job_data)

    jobs_df = pd.DataFrame(jobs_data)

    # job_ids = jobs_df.pop('job_id')

    job_samples_enc = ohe.fit_transform(jobs_df)
    job_samples_enc_features = ohe.get_feature_names_out(jobs_df.columns)
    job_samples_enc_data = pd.DataFrame(job_samples_enc, columns=job_samples_enc_features)

    candidate_vecs_df = pd.DataFrame(np.tile(new_candidate_df, (len(jobs_data), 1)), columns=new_candidate_df.columns)

    # candidate_vecs_ids = candidate_vecs_df.pop('candidate_id')

    candidate_vecs_enc = ohe.transform(candidate_vecs_df).toarray()
    candidate_vecs_enc_features = ohe.get_feature_names_out(candidate_vecs_df.columns)
    candidate_vecs_enc_data = pd.DataFrame(candidate_vecs_enc, columns=candidate_vecs_enc_features)
    

    return [job_samples_enc_data, candidate_vecs_enc_data]

def predict(data, input_type, current_user):
  preprocessed_data = preprocess_input(data, input_type, current_user)
  recommender_model = tf.keras.models.load_model('backend/recommender_model.keras')
  job_pred = recommender_model.predict([preprocessed_data[0], preprocessed_data[1]])
  
  return job_pred
