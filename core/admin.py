from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from .models import MyUser

class UserAdminConfig(UserAdmin):
  search_fields = ('email', 'user_name', 'first_name', 'last_name')
  ordering = ('-created_at',)
  list_display = ('email', 'user_name', 'first_name', 'last_name', 'is_staff', 'is_active')
  fieldsets = (
    (None, {'fields': ('email', 'user_name', 'password', 'first_name', 'last_name')}),
    ('Permissions', {'fields': ('is_staff', 'is_active')}),
    ('Personal', {'fields': ('photo', 'phone_number', 'dob', 'address', 'postcode', 'city', 'state', 'country')})
  )
  add_fieldsets = (
    (None, {
      'classes': ('wide',),
      'fields': ('email', 'user_name', 'password1', 'password2', 'is_staff', 'is_active', 'first_name', 'last_name', 'photo', 'phone_number', 'dob', 'address', 'postcode', 'city', 'state', 'country',)
    }),
  )

admin.site.register(MyUser, UserAdminConfig)