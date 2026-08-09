import datetime

from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase, APIClient

from .models import MyUser, Company, Job, Match, Application, SavedCandidate, WorkExperience
from .serializers import MyUserSerializer

class CandidateTests(APITestCase):

  def setUp(self):
    email = 'test@test.com'
    password = 't1234567u'
    # A JWT is only issued for a verified account, so the test user has to be
    # active before token_obtain_pair will hand one out.
    user = MyUser.objects.create(first_name='Test', last_name='One', email=email, user_name='testone', is_active=True)
    user.set_password(password)
    user.save()
    user_serializer = MyUserSerializer(user)
    self.user = user_serializer.data

    jwt_fetch_data = {
        'email': email,
        'password': password
    }

    url = reverse('token_obtain_pair')
    response = self.client.post(url, jwt_fetch_data, format='json')
    print(response.data)
    token = response.data['access']
    self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {token}')

  # def test_user_register(self):
  #   data = {
  #     "first_name": "Test User",
  #     "last_name": "One",
  #     "email": "testone@test.com",
  #     "user_name": "testuserone",
  #     "password": "t1234567u",
  #     "is_active": True
  #   }

  #   url = reverse("user_register")

  #   response = self.client.post(url, data, format='json')
  #   self.assertEqual(response.status_code, status.HTTP_201_CREATED)
  #   self.assertEqual(response.data['last_name'], 'One')
  
  def test_user_preferences(self):
    data = {
      "job_type": "full-time",
      "company_type": "restaurant",
      "company_size": "medium",
      "pay_range": "pay35_40"
    }

    url = reverse("user_preferences")

    response = self.client.post(url, data, format='json')
    print(response.data)
    self.assertEqual(response.data['job_type'], 'full-time')


