import datetime
from unittest import mock

from django.core import mail
from django.core.cache import cache
from django.db import connection
from django.test import override_settings
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase, APIClient

from .models import MyUser, Company, CompanyBranch, Job, Match, Application, ApplicationEvent, SavedCandidate, WorkExperience, Conversation, Message
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

  def test_applied_candidate_leaves_candidate_matches(self):
    Application.objects.create(user=self.matched, job=self.job_a)
    dashboard = self._dashboard()
    self.assertNotIn(self.matched.id, self._user_ids(dashboard['candidate_matches']))
    self.assertIn(self.other.id, self._user_ids(dashboard['candidate_matches']))
    # They only applied at company A - still an open match for company B.
    self.assertIn(self.matched.id, self._user_ids(self._dashboard(self.employer_b)['candidate_matches']))

  def test_withdrawn_application_still_hides_the_match(self):
    Application.objects.create(user=self.matched, job=self.job_a, status='w')
    self.assertNotIn(self.matched.id, self._user_ids(self._dashboard()['candidate_matches']))

  def test_applied_job_is_dropped_from_a_saved_candidates_matches(self):
    job_2 = Job.objects.create(company=self.company_a, title='Waiter', description='Serve')
    Match.objects.create(user=self.matched, job=job_2, score=40)
    self._save(self.matched)
    Application.objects.create(user=self.matched, job=self.job_a)
    row = next(r for r in self._dashboard()['saved_candidates'] if r['user']['id'] == self.matched.id)
    self.assertEqual([m['job'] for m in row['matches']], [job_2.id])
    self.assertEqual(row['top_score'], 40)

  def test_applied_match_is_not_an_open_invite(self):
    self.match.is_invited = True
    self.match.save()
    Application.objects.create(user=self.matched, job=self.job_a)
    dashboard = self._dashboard()
    self.assertNotIn(self.match.id, {invite['id'] for invite in dashboard['candidate_invites']})
    # The applicant row still carries the recommender score for that job.
    self.assertEqual(dashboard['job_applicants'][0]['score'], 90)

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


