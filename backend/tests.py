from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase, APIClient

from .models import MyUser
from .serializers import MyUserSerializer

class CandidateTests(APITestCase):

  def setUp(self):
    email = 'test@test.com'
    password = 't1234567u'
    user = MyUser.objects.create(first_name='Test', last_name='One', email=email, user_name='testone')
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
