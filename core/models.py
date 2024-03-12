from django.db import models
from django.contrib.auth.models import AbstractBaseUser, PermissionsMixin, BaseUserManager

class MyUserManager(BaseUserManager):
  def create_user(self, email, user_name, first_name, last_name, password, **other_fields):
    if not email:
      raise ValueError('User must have an email address')
  
    email = self.normalize_email(email)
    user = self.model(email=email, user_name=user_name, first_name=first_name, last_name=last_name, **other_fields)
    user.set_password(password)
    user.save()

    return user
  
  def create_superuser(self, email, user_name, first_name, last_name, password, **other_fields):
    other_fields.setdefault('is_staff', True)
    other_fields.setdefault('is_superuser', True)
    other_fields.setdefault('is_active', True)

    return self.create_user(email, user_name, first_name, last_name, password, **other_fields)

class MyUser(AbstractBaseUser, PermissionsMixin):
  first_name = models.CharField(max_length=100)
  last_name = models.CharField(max_length=100)
  email = models.EmailField(max_length=300, unique=True)
  user_name = models.CharField(max_length=150, unique=True)
  photo = models.CharField(max_length=500, blank=True, null=True)
  phone_number = models.CharField(max_length=30, blank=True, null=True)
  dob = models.DateField(blank=True, null=True)
  address = models.CharField(max_length=300, blank=True, null=True)
  postcode = models.CharField(max_length=20, blank=True, null=True)
  city = models.CharField(max_length=100, blank=True, null=True)
  state = models.CharField(max_length=100, blank=True, null=True)
  country = models.CharField(max_length=100, blank=True, null=True)
  is_staff = models.BooleanField(default=False)
  is_active = models.BooleanField(default=False)
  created_at = models.DateTimeField(auto_now_add=True)
  updated_at = models.DateTimeField(auto_now=True)

  objects = MyUserManager()

  USERNAME_FIELD = 'email'
  REQUIRED_FIELDS = ['user_name', 'first_name', 'last_name']

  def __str__(self):
    return self.user_name