class ApplicationTests(APITestCase):
  """Applying is idempotent and profile-based; the application's status is the
  shared pipeline state - employers move it through the stages, candidates may
  only withdraw, and every change lands in the append-only event log."""

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
    self.employer, self.company = self._employer('alpha')
    self.other_employer, self.other_company = self._employer('beta')

    self.job = Job.objects.create(company=self.company, title='Chef', description='Cook')
    self.closed_job = Job.objects.create(company=self.company, title='Old Chef', description='Cooked', status='h')

    self.candidate = self._candidate('applicant')
    Match.objects.create(user=self.candidate, job=self.job, score=77)

    # The `applications` throttle counts per user id in the process-wide cache,
    # and every test re-creates its users with the same ids (DB rollback), so
    # applies would accumulate across the class and eventually 429.
    cache.clear()

    self.client.force_authenticate(user=self.candidate)

  def _apply(self, job=None, **extra):
    return self.client.post(
      reverse('applications'), {'job': (job or self.job).id, **extra}, format='json',
    )

  def _detail(self, application_id, user=None):
    if user:
      self.client.force_authenticate(user=user)
    return self.client.get(reverse('application_detail', args=[application_id]))

  def _set_status(self, application_id, new_status, user=None, **extra):
    if user:
      self.client.force_authenticate(user=user)
    return self.client.patch(
      reverse('application_detail', args=[application_id]), {'status': new_status, **extra}, format='json',
    )

  # --- applying ---

  def test_apply_creates_application_with_event_and_cover_letter(self):
    response = self._apply(cover_letter='  I cook well.  ')

    self.assertEqual(response.status_code, status.HTTP_201_CREATED)
    self.assertEqual(response.data['status'], 'a')
    self.assertEqual(response.data['cover_letter'], 'I cook well.')
    application = Application.objects.get(pk=response.data['id'])
    self.assertEqual(application.user, self.candidate)
    events = list(application.events.all())
    self.assertEqual([(e.from_status, e.to_status) for e in events], [('', 'a')])
    self.assertEqual(events[0].actor, self.candidate)

  def test_duplicate_apply_is_idempotent(self):
    first = self._apply()
    second = self._apply()

    self.assertEqual(first.status_code, status.HTTP_201_CREATED)
    self.assertEqual(second.status_code, status.HTTP_200_OK)
    self.assertEqual(first.data['id'], second.data['id'])
    self.assertTrue(second.data.get('already_applied'))
    self.assertEqual(Application.objects.filter(user=self.candidate, job=self.job).count(), 1)
    self.assertEqual(ApplicationEvent.objects.count(), 1)

  def test_cannot_apply_to_a_closed_job(self):
    response = self._apply(job=self.closed_job)

    self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
    self.assertFalse(Application.objects.exists())

  def test_employer_cannot_apply_to_their_own_job(self):
    self.client.force_authenticate(user=self.employer)

    self.assertEqual(self._apply().status_code, status.HTTP_403_FORBIDDEN)
    self.assertFalse(Application.objects.exists())

  def test_apply_validates_body(self):
    missing = self.client.post(reverse('applications'), {}, format='json')
    self.assertEqual(missing.status_code, status.HTTP_400_BAD_REQUEST)

    too_long = self._apply(cover_letter='x' * 4001)
    self.assertEqual(too_long.status_code, status.HTTP_400_BAD_REQUEST)
    self.assertFalse(Application.objects.exists())

  def test_client_cannot_smuggle_status_or_user_on_create(self):
    stranger = self._candidate('stranger')
    response = self._apply(status='h', user=stranger.id)

    self.assertEqual(response.status_code, status.HTTP_201_CREATED)
    application = Application.objects.get(pk=response.data['id'])
    self.assertEqual(application.status, 'a')
    self.assertEqual(application.user, self.candidate)

  def test_candidate_list_includes_events(self):
    application_id = self._apply().data['id']

    payload = self.client.get(reverse('applications')).data
    self.assertEqual([a['id'] for a in payload['user_applications']], [application_id])
    self.assertEqual(
      [(e['application'], e['to_status']) for e in payload['application_events']],
      [(application_id, 'a')],
    )
    # Candidate-safe shape: employer-internal notes never appear here.
    self.assertNotIn('note', payload['application_events'][0])

  # --- the employer pipeline ---

  def test_employer_moves_application_through_stages(self):
    application_id = self._apply().data['id']

    for stage in ('s', 'i', 't', 'h'):
      response = self._set_status(application_id, stage, user=self.employer)
      self.assertEqual(response.status_code, status.HTTP_200_OK)
      self.assertEqual(response.data['status'], stage)

    events = [(e.from_status, e.to_status) for e in Application.objects.get(pk=application_id).events.all()]
    self.assertEqual(events, [('', 'a'), ('a', 's'), ('s', 'i'), ('i', 't'), ('t', 'h')])

  def test_employer_note_is_recorded_but_hidden_from_the_candidate(self):
    application_id = self._apply().data['id']
    self._set_status(application_id, 'r', user=self.employer, note='Not enough experience')

    employer_view = self._detail(application_id, user=self.employer)
    self.assertIn('Not enough experience', [e['note'] for e in employer_view.data['events']])

    candidate_view = self._detail(application_id, user=self.candidate)
    self.assertEqual(candidate_view.status_code, status.HTTP_200_OK)
    for event in candidate_view.data['events']:
      self.assertNotIn('note', event)

  def test_employer_cannot_set_withdrawn_or_garbage(self):
    application_id = self._apply().data['id']

    self.assertEqual(self._set_status(application_id, 'w', user=self.employer).status_code, status.HTTP_400_BAD_REQUEST)
    self.assertEqual(self._set_status(application_id, 'z', user=self.employer).status_code, status.HTTP_400_BAD_REQUEST)
    self.assertEqual(Application.objects.get(pk=application_id).status, 'a')

  def test_non_participants_get_404(self):
    application_id = self._apply().data['id']

    self.assertEqual(self._detail(application_id, user=self.other_employer).status_code, status.HTTP_404_NOT_FOUND)
    self.assertEqual(self._set_status(application_id, 's', user=self.other_employer).status_code, status.HTTP_404_NOT_FOUND)

    stranger = self._candidate('stranger')
    self.assertEqual(self._detail(application_id, user=stranger).status_code, status.HTTP_404_NOT_FOUND)

  def test_employer_get_marks_application_viewed(self):
    application_id = self._apply().data['id']
    self.assertIsNone(Application.objects.get(pk=application_id).employer_viewed_at)

    # The candidate's own reads never mark it viewed.
    self._detail(application_id, user=self.candidate)
    self.assertIsNone(Application.objects.get(pk=application_id).employer_viewed_at)

    response = self._detail(application_id, user=self.employer)
    self.assertEqual(response.status_code, status.HTTP_200_OK)
    self.assertIsNotNone(Application.objects.get(pk=application_id).employer_viewed_at)
    self.assertEqual(response.data['candidate']['id'], self.candidate.id)
    self.assertEqual(response.data['job']['id'], self.job.id)

  # --- withdrawing ---

  def test_candidate_can_withdraw_and_reapply(self):
    application_id = self._apply().data['id']

    withdrawn = self._set_status(application_id, 'w')
    self.assertEqual(withdrawn.status_code, status.HTTP_200_OK)
    self.assertEqual(withdrawn.data['status'], 'w')

    # A withdrawn application is frozen for the employer...
    conflict = self._set_status(application_id, 'i', user=self.employer)
    self.assertEqual(conflict.status_code, status.HTTP_409_CONFLICT)

    # ...and re-applying reactivates the SAME row rather than inserting another.
    self.client.force_authenticate(user=self.candidate)
    reapplied = self._apply(cover_letter='Second time lucky')
    self.assertEqual(reapplied.status_code, status.HTTP_200_OK)
    self.assertTrue(reapplied.data.get('reactivated'))
    self.assertEqual(reapplied.data['id'], application_id)
    self.assertEqual(Application.objects.count(), 1)

    application = Application.objects.get(pk=application_id)
    self.assertEqual(application.status, 'a')
    self.assertEqual(application.cover_letter, 'Second time lucky')
    events = [(e.from_status, e.to_status) for e in application.events.all()]
    self.assertEqual(events, [('', 'a'), ('a', 'w'), ('w', 'a')])

  def test_candidate_cannot_set_anything_but_withdrawn(self):
    application_id = self._apply().data['id']

    for stage in ('s', 'i', 't', 'h', 'r'):
      self.assertEqual(self._set_status(application_id, stage).status_code, status.HTTP_403_FORBIDDEN)
    self.assertEqual(Application.objects.get(pk=application_id).status, 'a')

  def test_candidate_cannot_withdraw_after_an_outcome(self):
    application_id = self._apply().data['id']
    self._set_status(application_id, 'h', user=self.employer)

    response = self._set_status(application_id, 'w', user=self.candidate)
    self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)
    self.assertEqual(Application.objects.get(pk=application_id).status, 'h')

  # --- the employer dashboard ---

  def test_dashboard_applicant_rows_carry_the_candidate_brief_and_score(self):
    self._apply()

    self.client.force_authenticate(user=self.employer)
    dashboard = self.client.get(reverse('company_dashboard')).data
    self.assertEqual(len(dashboard['job_applicants']), 1)
    row = dashboard['job_applicants'][0]
    self.assertEqual(row['candidate']['id'], self.candidate.id)
    self.assertEqual(row['candidate']['first_name'], 'applicant')
    self.assertEqual(row['score'], 77)
    self.assertEqual(row['job'], self.job.id)
    self.assertIsNone(row['employer_viewed_at'])
    # The brief never leaks contact or lifecycle fields.
    self.assertNotIn('email', row['candidate'])
    # No work history at all -> None, distinguishable from "less than a month".
    self.assertIsNone(row['total_experience_months'])

    WorkExperience.objects.create(
      user=self.candidate, job_title='Chef de Partie', description='...',
      start_date=datetime.date(2023, 1, 1), end_date=datetime.date(2024, 9, 1),
    )
    refreshed = self.client.get(reverse('company_dashboard')).data
    self.assertEqual(refreshed['job_applicants'][0]['total_experience_months'], 20)

  def test_dashboard_refuses_non_employers(self):
    response = self.client.get(reverse('company_dashboard'))

    self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

  # --- status changes land in the message thread ---

  def _unread(self, user):
    self.client.force_authenticate(user=user)
    return self.client.get(reverse('conversations_unread_count')).data

  def test_employer_status_change_messages_the_candidate(self):
    application_id = self._apply().data['id']

    self._set_status(application_id, 's', user=self.employer)

    conversation = Conversation.objects.get(job=self.job, candidate=self.candidate)
    messages = list(conversation.messages.all())
    self.assertEqual(len(messages), 1)
    self.assertEqual(messages[0].sender, self.employer)
    self.assertEqual(messages[0].body, 'Good news — your application for Chef has been shortlisted.')
    # The candidate is emailed the same text; the employer's internal note never is.
    self.assertEqual(len(mail.outbox), 1)
    self.assertEqual(mail.outbox[0].to, [self.candidate.email])
    self.assertIn(messages[0].body, mail.outbox[0].body)
    # The candidate's badge lights up; the employer's own message never counts for them.
    self.assertEqual(self._unread(self.candidate), {'unread_conversations': 1, 'unread_messages': 1})
    self.assertEqual(self._unread(self.employer), {'unread_conversations': 0, 'unread_messages': 0})

    # A second change appends to the SAME thread rather than forking one.
    self._set_status(application_id, 'i', user=self.employer)
    self.assertEqual(Conversation.objects.count(), 1)
    bodies = [m.body for m in conversation.messages.all()]
    self.assertEqual(bodies[-1], 'Your application for Chef has moved to the interview stage.')
    self.assertEqual(self._unread(self.candidate), {'unread_conversations': 1, 'unread_messages': 2})

  def test_note_only_and_noop_patches_send_no_message(self):
    application_id = self._apply().data['id']
    self._set_status(application_id, 's', user=self.employer, note='Strong CV')
    self._set_status(application_id, 's', user=self.employer, note='Second look')
    self._set_status(application_id, 's', user=self.employer)

    bodies = [m.body for m in Message.objects.all()]
    self.assertEqual(len(bodies), 1)
    # Internal notes never leave the server, least of all into the candidate's thread.
    self.assertNotIn('Strong CV', bodies[0])
    self.assertNotIn('Second look', bodies[0])

  def test_withdrawal_only_messages_an_existing_thread(self):
    application_id = self._apply().data['id']

    # No thread yet: withdrawing must not open one - candidates never start threads.
    self._set_status(application_id, 'w', user=self.candidate)
    self.assertEqual(Conversation.objects.count(), 0)

    # Re-apply (still no thread, still silent), get shortlisted (thread
    # created by the employer's change), then withdraw again.
    self.client.force_authenticate(user=self.candidate)
    self._apply()
    self.assertEqual(Conversation.objects.count(), 0)
    self._set_status(application_id, 's', user=self.employer)
    self._set_status(application_id, 'w', user=self.candidate)

    conversation = Conversation.objects.get(job=self.job, candidate=self.candidate)
    last = conversation.messages.last()
    self.assertEqual(last.sender, self.candidate)
    self.assertEqual(last.body, 'I’ve withdrawn my application for Chef.')
    self.assertEqual(self._unread(self.employer), {'unread_conversations': 1, 'unread_messages': 1})

    # Re-applying into the existing thread tells the employer too.
    self.client.force_authenticate(user=self.candidate)
    self.assertTrue(self._apply().data.get('reactivated'))
    self.assertEqual(conversation.messages.last().body, 'I’ve re-applied for Chef.')
    self.assertEqual(Conversation.objects.count(), 1)

  # --- throttling ---

  def test_applies_are_throttled_but_reads_are_not(self):
    from .views import PostScopedRateThrottle

    original_rates = PostScopedRateThrottle.THROTTLE_RATES
    PostScopedRateThrottle.THROTTLE_RATES = {'applications': '1/hour', 'messages': '30/min'}
    cache.clear()
    try:
      self.assertEqual(self._apply().status_code, status.HTTP_201_CREATED)
      self.assertEqual(self._apply(job=self.closed_job).status_code, status.HTTP_429_TOO_MANY_REQUESTS)
      self.assertEqual(self.client.get(reverse('applications')).status_code, status.HTTP_200_OK)
    finally:
      PostScopedRateThrottle.THROTTLE_RATES = original_rates
      cache.clear()


