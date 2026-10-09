from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import AuthenticationForm, PasswordChangeForm
from django.contrib.auth.password_validation import validate_password
from django.db import transaction

from .models import Business
from .services import _assert_can_manage

User = get_user_model()


# =====================================================================
# Tailwind styling
# =====================================================================
class TailwindMixin:
    INPUT = "input"
    CHECKBOX = (
        "h-4 w-4 rounded border-slate-300 text-brand-600 "
        "focus:ring-brand-500 dark:border-slate-600 dark:bg-slate-800"
    )
    TEXTAREA = "input min-h-[80px]"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name, field in self.fields.items():
            w = field.widget
            if isinstance(w, forms.CheckboxInput):
                css = self.CHECKBOX
            elif isinstance(w, forms.Textarea):
                css = self.TEXTAREA
            else:
                css = self.INPUT
            w.attrs["class"] = f"{w.attrs.get('class', '')} {css}".strip()
            if name in self.errors:
                w.attrs["aria-invalid"] = "true"
            if field.required and not isinstance(w, forms.CheckboxInput):
                w.attrs.setdefault("aria-required", "true")

            # Link errors to the input for screen readers
            if name in self.errors:
                w.attrs["aria-invalid"] = "true"
                w.attrs["aria-describedby"] = f"id_{name}-errors"


# =====================================================================
# Business
# =====================================================================
class BusinessForm(TailwindMixin, forms.ModelForm):
    class Meta:
        model = Business
        fields = ["name", "address", "phone1", "phone2", "email",
                  "logo", "tax_rate", "currency"]
        widgets = {"address": forms.Textarea(attrs={"rows": 3})}


# =====================================================================
# Auth
# =====================================================================
class LoginForm(TailwindMixin, AuthenticationForm):
    username = forms.CharField(
        widget=forms.TextInput(attrs={
            "autofocus": True, "placeholder": "Username",
            "autocomplete": "username",
        }),
    )
    password = forms.CharField(
        widget=forms.PasswordInput(attrs={
            "placeholder": "Password", "autocomplete": "current-password",
        }),
    )
    remember_me = forms.BooleanField(required=False, initial=True)


# =====================================================================
# Staff — create + edit
# =====================================================================
class BaseStaffForm(TailwindMixin, forms.ModelForm):
    ACCOUNT_FIELDS = (
        "username", "first_name", "last_name", "email",
        "role", "is_active_staff", "hired_at", "employee_id",
    )
    PROFILE_FIELDS = ("phone1", "phone2", "address", "profile_picture")

    class Meta:
        model = User
        fields = [
            "username", "first_name", "last_name", "email",
            "phone1", "phone2", "address", "employee_id",
            "profile_picture", "role", "is_active_staff", "hired_at",
        ]
        widgets = {
            "hired_at": forms.DateInput(attrs={"type": "date"}),
            "address": forms.Textarea(attrs={"rows": 2}),
        }

    def __init__(self, *args, actor=None, **kwargs):
        self.actor = actor
        super().__init__(*args, **kwargs)
        self._apply_role_restrictions()

    # ---- Template helpers ----
    def account_fields(self):
        return [self[n] for n in self.ACCOUNT_FIELDS if n in self.fields]

    def profile_fields(self):
        return [self[n] for n in self.PROFILE_FIELDS if n in self.fields]

    # ---- Restrictions ----
    def _apply_role_restrictions(self):
        actor = self.actor
        # Role choices: never allow OWNER via this form (one owner per business)
        self.fields["role"].choices = [
            (User.Role.MANAGER, "Manager"),
            (User.Role.SALESPERSON, "Sales Person"),
        ]
        if not actor or not actor.is_owner:
            # Managers can only assign salesperson
            self.fields["role"].choices = [
                (User.Role.SALESPERSON, "Sales Person"),
            ]
            self.fields["role"].initial = User.Role.SALESPERSON

        if self.instance.pk and self.instance.is_owner:
            self.fields["role"].disabled = True
            self.fields["is_active_staff"].disabled = True

    # ---- Validation ----
    def clean_username(self):
        username = self.cleaned_data["username"].strip()
        qs = User.objects.filter(username__iexact=username)
        if self.instance.pk:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise forms.ValidationError("That username is already taken.")
        return username

    def clean_email(self):
        email = (self.cleaned_data.get("email") or "").strip().lower()
        if email:
            qs = User.objects.filter(email__iexact=email)
            if self.instance.pk:
                qs = qs.exclude(pk=self.instance.pk)
            if qs.exists():
                raise forms.ValidationError(
                    "Another account already uses this email."
                )
        return email

    def clean_is_active_staff(self):
        value = self.cleaned_data.get("is_active_staff")
        if (self.actor and self.instance.pk
                and self.instance.pk == self.actor.pk and not value):
            raise forms.ValidationError("You can't deactivate yourself.")
        return value


