from django.db import models
from django.contrib.auth import get_user_model
from django.contrib.auth.models import AbstractBaseUser, PermissionsMixin, BaseUserManager

PAY_RANGE_OPTIONS = (
  ('pay20_30', '20,000 - 30,000'),
  ('pay30_35', '30,000 - 35,000'),
  ('pay35_40', '35,000 - 40,000'),
  ('pay40_50', '40,000 - 50,000'),
  ('pay50plus', 'more than 50,000'),
)

JOB_STATUSES = (
  ('a', 'Active'),
  ('h', 'Hired'),
  ('e', 'Expired'),
)

APPLICATION_STATUSES = (
  ('a', 'Applied'),
  ('s', 'Selected'),
  ('i', 'Interview'),
  ('t', 'Trial'),
  ('h', 'Hired'),
  ('r', 'Rejected'),
  )

COMPANY_TYPES = (
  ('restaurant', 'Restaurant'),
  ('hotel', 'Hotel'),
)

COMPANY_SIZES = (
  ('small', 'up to 100 employees'),
  ('medium', 'from 100 to 1000 employees'),
  ('large', 'more than 1000 employees'),
)

ATTACHMENT_OPTIONS = (
  ('file', 'File'),
  ('url', 'URL'),
)

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
  
class Company(models.Model):
  user = models.ForeignKey(get_user_model(), on_delete=models.CASCADE)
  name = models.CharField(max_length=100)
  legal_name = models.CharField(max_length=100, blank=True)
  email = models.EmailField(max_length=254)
  photo = models.CharField(max_length=500, blank=True)
  type = models.CharField(
    max_length=30,
    choices=COMPANY_TYPES,
    default='restaurant'
    )
  size = models.CharField(
    max_length=6,
    choices=COMPANY_SIZES,
    default='small'
    )
  phone_number = models.CharField(max_length=30)
  website = models.CharField(max_length=100, blank=True)
  address = models.CharField(max_length=300)
  postcode = models.CharField(max_length=20)
  city = models.CharField(max_length=100)
  state = models.CharField(max_length=100)
  country = models.CharField(max_length=100)
  created_at = models.DateTimeField(auto_now_add=True)
  updated_at = models.DateTimeField(auto_now=True)

  def __str__(self):
    return self.name

class Job(models.Model):
  company = models.ForeignKey(Company, on_delete=models.CASCADE, null=True)
  title = models.CharField(max_length=100)
  description = models.TextField()
  job_type = models.CharField(max_length=200, null=True)
  pay = models.CharField(max_length=200, null=True)
  pay_range = models.CharField(
    max_length=20,
    choices=PAY_RANGE_OPTIONS,
    default='pay20_30'
    )
  status = models.CharField(
    max_length=1,
    choices=JOB_STATUSES,
    default='a'
    )
  contact = models.CharField(max_length=100, null=True)
  created_at = models.DateTimeField(auto_now_add=True)
  updated_at = models.DateTimeField(auto_now=True)
  

  def __str__(self):
    return self.title

def get_company_name():
  return Company.objects.get('name')

class WorkExperience(models.Model):
  user = models.ForeignKey(get_user_model(), on_delete=models.CASCADE)
  company = models.ForeignKey(Company, on_delete=models.SET(get_company_name), blank=True, null=True, default=None)
  job_title = models.CharField(max_length=100)
  description = models.TextField()
  company_name = models.CharField(max_length=100, blank=True, null=True, default=None)
  company_address = models.CharField(max_length=300, blank=True, null=True, default=None)
  company_website = models.CharField(max_length=100, blank=True, null=True, default=None)
  start_date = models.DateField()
  end_date = models.DateField(blank=True, null=True, default=None)
  created_at = models.DateTimeField(auto_now_add=True)
  updated_at = models.DateTimeField(auto_now=True)

class Skill(models.Model):
  work_experience = models.ManyToManyField(WorkExperience)
  name = models.CharField(max_length=100)
  created_at = models.DateTimeField(auto_now_add=True)
  updated_at = models.DateTimeField(auto_now=True)

class Preference(models.Model):
  user = models.OneToOneField(get_user_model(), on_delete=models.CASCADE)
  job_type = models.CharField(max_length=200, null=True)
  company_type = models.CharField(
    max_length=30,
    choices=COMPANY_TYPES,
    default='restaurant'
    )
  company_size = models.CharField(
    max_length=6,
    choices=COMPANY_SIZES,
    default='small'
    )
  pay_range = models.CharField(
    max_length=20,
    choices=PAY_RANGE_OPTIONS,
    default='pay20_30'
    )
  created_at = models.DateTimeField(auto_now_add=True)
  updated_at = models.DateTimeField(auto_now=True)

class SavedJob(models.Model):
  user = models.ForeignKey(get_user_model(), on_delete=models.CASCADE)
  job = models.ForeignKey(Job, on_delete=models.CASCADE)

class SavedCandidate(models.Model):
  company = models.ForeignKey(Company, on_delete=models.CASCADE)
  job = models.ForeignKey(Job, on_delete=models.CASCADE, blank=True, null=True)
  user = models.ForeignKey(get_user_model(), on_delete=models.CASCADE)

class Match(models.Model):
  user = models.ForeignKey(get_user_model(), on_delete=models.CASCADE)
  job = models.ForeignKey(Job, on_delete=models.CASCADE)
  is_invited = models.BooleanField(default=False)
  created_at = models.DateTimeField(auto_now_add=True)
  updated_at = models.DateTimeField(auto_now=True)

class Application(models.Model):
  user = models.ForeignKey(get_user_model(), on_delete=models.CASCADE)
  job = models.ForeignKey(Job, on_delete=models.CASCADE)
  status = models.CharField(
    max_length=1,
    choices=APPLICATION_STATUSES,
    default='a'
    )
  created_at = models.DateTimeField(auto_now_add=True)
  updated_at = models.DateTimeField(auto_now=True)

class ApplicationQuestion(models.Model):
  application = models.ForeignKey(Application, on_delete=models.CASCADE)
  question = models.CharField(max_length=200)

class ApplicationAnswer(models.Model):
  application_question = models.OneToOneField(ApplicationQuestion, on_delete=models.CASCADE)
  answer = models.CharField(max_length=300)

class AttachmentRequirement(models.Model):
  application = models.ForeignKey(Application, on_delete=models.CASCADE)
  requirement = models.CharField(max_length=200)
  attachment_type = models.CharField(
    max_length=5,
    choices=ATTACHMENT_OPTIONS,
    default='file'
    )

class AttachmentAnswer(models.Model):
  attachment_requirement = models.OneToOneField(AttachmentRequirement, on_delete=models.CASCADE)
  attachment = models.CharField(max_length=200)

class Conversation(models.Model):
  creator = models.ForeignKey(get_user_model(), related_name='creator', on_delete=models.CASCADE)
  recipient = models.ForeignKey(get_user_model(), related_name='recipient', on_delete=models.CASCADE)
  job = models.ForeignKey(Job, on_delete=models.CASCADE)
  created_at = models.DateTimeField(auto_now_add=True)

class Message(models.Model):
  conversation = models.ForeignKey(Conversation, on_delete=models.CASCADE)
  sender = models.ForeignKey(get_user_model(), on_delete=models.CASCADE)
  message = models.TextField(blank=True, null=True)
  created_at = models.DateTimeField(auto_now_add=True)
  updated_at = models.DateTimeField(auto_now=True)

class MessageFile(models.Model):
  message = models.ForeignKey(Message, on_delete=models.CASCADE)
  file_link = models.CharField(max_length=500)