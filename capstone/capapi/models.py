from datetime import timedelta
import uuid
import logging

import email_normalize
from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, AnonymousUser
from django.core.exceptions import PermissionDenied, ObjectDoesNotExist
from django.db import models, IntegrityError, transaction
from django.utils import timezone
from django.conf import settings
from capapi.permissions import staff_level_permissions

from model_utils import FieldTracker

from rest_framework.authtoken.models import Token

logger = logging.getLogger(__name__)


class CapUserManager(BaseUserManager):
    def create_user(self, email, password, **kwargs):
        if not email:
            raise ValueError('Email address is required')

        user = self.model(email=self.normalize_email(email), **kwargs)
        user.set_password(password)
        user.create_nonce()
        user.save(using=self._db)
        return user

    def create_superuser(self, email, password, **kwargs):
        kwargs.setdefault('is_staff', True)
        kwargs.setdefault('is_superuser', True)
        kwargs.setdefault('email_verified', True)
        kwargs.setdefault('total_case_allowance', settings.API_CASE_DAILY_ALLOWANCE)
        kwargs.setdefault('case_allowance_remaining', settings.API_CASE_DAILY_ALLOWANCE)

        if kwargs.get('is_staff') is not True:
            raise ValueError('Superuser must have is_staff=True.')
        if kwargs.get('is_superuser') is not True:
            raise ValueError('Superuser must have is_superuser=True.')

        return self.create_user(email=email, password=password, **kwargs)


class CapUser(AbstractBaseUser):
    email = models.EmailField(
        max_length=254,
        unique=True,
        db_index=True,
        error_messages={'unique': "A user with that email address already exists."}
    )
    normalized_email = models.CharField(max_length=255, help_text="Used to ensure that new emails are unique.")

    first_name = models.CharField(max_length=30)
    last_name = models.CharField(max_length=30)
    total_case_allowance = models.IntegerField(null=True, blank=True, default=0)
    case_allowance_remaining = models.IntegerField(null=False, blank=False, default=0)
    # when we last reset the user's case count:
    case_allowance_last_updated = models.DateTimeField(auto_now_add=True)
    unlimited_access_until = models.DateTimeField(null=True, blank=True)
    is_staff = models.BooleanField(default=False)
    is_superuser = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)

    email_verified = models.BooleanField(default=False, help_text="Whether user has verified their email address")
    activation_nonce = models.CharField(max_length=40, null=True, blank=True)
    nonce_expires = models.DateTimeField(null=True, blank=True)

    date_joined = models.DateTimeField(auto_now_add=True)
    agreed_to_tos = models.BooleanField(default=False)

    USERNAME_FIELD = 'email'

    objects = CapUserManager()
    tracker = FieldTracker()

    class Meta:
        verbose_name = 'User'

    def get_activation_nonce(self):
        if self.nonce_expires + timedelta(hours=24) < timezone.now():
            self.create_nonce()
            self.save()
        return self.activation_nonce

    def unlimited_access_in_effect(self):
        if not self.unlimited_access_until:
            return False
        return self.unlimited_access_until > timezone.now()

    def update_case_allowance(self, case_count=0, save=True):
        if self.unlimited_access_in_effect():
            return

        if self.case_allowance_last_updated + timedelta(hours=settings.API_CASE_EXPIRE_HOURS) < timezone.now():
            self.case_allowance_remaining = self.total_case_allowance
            self.case_allowance_last_updated = timezone.now()

        if case_count:
            if self.case_allowance_remaining < case_count:
                raise AttributeError("Case allowance is too low.")
            self.case_allowance_remaining -= case_count

        if save:
            self.save(update_fields=['case_allowance_remaining', 'case_allowance_last_updated'])

    def authenticate_user(self, activation_nonce):
        if self.activation_nonce == activation_nonce and self.nonce_expires + timedelta(hours=24) > timezone.now():
            Token.objects.create(user=self)
            self.activation_nonce = ''
            self.email_verified = True
            self.save()
        else:
            raise PermissionDenied

    def create_nonce(self):
        self.activation_nonce = self.generate_nonce_timestamp()
        self.nonce_expires = timezone.now()
        self.save()

    def save(self, *args, **kwargs):
        if self.tracker.has_changed('email'):
            self.normalized_email = self.normalize_email(self.email)
        super(CapUser, self).save(*args, **kwargs)

    @staticmethod
    def generate_nonce_timestamp():
        nonce = uuid.uuid1()
        return nonce.hex

    def get_api_key(self):
        try:
            # relying on DRF's Token model
            return self.auth_token.key
        except ObjectDoesNotExist:
            return None

    def get_short_name(self):
        return self.email.split('@')[0]

    def case_download_allowed(self, case_count):
        if case_count > 0:
            self.update_case_allowance()
            return self.case_allowance_remaining >= case_count
        else:
            return True

    def has_module_perms(self, app_label):
        if app_label == 'capapi' or app_label == 'capdb':
            return self.is_staff

        return self.is_superuser

    def has_perm(self, perm, obj=None):
        if perm in staff_level_permissions:
            return self.is_staff
        return self.is_superuser

    @staticmethod
    def normalize_email(email):
        """
            Return a normalized form of the email address:
            - lowercase
            - applying host-specific rules for domains hosted by Google, Microsoft, Yahoo, Fastmail
        """
        return email_normalize.normalize(email.strip(), resolve=False)


