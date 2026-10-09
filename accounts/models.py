from django.contrib.auth.models import AbstractUser, UserManager as DjangoUserManager
from django.core.validators import RegexValidator
from django.db import IntegrityError, models, transaction
from django.utils.crypto import get_random_string
from django.utils.text import slugify


# ---------------------------------------------------------------
# Managers
# ---------------------------------------------------------------
class BusinessQuerySet(models.QuerySet):
    def for_user(self, user):
        if user.is_superuser:
            return self
        if user.business_id:
            return self.filter(pk=user.business_id)
        return self.none()


class BusinessManager(models.Manager.from_queryset(BusinessQuerySet)):
    pass


class UserQuerySet(models.QuerySet):
    def active(self):
        return self.filter(is_active=True, is_active_staff=True)

    def owners(self):
        return self.filter(role=User.Role.OWNER)

    def for_business(self, business):
        return self.filter(business=business)


class UserManager(DjangoUserManager.from_queryset(UserQuerySet)):
    def create_user(self, username, email=None, password=None, **extra_fields):
        extra_fields.setdefault("role", User.Role.SALESPERSON)
        extra_fields.setdefault("is_active_staff", True)
        return super().create_user(username, email, password, **extra_fields)


# ---------------------------------------------------------------
# Business (tenant root)
# ---------------------------------------------------------------
class Business(models.Model):
    name = models.CharField(max_length=200)
    slug = models.SlugField(unique=True, blank=True, max_length=220)
    owner = models.OneToOneField(
        "accounts.User",
        on_delete=models.PROTECT,
        related_name="owned_business",
        null=True, blank=True,
    )

    address = models.TextField(blank=True)
    phone1 = models.CharField(max_length=20, blank=True)
    phone2 = models.CharField(max_length=20, blank=True)
    email = models.EmailField(blank=True)
    logo = models.ImageField(upload_to="logos/", blank=True, null=True)

    tax_rate = models.DecimalField(
        max_digits=5, decimal_places=2, default=0,
        help_text="Percent, e.g. 7.50 for 7.5%",
    )
    currency = models.CharField(
        max_length=3, default="USD",
        validators=[RegexValidator(r"^[A-Z]{3}$", "Use ISO 4217, e.g. USD.")],
    )

    next_employee_number = models.PositiveIntegerField(default=1)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = BusinessManager()

    class Meta:
        verbose_name_plural = "Businesses"
        ordering = ["name"]

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = self._generate_unique_slug()
        super().save(*args, **kwargs)

    def _generate_unique_slug(self, max_attempts=20):
        base = slugify(self.name)[:200] or "business"
        for i in range(max_attempts):
            candidate = base if i == 0 else f"{base}-{i}"
            if not Business.objects.filter(slug=candidate).exists():
                return candidate
        raise IntegrityError("Could not generate a unique slug.")

    def allocate_employee_id(self) -> str:
        """Atomically reserve the next employee ID for this business."""
        with transaction.atomic():
            locked = Business.objects.select_for_update().get(pk=self.pk)
            num = locked.next_employee_number
            locked.next_employee_number = num + 1
            locked.save(update_fields=["next_employee_number"])
        return f"EMP-{num:05d}"


# ---------------------------------------------------------------
# User
# ---------------------------------------------------------------
class User(AbstractUser):
    class Role(models.TextChoices):
        OWNER = "owner", "Owner"
        MANAGER = "manager", "Manager"
        SALESPERSON = "salesperson", "Sales Person"

    business = models.ForeignKey(
        Business, on_delete=models.CASCADE,
        null=True, blank=True, related_name="users",
    )
    role = models.CharField(
        max_length=20, choices=Role.choices, default=Role.SALESPERSON,
    )
    employee_id = models.CharField(max_length=30, blank=True, null=True)
    hired_at = models.DateField(null=True, blank=True)

    address = models.TextField(blank=True)
    phone1 = models.CharField(max_length=20, blank=True)
    phone2 = models.CharField(max_length=20, blank=True)
    profile_picture = models.ImageField(
        upload_to="profiles/", blank=True, null=True,
    )

    is_active_staff = models.BooleanField(default=True)

    must_change_password = models.BooleanField(
        default=False,
        help_text="Force user to change password on next login.",
    )
    password_reset_by = models.ForeignKey(
        "self", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="password_resets_performed",
    )
    password_reset_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = UserManager()

    class Meta:
        ordering = ["first_name", "last_name", "username"]
        constraints = [
            models.UniqueConstraint(
                fields=["business", "employee_id"],
                condition=models.Q(employee_id__isnull=False),
                name="unique_employee_id_per_business",
            ),
        ]

    # ---- Role helpers ----
    @property
    def is_owner(self):
        return self.role == self.Role.OWNER

    @property
    def is_manager_or_above(self):
        return self.role in (self.Role.OWNER, self.Role.MANAGER)

    @property
    def is_manager(self):
        return self.is_manager_or_above

    @property
    def is_salesperson(self):
        return self.role == self.Role.SALESPERSON

    # ---- Persistence ----
    def save(self, *args, **kwargs):
        # Auto-assign employee ID on first save within a business
        if not self.employee_id and self.business_id:
            self.employee_id = self.business.allocate_employee_id()
        super().save(*args, **kwargs)

    # ---- Status ----
    def deactivate(self, *, using=None):
        self.is_active_staff = False
        self.is_active = False
        self.save(
            update_fields=["is_active_staff", "is_active", "updated_at"],
            using=using,
        )

    def reactivate(self, *, using=None):
        self.is_active_staff = True
        self.is_active = True
        self.save(
            update_fields=["is_active_staff", "is_active", "updated_at"],
            using=using,
        )

    def __str__(self):
        return f"{self.get_full_name() or self.username} ({self.get_role_display()})"