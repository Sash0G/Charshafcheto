from django.contrib.auth.models import AbstractUser, BaseUserManager
from django.db import models


class UserManager(BaseUserManager):
    use_in_migrations = True

    def _create_user(self, email, password, **extra):
        if not email:
            raise ValueError("Имейлът е задължителен.")
        email = self.normalize_email(email).lower()
        user = self.model(email=email, **extra)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_user(self, email, password=None, **extra):
        extra.setdefault("is_staff", False)
        extra.setdefault("is_superuser", False)
        return self._create_user(email, password, **extra)

    def create_superuser(self, email, password=None, **extra):
        extra.setdefault("is_staff", True)
        extra.setdefault("is_superuser", True)
        return self._create_user(email, password, **extra)


class User(AbstractUser):
    """Customers and staff share one model; customers log in with their email."""

    username = None
    email = models.EmailField("имейл", unique=True)
    phone = models.CharField("телефон", max_length=32, blank=True)
    marketing_consent = models.BooleanField("съгласие за маркетинг", default=False)
    email_verified = models.BooleanField("потвърден имейл", default=False)

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = []

    objects = UserManager()

    class Meta:
        verbose_name = "потребител"
        verbose_name_plural = "потребители"

    def __str__(self):
        return self.get_full_name() or self.email


class Address(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="addresses")
    label = models.CharField("етикет", max_length=60, default="Основен адрес")
    full_name = models.CharField("име и фамилия", max_length=120)
    phone = models.CharField("телефон", max_length=32)
    city = models.CharField("град", max_length=80)
    postcode = models.CharField("пощенски код", max_length=12, blank=True)
    line1 = models.CharField("адрес", max_length=200)
    is_default = models.BooleanField("основен", default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-is_default", "-created_at"]
        verbose_name = "адрес"
        verbose_name_plural = "адреси"

    def __str__(self):
        return f"{self.city}, {self.line1}"

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        if self.is_default:
            Address.objects.filter(user=self.user).exclude(pk=self.pk).update(is_default=False)
