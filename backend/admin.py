from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from .models import MyUser, Job, Company, CompanyBranch, WorkExperience, Skill, Preference, SavedJob, SavedCandidate, Match, Application, ApplicationEvent, ApplicationQuestion, ApplicationAnswer, AttachmentRequirement, AttachmentAnswer, Conversation, Message, MessageFile

class UserAdminConfig(UserAdmin):
  search_fields = ('email', 'user_name', 'first_name', 'last_name')
  ordering = ('-created_at',)
  list_display = ('email', 'user_name', 'first_name', 'last_name', 'role', 'is_staff', 'is_active')
  list_filter = ('role', 'is_staff', 'is_active')
  fieldsets = (
    (None, {'fields': ('email', 'user_name', 'password', 'first_name', 'last_name')}),
    ('Permissions', {'fields': ('role', 'is_staff', 'is_active')}),
    ('Personal', {'fields': ('photo', 'phone_number', 'dob', 'address', 'postcode', 'city', 'state', 'country')})
  )
  add_fieldsets = (
    (None, {
      'classes': ('wide',),
      'fields': ('email', 'user_name', 'password1', 'password2', 'role', 'is_staff', 'is_active', 'first_name', 'last_name', 'photo', 'phone_number', 'dob', 'address', 'postcode', 'city', 'state', 'country',)
    }),
  )

admin.site.register(MyUser, UserAdminConfig)
admin.site.register(Job)
admin.site.register(Company)
admin.site.register(CompanyBranch)
admin.site.register(WorkExperience)
admin.site.register(Skill)
admin.site.register(Preference)
admin.site.register(SavedJob)
admin.site.register(SavedCandidate)
admin.site.register(Match)
class ApplicationAdmin(admin.ModelAdmin):
  list_display = ('id', 'user', 'job', 'status', 'created_at', 'updated_at')
  list_filter = ('status',)
  search_fields = ('user__email', 'user__user_name', 'job__title')

class ApplicationEventAdmin(admin.ModelAdmin):
  list_display = ('id', 'application', 'actor', 'from_status', 'to_status', 'created_at')
  list_filter = ('to_status',)

admin.site.register(Application, ApplicationAdmin)
admin.site.register(ApplicationEvent, ApplicationEventAdmin)
admin.site.register(ApplicationQuestion)
admin.site.register(ApplicationAnswer)
admin.site.register(AttachmentRequirement)
admin.site.register(AttachmentAnswer)
admin.site.register(Conversation)
admin.site.register(Message)
admin.site.register(MessageFile)