class InviteTests(APITestCase):
  """Inviting a candidate posts a company-voiced message into the (job,
  candidate) thread - exactly once per match row, however many times the
  button is pressed. No cache.clear() needed here: neither match_invite nor
  application_detail is throttled, and the append test creates its
  Application via the ORM rather than the throttled apply endpoint."""

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
    self.employer, self.company = self._employer('alpha')
    self.other_employer, self.other_company = self._employer('beta')

    self.job = Job.objects.create(company=self.company, title='Chef', description='Cook')
    self.closed_job = Job.objects.create(company=self.company, title='Old Chef', description='Cooked', status='h')

    self.candidate = self._candidate('invitee')
    self.match = Match.objects.create(user=self.candidate, job=self.job, score=77)

    self.client.force_authenticate(user=self.employer)

  def _invite(self, match, user=None):
    if user:
      self.client.force_authenticate(user=user)
    return self.client.patch(reverse('match_invite', args=[match.id]))

  def _unread(self, user):
    self.client.force_authenticate(user=user)
    return self.client.get(reverse('conversations_unread_count')).data

  def test_invite_flips_the_match_and_messages_the_candidate(self):
    response = self._invite(self.match)

    self.assertEqual(response.status_code, status.HTTP_200_OK)
    self.assertTrue(response.data['is_invited'])
    self.assertNotIn('already_invited', response.data)

    conversation = Conversation.objects.get(job=self.job, candidate=self.candidate)
    messages = list(conversation.messages.all())
    self.assertEqual(len(messages), 1)
    self.assertEqual(messages[0].sender, self.employer)
    self.assertEqual(
      messages[0].body,
      'You’ve been invited to apply for Chef. You’ll find it in the Invited tab of your matches.',
    )
    self.assertEqual(self._unread(self.candidate), {'unread_conversations': 1, 'unread_messages': 1})
    self.assertEqual(self._unread(self.employer), {'unread_conversations': 0, 'unread_messages': 0})
    # ...and the same message lands in their email inbox.
    self.assertEqual(len(mail.outbox), 1)
    self.assertEqual(mail.outbox[0].to, [self.candidate.email])
    self.assertIn(messages[0].body, mail.outbox[0].body)

    # Candidates see the company as the counterpart, never the employer user.
    self.client.force_authenticate(user=self.candidate)
    inbox = self.client.get(reverse('conversations')).data
    self.assertEqual(inbox['conversations'][0]['counterpart']['name'], 'alpha Ltd')

  def test_re_invite_is_idempotent(self):
    self._invite(self.match)
    response = self._invite(self.match)

    self.assertEqual(response.status_code, status.HTTP_200_OK)
    self.assertTrue(response.data['already_invited'])
    self.assertTrue(response.data['is_invited'])
    self.assertEqual(Message.objects.count(), 1)
    self.assertEqual(Conversation.objects.count(), 1)
    self.assertEqual(self._unread(self.candidate), {'unread_conversations': 1, 'unread_messages': 1})

  def test_only_the_job_owner_can_invite(self):
    self.assertEqual(self._invite(self.match, user=self.other_employer).status_code, status.HTTP_403_FORBIDDEN)
    self.assertEqual(self._invite(self.match, user=self.candidate).status_code, status.HTTP_403_FORBIDDEN)
    self.client.force_authenticate(user=self.employer)
    self.assertEqual(self.client.patch(reverse('match_invite', args=[9999])).status_code, status.HTTP_404_NOT_FOUND)

    self.match.refresh_from_db()
    self.assertFalse(self.match.is_invited)
    self.assertEqual(Conversation.objects.count(), 0)

  def test_invite_after_status_change_appends_to_the_existing_thread(self):
    application = Application.objects.create(user=self.candidate, job=self.job)
    self.client.patch(reverse('application_detail', args=[application.id]), {'status': 's'}, format='json')
    self.assertEqual(Conversation.objects.count(), 1)

    self._invite(self.match)

    conversation = Conversation.objects.get(job=self.job, candidate=self.candidate)
    bodies = [m.body for m in conversation.messages.all()]
    self.assertEqual(len(bodies), 2)
    # They already applied, so the role isn't in their deck - no tab pointer.
    self.assertEqual(bodies[-1], 'You’ve been invited to apply for Chef.')
    self.assertEqual(Conversation.objects.count(), 1)
    self.assertEqual(self._unread(self.candidate), {'unread_conversations': 1, 'unread_messages': 2})

  def test_invite_on_a_closed_job_does_not_promise_the_deck(self):
    match = Match.objects.create(user=self.candidate, job=self.closed_job, score=50)

    self.assertEqual(self._invite(match).status_code, status.HTTP_200_OK)
    conversation = Conversation.objects.get(job=self.closed_job, candidate=self.candidate)
    self.assertEqual(conversation.messages.first().body, 'You’ve been invited to apply for Old Chef.')

  def test_invited_candidate_can_reply(self):
    self._invite(self.match)
    conversation = Conversation.objects.get(job=self.job, candidate=self.candidate)

    # Born with the invite message, so the "employer messaged first" invariant
    # that lets candidates reply holds for invite-created threads too.
    self.client.force_authenticate(user=self.candidate)
    reply = self.client.post(
      reverse('conversation_messages', args=[conversation.id]), {'body': 'Thanks — keen to talk'}, format='json',
    )
    self.assertEqual(reply.status_code, status.HTTP_201_CREATED)


