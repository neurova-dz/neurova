"""Authentication and onboarding forms."""

from __future__ import annotations

from flask_wtf import FlaskForm
from wtforms import (
    BooleanField,
    PasswordField,
    SelectField,
    StringField,
    TextAreaField,
)
from wtforms.validators import DataRequired, Email, EqualTo, Length, Optional, Regexp

from app.data.countries import COUNTRY_CHOICES


class LoginForm(FlaskForm):
    email = StringField(
        "Email",
        validators=[DataRequired(), Email(), Length(max=180)],
    )
    password = PasswordField("Password", validators=[DataRequired(), Length(min=1, max=128)])
    remember = BooleanField("Keep me signed in", default=False)


class ClinicRegisterForm(FlaskForm):
    """Clinic-first registration: clinic name + first admin's identity."""

    clinic_name = StringField(
        "Clinic / Hospital Name",
        validators=[DataRequired(), Length(min=2, max=200)],
    )
    clinic_country = SelectField(
        "Country",
        choices=COUNTRY_CHOICES,
        default="Algeria",
        validators=[Optional()],
    )
    clinic_phone = StringField("Clinic Phone", validators=[Optional(), Length(max=40)])
    clinic_address = StringField("Address", validators=[Optional(), Length(max=500)])
    contact_email = StringField(
        "Clinic Contact Email",
        validators=[Optional(), Email(), Length(max=180)],
    )

    admin_full_name = StringField(
        "Your Full Name",
        validators=[DataRequired(), Length(min=2, max=160)],
    )
    admin_email = StringField(
        "Your Email (used for login)",
        validators=[DataRequired(), Email(), Length(max=180)],
    )
    admin_password = PasswordField(
        "Password (min. 8 chars)",
        validators=[DataRequired(), Length(min=8, max=128)],
    )
    admin_password_confirm = PasswordField(
        "Confirm Password",
        validators=[DataRequired(), EqualTo("admin_password", message="Passwords do not match.")],
    )
    accept_terms = BooleanField(
        "I confirm I am authorized to register this clinic and accept the terms of service.",
        default=False,
    )


class DoctorInviteForm(FlaskForm):
    """Issued by a clinic admin (or superadmin)."""

    full_name = StringField(
        "Full Name", validators=[DataRequired(), Length(min=2, max=160)]
    )
    email = StringField(
        "Email", validators=[DataRequired(), Email(), Length(max=180)]
    )
    specialty = SelectField(
        "Specialty",
        choices=[
            ("brain_tumor", "Brain MRI / tumor"),
            ("diabetic_retinopathy", "Diabetic retinopathy"),
            ("", "Not set"),
        ],
        validators=[Optional()],
    )
    title = StringField("Title (optional)", validators=[Optional(), Length(max=80)])
    phone = StringField("Phone (optional)", validators=[Optional(), Length(max=40)])


class AdminNewClinicForm(FlaskForm):
    """Superadmin: create a clinic and send a clinic_admin invite."""

    clinic_name = StringField(
        "Clinic / Hospital Name",
        validators=[DataRequired(), Length(min=2, max=200)],
    )
    country = SelectField(
        "Country",
        choices=[COUNTRY_CHOICES],
        default="Algeria",
        validators=[Optional()],
    )
    admin_email = StringField(
        "Admin Email",
        validators=[DataRequired(), Email(), Length(max=180)],
    )
    admin_full_name = StringField(
        "Admin Full Name",
        validators=[DataRequired(), Length(min=2, max=160)],
    )


class ClinicAdminInviteForm(FlaskForm):
    """Issued by a superadmin to seat a clinic admin into an existing clinic."""

    clinic_id = StringField("Clinic ID", validators=[DataRequired()])
    full_name = StringField(
        "Full Name", validators=[DataRequired(), Length(min=2, max=160)]
    )
    email = StringField(
        "Email", validators=[DataRequired(), Email(), Length(max=180)]
    )


class AcceptInviteForm(FlaskForm):
    """Set a password from an invitation link."""

    full_name = StringField(
        "Full Name", validators=[DataRequired(), Length(min=2, max=160)]
    )
    password = PasswordField(
        "Password (min. 8 chars)",
        validators=[DataRequired(), Length(min=8, max=128)],
    )
    password_confirm = PasswordField(
        "Confirm Password",
        validators=[DataRequired(), EqualTo("password", message="Passwords do not match.")],
    )


class ForgotForm(FlaskForm):
    email = StringField(
        "Email", validators=[DataRequired(), Email(), Length(max=180)]
    )


class ResetForm(FlaskForm):
    password = PasswordField(
        "New Password",
        validators=[DataRequired(), Length(min=8, max=128)],
    )
    password_confirm = PasswordField(
        "Confirm New Password",
        validators=[DataRequired(), EqualTo("password", message="Passwords do not match.")],
    )


class CloseFolderForm(FlaskForm):
    reason = TextAreaField(
        "Closure Reason",
        validators=[DataRequired(), Length(min=3, max=500)],
    )


class FolderNotesForm(FlaskForm):
    notes_md = TextAreaField(
        "Clinical Notes (markdown supported)",
        validators=[Optional(), Length(max=10000)],
    )


class PatientForm(FlaskForm):
    first_name = StringField("First Name", validators=[DataRequired(), Length(max=120)])
    last_name = StringField("Last Name", validators=[DataRequired(), Length(max=120)])
    sex = SelectField(
        "Sex",
        choices=[("", "—"), ("female", "Female"), ("male", "Male")],
        validators=[Optional()],
    )
    birth_date = StringField(
        "Birth Date",
        validators=[
            Optional(),
            Regexp(r"^\d{2}-\d{2}-\d{4}$", message="Use DD-MM-YYYY."),
        ],
    )
    mrn = StringField("MRN", validators=[Optional(), Length(max=80)])
    phone = StringField("Phone", validators=[Optional(), Length(max=40)])
    clinical_notes = TextAreaField(
        "Clinical Notes", validators=[Optional(), Length(max=10000)]
    )
