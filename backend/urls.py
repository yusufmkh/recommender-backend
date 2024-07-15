"""
URL configuration for recommenderbackend project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/4.2/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.urls import path
from rest_framework.urlpatterns import format_suffix_patterns

from backend import views

from rest_framework_simplejwt.views import (
    TokenObtainPairView,
    TokenRefreshView,
)

urlpatterns = [
    path("admin/", admin.site.urls),
    path('api/token/', TokenObtainPairView.as_view(), name='token_obtain_pair'),
    path('api/token/refresh/', TokenRefreshView.as_view(), name='token_refresh'),
    path("api/user_register/", views.user_register, name="user_register"),
    path("api/user_dashboard/", views.user_dashboard, name="user_dashboard"),
    path("api/user_work_experiences/", views.user_work_experiences, name="user_work_experiences"),
    path("api/user_skills/", views.user_skills),
    path("api/user_preferences/", views.user_preferences, name="user_preferences"),
    path("api/company_register/", views.company_register, name="company_register"),
    path("api/company_dashboard/", views.company_dashboard, name="company_dashboard"),
    path("api/jobs/", views.jobs, name="jobs"),
    path("api/jobs/<int:id>", views.job_details, name="job"),
    path("api/saved_jobs/", views.saved_jobs, name="saved_jobs"),
    path("api/saved_candidates/company/<int:company_id>", views.saved_candidates, name="saved_candidates"),
    path("api/applications/", views.job_applications, name="applications"),
]

urlpatterns = format_suffix_patterns(urlpatterns)