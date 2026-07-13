from rest_framework import serializers
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer
from rest_framework_simplejwt.views import TokenObtainPairView

from .models import MyUser


class EmailAwareTokenObtainPairSerializer(TokenObtainPairSerializer):
  """Same as the default serializer, but distinguishes "correct password,
  unverified account" from "wrong email/password" so the frontend can point
  the user at the verification flow instead of a generic auth error."""

  def validate(self, attrs):
    email = attrs.get(self.username_field)
    password = attrs.get('password')
    user = MyUser.objects.filter(email__iexact=email).first()

    if user and not user.is_active and user.check_password(password):
      raise serializers.ValidationError({'detail': 'unverified', 'email': user.email})

    return super().validate(attrs)


class EmailAwareTokenObtainPairView(TokenObtainPairView):
  serializer_class = EmailAwareTokenObtainPairSerializer