class MessagingTests(APITestCase):
  """An employer may only open a thread about a job with a candidate they invited
  to it or who applied to it; candidates can only ever reply. Threads are created
  together with their first message, so a thread existing IS the proof the
  candidate has already been messaged."""

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
    self.job_a2 = Job.objects.create(company=self.company_a, title='Waiter', description='Serve')
    self.job_b = Job.objects.create(company=self.company_b, title='Barista', description='Pour')

    self.invited = self._candidate('invited')
    Match.objects.create(user=self.invited, job=self.job_a, is_invited=True, score=80)
    self.applicant = self._candidate('applicant')
    Application.objects.create(user=self.applicant, job=self.job_a)
    self.matched = self._candidate('matched')
    Match.objects.create(user=self.matched, job=self.job_a, score=60)
    self.stranger = self._candidate('stranger')

    self.client.force_authenticate(user=self.employer_a)

  def _start(self, candidate, job, body='Hello there'):
    return self.client.post(
      reverse('conversations'), {'candidate': candidate.id, 'job': job.id, 'body': body}, format='json',
    )

  def _send(self, conversation_id, body='Follow-up'):
    return self.client.post(
      reverse('conversation_messages', args=[conversation_id]), {'body': body}, format='json',
    )

  def _thread(self, conversation_id, **params):
    return self.client.get(reverse('conversation_details', args=[conversation_id]), params)

  def _inbox(self, user=None):
    if user:
      self.client.force_authenticate(user=user)
    return self.client.get(reverse('conversations'))

  def _unread(self, user):
    self.client.force_authenticate(user=user)
    return self.client.get(reverse('conversations_unread_count')).data

  # --- the gate ---

  def test_invited_candidate_can_be_messaged(self):
    response = self._start(self.invited, self.job_a)

    self.assertEqual(response.status_code, status.HTTP_201_CREATED)
    self.assertEqual(response.data['conversation']['job']['id'], self.job_a.id)
    self.assertEqual(response.data['conversation']['counterpart']['id'], self.invited.id)
    self.assertEqual([m['body'] for m in response.data['messages']], ['Hello there'])
    self.assertTrue(Conversation.objects.filter(job=self.job_a, candidate=self.invited).exists())

  def test_applicant_can_be_messaged(self):
    self.assertEqual(self._start(self.applicant, self.job_a).status_code, status.HTTP_201_CREATED)

  def test_match_without_invite_is_not_enough(self):
    response = self._start(self.matched, self.job_a)

    self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
    self.assertEqual(Conversation.objects.count(), 0)

  def test_shortlisting_alone_is_not_enough(self):
    SavedCandidate.objects.create(company=self.company_a, user=self.stranger)

    self.assertEqual(self._start(self.stranger, self.job_a).status_code, status.HTTP_403_FORBIDDEN)

  def test_application_does_not_open_other_jobs(self):
    # The applicant applied to job_a only - job_a2 stays closed until they are
    # invited to it or apply there.
    self.assertEqual(self._start(self.applicant, self.job_a2).status_code, status.HTTP_403_FORBIDDEN)

  def test_cannot_message_about_another_companys_job(self):
    Match.objects.create(user=self.invited, job=self.job_b, is_invited=True)

    self.assertEqual(self._start(self.invited, self.job_b).status_code, status.HTTP_403_FORBIDDEN)

  def test_candidate_cannot_start_a_conversation(self):
    self.client.force_authenticate(user=self.invited)

    self.assertEqual(self._start(self.invited, self.job_a).status_code, status.HTTP_403_FORBIDDEN)
    self.assertEqual(Conversation.objects.count(), 0)

  # --- thread mechanics ---

  def test_starting_twice_appends_to_one_thread(self):
    first = self._start(self.invited, self.job_a)
    second = self._start(self.invited, self.job_a, body='Just checking in')

    self.assertEqual(first.status_code, status.HTTP_201_CREATED)
    self.assertEqual(second.status_code, status.HTTP_200_OK)
    self.assertEqual(first.data['conversation']['id'], second.data['conversation']['id'])
    self.assertEqual(Conversation.objects.count(), 1)
    self.assertEqual([m['body'] for m in second.data['messages']], ['Hello there', 'Just checking in'])

  def test_candidate_can_reply_once_messaged(self):
    conversation_id = self._start(self.invited, self.job_a).data['conversation']['id']

    self.client.force_authenticate(user=self.invited)
    reply = self._send(conversation_id, body='Thanks, keen to talk')
    self.assertEqual(reply.status_code, status.HTTP_201_CREATED)

    thread = self._thread(conversation_id)
    self.assertEqual(thread.status_code, status.HTTP_200_OK)
    self.assertEqual(thread.data['me'], self.invited.id)
    # The candidate sees the company as the counterpart, never the employer user.
    self.assertEqual(thread.data['conversation']['counterpart']['name'], 'alpha Ltd')
    self.assertEqual([m['body'] for m in thread.data['messages']], ['Hello there', 'Thanks, keen to talk'])

  def test_non_participants_cannot_read_or_write(self):
    conversation_id = self._start(self.invited, self.job_a).data['conversation']['id']

    self.client.force_authenticate(user=self.employer_b)
    self.assertEqual(self._thread(conversation_id).status_code, status.HTTP_404_NOT_FOUND)
    self.assertEqual(self._send(conversation_id).status_code, status.HTTP_404_NOT_FOUND)

    self.client.force_authenticate(user=self.matched)
    self.assertEqual(self._thread(conversation_id).status_code, status.HTTP_404_NOT_FOUND)
    self.assertEqual(self._send(conversation_id).status_code, status.HTTP_404_NOT_FOUND)
    self.assertEqual(Message.objects.count(), 1)

  def test_message_body_is_validated(self):
    self.assertEqual(self._start(self.invited, self.job_a, body='').status_code, status.HTTP_400_BAD_REQUEST)
    self.assertEqual(self._start(self.invited, self.job_a, body='   ').status_code, status.HTTP_400_BAD_REQUEST)
    self.assertEqual(self._start(self.invited, self.job_a, body='x' * 4001).status_code, status.HTTP_400_BAD_REQUEST)
    missing_ids = self.client.post(reverse('conversations'), {'body': 'hi'}, format='json')
    self.assertEqual(missing_ids.status_code, status.HTTP_400_BAD_REQUEST)
    self.assertEqual(Conversation.objects.count(), 0)

    conversation_id = self._start(self.invited, self.job_a).data['conversation']['id']
    self.assertEqual(self._send(conversation_id, body='  ').status_code, status.HTTP_400_BAD_REQUEST)
    self.assertEqual(Message.objects.count(), 1)

  # --- read state ---

  def test_read_cursors_and_unread_counts(self):
    conversation_id = self._start(self.invited, self.job_a).data['conversation']['id']

    self.assertEqual(self._unread(self.invited), {'unread_conversations': 1, 'unread_messages': 1})
    self.assertEqual(self._unread(self.employer_a), {'unread_conversations': 0, 'unread_messages': 0})

    # A peek fetch (the inbox auto-opening its newest thread) must NOT advance
    # the read cursor - the peeked pane may be hidden on the reader's viewport.
    self.client.force_authenticate(user=self.invited)
    self.assertEqual(self._thread(conversation_id, peek=1).status_code, status.HTTP_200_OK)
    self.assertEqual(self._unread(self.invited), {'unread_conversations': 1, 'unread_messages': 1})

    # Opening the thread advances the candidate's read cursor.
    self.client.force_authenticate(user=self.invited)
    self._thread(conversation_id)
    self.assertEqual(self._unread(self.invited), {'unread_conversations': 0, 'unread_messages': 0})

    self.client.force_authenticate(user=self.invited)
    self._send(conversation_id, body='Reply one')
    self._send(conversation_id, body='Reply two')
    self.assertEqual(self._unread(self.employer_a), {'unread_conversations': 1, 'unread_messages': 2})

    self.client.force_authenticate(user=self.employer_a)
    self._thread(conversation_id)
    self.assertEqual(self._unread(self.employer_a), {'unread_conversations': 0, 'unread_messages': 0})

  def test_after_returns_only_new_messages(self):
    started = self._start(self.invited, self.job_a)
    conversation_id = started.data['conversation']['id']
    first_id = started.data['messages'][0]['id']

    self.client.force_authenticate(user=self.invited)
    self._send(conversation_id, body='Newer')

    self.client.force_authenticate(user=self.employer_a)
    delta = self._thread(conversation_id, after=first_id)
    self.assertEqual([m['body'] for m in delta.data['messages']], ['Newer'])

    self.assertEqual(self._thread(conversation_id, after='abc').status_code, status.HTTP_400_BAD_REQUEST)

  # --- inbox ---

  def test_inbox_orders_by_latest_activity_with_counterparts(self):
    first_id = self._start(self.invited, self.job_a).data['conversation']['id']
    self._start(self.applicant, self.job_a, body='About your application')
    # New activity moves the older thread back to the top.
    self._send(first_id, body='Bumping this')

    inbox = self._inbox().data
    self.assertEqual(inbox['me'], self.employer_a.id)
    self.assertEqual([c['id'] for c in inbox['conversations']][0], first_id)
    top = inbox['conversations'][0]
    self.assertEqual(top['counterpart']['name'], 'invited Candidate')
    self.assertEqual(top['last_message']['body'], 'Bumping this')
    self.assertEqual(top['unread_count'], 0)

    candidate_inbox = self._inbox(user=self.invited).data
    self.assertEqual(len(candidate_inbox['conversations']), 1)
    self.assertEqual(candidate_inbox['conversations'][0]['counterpart']['name'], 'alpha Ltd')
    self.assertEqual(candidate_inbox['conversations'][0]['unread_count'], 2)

  def test_inbox_query_count_does_not_grow_with_conversations(self):
    self._start(self.invited, self.job_a)

    with CaptureQueriesContext(connection) as baseline:
      self._inbox()

    self._start(self.applicant, self.job_a)
    for i in range(3):
      extra = self._candidate(f'extra{i}')
      Match.objects.create(user=extra, job=self.job_a2, is_invited=True)
      conversation_id = self._start(extra, self.job_a2).data['conversation']['id']
      self._send(conversation_id, body=f'More for {i}')

    with CaptureQueriesContext(connection) as grown:
      self._inbox()

    self.assertEqual(len(baseline.captured_queries), len(grown.captured_queries))

  # --- email notifications ---

  @override_settings(FRONTEND_URL='http://testserver')
  def test_opening_a_thread_emails_the_candidate(self):
    response = self._start(self.invited, self.job_a, body='Fancy a chat?')

    self.assertEqual(response.status_code, status.HTTP_201_CREATED)
    conversation_id = response.data['conversation']['id']
    self.assertEqual(len(mail.outbox), 1)
    email = mail.outbox[0]
    self.assertEqual(email.to, [self.invited.email])
    self.assertEqual(email.subject, 'New message from alpha Ltd about Chef')
    self.assertIn('Hi invited,', email.body)
    self.assertIn('alpha Ltd sent you a message about Chef:', email.body)
    self.assertIn('Fancy a chat?', email.body)
    self.assertIn(f'http://testserver/candidate/messages/{conversation_id}', email.body)

  def test_employer_reply_emails_the_candidate_but_candidate_reply_does_not(self):
    conversation_id = self._start(self.invited, self.job_a).data['conversation']['id']
    self.assertEqual(len(mail.outbox), 1)

    self.assertEqual(self._send(conversation_id, body='Still keen?').status_code, status.HTTP_201_CREATED)
    self.assertEqual(len(mail.outbox), 2)
    self.assertEqual(mail.outbox[1].to, [self.invited.email])
    self.assertIn('Still keen?', mail.outbox[1].body)

    self.client.force_authenticate(user=self.invited)
    self.assertEqual(self._send(conversation_id, body='Yes!').status_code, status.HTTP_201_CREATED)
    # The candidate is the sender: nobody gets emailed their own reply, and the
    # employer side has no email notifications at all.
    self.assertEqual(len(mail.outbox), 2)

  def test_branch_name_is_used_when_the_job_has_a_branch(self):
    branch = CompanyBranch.objects.create(
      company=self.company_a, name='alpha Soho', photo='https://img/soho.png',
      address='2 Street', postcode='W1', city='Soho', state='London', country='UK',
    )
    self.job_a.branch = branch
    self.job_a.save(update_fields=['branch'])

    conversation_id = self._start(self.invited, self.job_a).data['conversation']['id']

    self.assertEqual(mail.outbox[0].subject, 'New message from alpha Soho about Chef')
    self.assertIn('alpha Soho sent you a message about Chef:', mail.outbox[0].body)

    # The candidate's view of the thread and inbox is the branch too - but the
    # company id/name travel alongside so "all jobs by this company" still works.
    self.client.force_authenticate(user=self.invited)
    counterpart = self._thread(conversation_id).data['conversation']['counterpart']
    self.assertEqual(counterpart, {
      'id': self.company_a.id, 'name': 'alpha Soho', 'photo': 'https://img/soho.png',
      'subtitle': 'Soho', 'company_name': 'alpha Ltd',
    })
    inbox = self._inbox().data['conversations']
    self.assertEqual(inbox[0]['counterpart']['name'], 'alpha Soho')

    # A job without a branch keeps showing the company.
    self.client.force_authenticate(user=self.employer_a)
    Match.objects.create(user=self.invited, job=self.job_a2, is_invited=True, score=50)
    other_id = self._start(self.invited, self.job_a2).data['conversation']['id']
    self.assertEqual(mail.outbox[1].subject, 'New message from alpha Ltd about Waiter')
    self.client.force_authenticate(user=self.invited)
    counterpart = self._thread(other_id).data['conversation']['counterpart']
    self.assertEqual(counterpart['name'], 'alpha Ltd')
    self.assertEqual(counterpart['company_name'], 'alpha Ltd')

  def test_email_failure_does_not_break_the_send(self):
    with mock.patch('backend.emails.EmailMultiAlternatives.send', side_effect=RuntimeError('SES down')):
      with self.assertLogs('backend.emails', level='ERROR'):
        response = self._start(self.invited, self.job_a, body='Hello?')

    self.assertEqual(response.status_code, status.HTTP_201_CREATED)
    self.assertEqual(Message.objects.filter(conversation_id=response.data['conversation']['id']).count(), 1)

  # --- throttling ---

  def test_sends_are_throttled_but_reads_are_not(self):
    from .views import PostScopedRateThrottle

    original_rates = PostScopedRateThrottle.THROTTLE_RATES
    PostScopedRateThrottle.THROTTLE_RATES = {'messages': '2/min'}
    cache.clear()
    try:
      conversation_id = self._start(self.invited, self.job_a).data['conversation']['id']
      self.assertEqual(self._send(conversation_id).status_code, status.HTTP_201_CREATED)
      # Third write inside the window is refused...
      self.assertEqual(self._send(conversation_id).status_code, status.HTTP_429_TOO_MANY_REQUESTS)
      # ...while reads (inbox and the polling thread view) sail through.
      self.assertEqual(self._inbox().status_code, status.HTTP_200_OK)
      self.assertEqual(self._thread(conversation_id).status_code, status.HTTP_200_OK)
    finally:
      PostScopedRateThrottle.THROTTLE_RATES = original_rates
      cache.clear()