# make AnonymousUser API conform with CapUser API
AnonymousUser.unlimited_access_until = None
AnonymousUser.unlimited_access_in_effect = lambda self: False


class ResearchRequest(models.Model):
    user = models.ForeignKey(CapUser, on_delete=models.CASCADE, related_name='research_requests')
    submitted_date = models.DateTimeField(auto_now_add=True)

    name = models.CharField(max_length=255)
    email = models.EmailField(max_length=255)
    institution = models.CharField(max_length=255)
    title = models.CharField(max_length=255)
    area_of_interest = models.TextField(blank=True, null=True)

    status = models.CharField(max_length=20, default='pending', choices=(('pending', 'pending'), ('approved', 'approved'), ('denied', 'denied'), ('awaiting signature', 'awaiting signature')))
    notes = models.TextField(blank=True, null=True)

    class Meta:
        ordering = ['-submitted_date']


class SiteLimits(models.Model):
    """
        Singleton model to track sitewide values in a row with ID=1
    """
    daily_signup_limit = models.IntegerField(default=50)
    daily_signups = models.IntegerField(default=0)
    daily_download_limit = models.IntegerField(default=50000)
    daily_downloads = models.IntegerField(default=0)

    @classmethod
    def create(cls):
        """ Create and return the ID=1 row, or fetch the existing one. """
        site_limits = cls(pk=1)
        try:
            site_limits.save()
        except IntegrityError:
            return cls.objects.get(pk=1)
        else:
            return site_limits

    @classmethod
    def get(cls):
        """ Get the ID=1 row, creating if necessary. """
        try:
            return cls.objects.get(pk=1)
        except cls.DoesNotExist:
            return cls.create()

    @classmethod
    def get_for_update(cls):
        """
            Get the ID=1 row with select_for_update()
            This must be run from within a transaction.
        """
        try:
            site_limits = cls.objects.select_for_update().get(pk=1)
        except cls.DoesNotExist:
            cls.create()
            site_limits = cls.objects.select_for_update().get(pk=1)
        return site_limits

    @classmethod
    def add_values(cls, **pairs):
        """
            Modify existing values.
            E.g., SiteLimits.add_values(daily_downloads=1) increases daily_downloads by 1.
        """
        with transaction.atomic():
            site_limits = cls.get_for_update()
            for k, v in pairs.items():
                setattr(site_limits, k, getattr(site_limits, k) + v)
            site_limits.save()
        return site_limits

    @classmethod
    def reset(cls):
        """ Reset all counters to 0. """
        with transaction.atomic():
            site_limits = cls.get_for_update()
            site_limits.daily_signups = 0
            site_limits.daily_downloads = 0
            site_limits.save()