class StaffCreateForm(BaseStaffForm):
    """Owner-only. Generates a unique temporary password and forces a change."""

    class Meta(BaseStaffForm.Meta):
        fields = [
            "username", "first_name", "last_name", "email",
            "phone1", "phone2", "address",
            "role", "is_active_staff", "hired_at",
        ]

    @transaction.atomic
    def save(self, commit=True):
        user = super().save(commit=False)
        business = self.actor.business
        if business is None:
            raise forms.ValidationError("Your account has no business assigned.")

        user.business = business
        user.must_change_password = True
        user.employee_id = business.allocate_employee_id()

        # Deferred import to avoid circular dependency
        from .services import generate_temporary_password
        temp = generate_temporary_password()
        user.set_password(temp)

        if commit:
            user.save()

        # Attach temp password for one-time display in the view
        self.temp_password = temp
        return user


class StaffEditForm(BaseStaffForm):
    """Edit without password fields. Use reset_user_password for resets."""
    pass


# =====================================================================
# Profile / password
# =====================================================================
class ProfileForm(TailwindMixin, forms.ModelForm):
    class Meta:
        model = User
        fields = ["first_name", "last_name", "email", "phone1", "phone2",
                  "address", "profile_picture"]
        widgets = {"address": forms.Textarea(attrs={"rows": 3})}


class CustomPasswordChangeForm(TailwindMixin, PasswordChangeForm):
    pass


# =====================================================================
# One-time bootstrap: Business + first Owner
# =====================================================================
class BootstrapOwnerForm(TailwindMixin, forms.Form):
    business_name = forms.CharField(max_length=200)
    username = forms.CharField(max_length=150)
    email = forms.EmailField()
    first_name = forms.CharField(max_length=150, required=False)
    last_name = forms.CharField(max_length=150, required=False)
    password1 = forms.CharField(widget=forms.PasswordInput, label="Password")
    password2 = forms.CharField(widget=forms.PasswordInput, label="Confirm password")

    def clean(self):
        cleaned = super().clean()
        p1, p2 = cleaned.get("password1"), cleaned.get("password2")
        if p1 and p2 and p1 != p2:
            self.add_error("password2", "Passwords do not match.")
        if p1:
            probe = User(
                username=cleaned.get("username", ""),
                email=cleaned.get("email", ""),
            )
            try:
                validate_password(p1, user=probe)
            except forms.ValidationError as e:
                self.add_error("password1", e)
        return cleaned

    @transaction.atomic
    def save(self):
        data = self.cleaned_data
        business = Business.objects.create(
            name=data["business_name"], email=data["email"],
        )
        user = User.objects.create_user(
            username=data["username"],
            email=data["email"],
            password=data["password1"],
            first_name=data["first_name"],
            last_name=data["last_name"],
            business=business,
            role=User.Role.OWNER,
            must_change_password=False,
        )
        business.owner = user
        business.save(update_fields=["owner", "updated_at"])
        return user