class EmployerShortlistTests(APITestCase):
  """Saving a candidate moves them from the matched list to the shortlist without
  touching their Match rows, so the saved page can still show matched/invited jobs."""

  def _employer(self, slug):
    user = MyUser.objects.create_user(
      email=f'{slug}@test.com', user_name=slug, first_name=slug, last_name='Employer',
      password='pw12345678', is_active=True,
    )
    company = Company.objects.create(
      user=user, name=f'{slug} Ltd', email=f'{slug}@test.com', phone_number='0',
      address='1 Road', postcode='E1', city='London', state='London', country='UK',
    )
    return user, company

  def _candidate(self, slug):
    return MyUser.objects.create_user(
      email=f'{slug}@test.com', user_name=slug, first_name=slug, last_name='Candidate',
      password='pw12345678', is_active=True,
    )

  def setUp(self):
    self.employer_a, self.company_a = self._employer('alpha')
    self.employer_b, self.company_b = self._employer('beta')

    self.job_a = Job.objects.create(company=self.company_a, title='Chef', description='Cook')
    self.job_b = Job.objects.create(company=self.company_b, title='Barista', description='Pour')

    self.matched = self._candidate('matched')
    self.other = self._candidate('other')
    self.stranger = self._candidate('stranger')

    WorkExperience.objects.create(
      user=self.matched, job_title='Sous Chef', description='...',
      start_date=datetime.date(2023, 1, 1),
    )

    self.match = Match.objects.create(user=self.matched, job=self.job_a, score=90)
    Match.objects.create(user=self.other, job=self.job_a, score=50)
    # The same candidate is matched to company B as well - shortlisting them at A
    # must not affect what B sees.
    Match.objects.create(user=self.matched, job=self.job_b, score=70)

    self.client.force_authenticate(user=self.employer_a)

  def _dashboard(self, employer=None):
    if employer:
      self.client.force_authenticate(user=employer)
    return self.client.get(reverse('company_dashboard')).data

  def _save(self, candidate, note=''):
    return self.client.post(
      reverse('company_saved_candidates'), {'user': candidate.id, 'note': note}, format='json',
    )

  def _user_ids(self, rows):
    return {row['user']['id'] for row in rows}

  def test_saving_moves_candidate_to_the_shortlist(self):
    before = self._dashboard()
    self.assertIn(self.matched.id, self._user_ids(before['candidate_matches']))
    self.assertEqual(before['saved_candidates'], [])

    self.assertEqual(self._save(self.matched).status_code, status.HTTP_201_CREATED)

    after = self._dashboard()
    self.assertNotIn(self.matched.id, self._user_ids(after['candidate_matches']))
    self.assertIn(self.matched.id, self._user_ids(after['saved_candidates']))
    # The other matched candidate is untouched.
    self.assertIn(self.other.id, self._user_ids(after['candidate_matches']))

  def test_match_rows_survive_and_travel_with_the_candidate(self):
    self._save(self.matched)

    self.assertTrue(Match.objects.filter(pk=self.match.pk).exists())

    row = next(r for r in self._dashboard()['saved_candidates'] if r['user']['id'] == self.matched.id)
    # Only this company's job - never the match against company B's job.
    self.assertEqual([m['job'] for m in row['matches']], [self.job_a.id])
    self.assertEqual(row['top_score'], 90)
    self.assertEqual(row['current_role'], 'Sous Chef')

  def test_invited_candidate_stays_on_the_invites_list_after_saving(self):
    self.match.is_invited = True
    self.match.save()

    self._save(self.matched)

    dashboard = self._dashboard()
    self.assertIn(self.match.id, {invite['id'] for invite in dashboard['candidate_invites']})
    self.assertNotIn(self.matched.id, self._user_ids(dashboard['candidate_matches']))

  def test_saved_candidate_with_no_matches_is_still_listed(self):
    self._save(self.matched)
    Match.objects.filter(user=self.matched, job=self.job_a).delete()

    row = next(r for r in self._dashboard()['saved_candidates'] if r['user']['id'] == self.matched.id)
    self.assertEqual(row['matches'], [])
    self.assertIsNone(row['top_score'])

  def test_shortlist_does_not_leak_between_companies(self):
    self._save(self.matched)

    dashboard_b = self._dashboard(self.employer_b)
    self.assertEqual(dashboard_b['saved_candidates'], [])
    # Still an untriaged match for company B.
    self.assertIn(self.matched.id, self._user_ids(dashboard_b['candidate_matches']))

  def test_saving_twice_returns_the_existing_row(self):
    first = self._save(self.matched, note='Great fit')
    second = self._save(self.matched, note='ignored')

    self.assertEqual(first.status_code, status.HTTP_201_CREATED)
    self.assertEqual(second.status_code, status.HTTP_200_OK)
    self.assertEqual(first.data['id'], second.data['id'])
    self.assertEqual(second.data['note'], 'Great fit')
    self.assertEqual(SavedCandidate.objects.filter(company=self.company_a).count(), 1)

  def test_cannot_save_an_unreachable_candidate(self):
    response = self._save(self.stranger)

    self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
    self.assertFalse(SavedCandidate.objects.filter(user=self.stranger).exists())

  def test_can_save_an_applicant_who_has_no_match(self):
    Application.objects.create(user=self.stranger, job=self.job_a)

    self.assertEqual(self._save(self.stranger).status_code, status.HTTP_201_CREATED)

  def test_another_company_cannot_touch_the_row(self):
    saved_id = self._save(self.matched).data['id']

    self.client.force_authenticate(user=self.employer_b)
    url = reverse('company_saved_candidate_details', args=[saved_id])

    self.assertEqual(self.client.delete(url).status_code, status.HTTP_404_NOT_FOUND)
    self.assertEqual(self.client.patch(url, {'note': 'x'}, format='json').status_code, status.HTTP_404_NOT_FOUND)
    self.assertTrue(SavedCandidate.objects.filter(pk=saved_id).exists())

  def test_note_round_trip_and_unsave_returns_them_to_matches(self):
    saved_id = self._save(self.matched).data['id']
    url = reverse('company_saved_candidate_details', args=[saved_id])

    patched = self.client.patch(url, {'note': 'Second interview booked'}, format='json')
    self.assertEqual(patched.data['note'], 'Second interview booked')

    row = next(r for r in self._dashboard()['saved_candidates'] if r['user']['id'] == self.matched.id)
    self.assertEqual(row['saved']['note'], 'Second interview booked')

    self.assertEqual(self.client.delete(url).status_code, status.HTTP_204_NO_CONTENT)

    after = self._dashboard()
    self.assertEqual(after['saved_candidates'], [])
    self.assertIn(self.matched.id, self._user_ids(after['candidate_matches']))

  def test_saved_candidate_profile_stays_viewable_without_a_match(self):
    Application.objects.create(user=self.stranger, job=self.job_a)
    self._save(self.stranger)
    Application.objects.filter(user=self.stranger).delete()

    response = self.client.get(reverse('candidate_profile', args=[self.stranger.id]))
    self.assertEqual(response.status_code, status.HTTP_200_OK)

  def test_dashboard_query_count_does_not_grow_with_candidates(self):
    with CaptureQueriesContext(connection) as baseline:
      self.client.get(reverse('company_dashboard'))

    for i in range(5):
      extra = self._candidate(f'extra{i}')
      WorkExperience.objects.create(
        user=extra, job_title=f'Role {i}', description='...', start_date=datetime.date(2024, 1, 1),
      )
      Match.objects.create(user=extra, job=self.job_a, score=10 + i)
      SavedCandidate.objects.create(company=self.company_a, user=extra)

    with CaptureQueriesContext(connection) as grown:
      self.client.get(reverse('company_dashboard'))

    self.assertEqual(len(baseline.captured_queries), len(grown.captured_queries))
