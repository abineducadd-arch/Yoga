# serializers.py
from rest_framework import serializers
from django.contrib.auth.hashers import make_password
from django.utils import timezone
from datetime import datetime

from doctors.models import Doctor, Specialization
from appointments.models import Appointment
from accounts.models import User
from medical_records.models import MedicalRecord

# ------------------- Accounts Serializers -------------------

class UserSerializer(serializers.ModelSerializer):
    """Serializer for User model (read-only or safe fields)."""
    full_name = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = ['id', 'username', 'email', 'first_name', 'last_name', 'full_name', 'role', 'phone', 'date_of_birth', 'profile_picture']
        read_only_fields = ['id', 'username', 'email', 'role']  # email and username are typically set on creation

    def get_full_name(self, obj):
        return obj.get_full_name()

class UserCreateSerializer(serializers.ModelSerializer):
    """Serializer for creating new users (registration)."""
    password = serializers.CharField(write_only=True, style={'input_type': 'password'})
    confirm_password = serializers.CharField(write_only=True, style={'input_type': 'password'})

    class Meta:
        model = User
        fields = ['username', 'email', 'password', 'confirm_password', 'first_name', 'last_name', 'role', 'phone', 'date_of_birth']

    def validate(self, data):
        if data['password'] != data.pop('confirm_password'):
            raise serializers.ValidationError({"confirm_password": "Passwords do not match."})
        return data

    def create(self, validated_data):
        validated_data['password'] = make_password(validated_data['password'])
        return super().create(validated_data)

class UserUpdateSerializer(serializers.ModelSerializer):
    """Serializer for updating user profile (partial updates)."""
    class Meta:
        model = User
        fields = ['first_name', 'last_name', 'phone', 'date_of_birth', 'profile_picture']
        read_only_fields = ['id', 'username', 'email', 'role']

# ------------------- Doctors Serializers -------------------

class DoctorRegistrationSerializer(serializers.ModelSerializer):
    specialization_id = serializers.PrimaryKeyRelatedField(
        queryset=Specialization.objects.all(),
        source='specialization'
    )

    class Meta:
        model = Doctor
        fields = ['specialization_id', 'qualifications', 'experience_years', 'bio', 'consultation_fee']

class UserRegistrationSerializer(serializers.ModelSerializer):
    doctor_profile = DoctorRegistrationSerializer(write_only=True, required=False)
    confirm_password = serializers.CharField(write_only=True)

    class Meta:
        model = User
        fields = ['username', 'email', 'password', 'confirm_password', 'first_name', 'last_name',
                  'role', 'phone', 'date_of_birth', 'doctor_profile']

    def validate(self, data):
        if data['password'] != data['confirm_password']:
            raise serializers.ValidationError({"confirm_password": "Passwords do not match."})

        # Ensure doctor profile is present when role is doctor
        if data.get('role') == 'doctor' and not data.get('doctor_profile'):
            raise serializers.ValidationError({"doctor_profile": "Doctor profile is required."})

        return data

    def create(self, validated_data):
        # Remove doctor profile from user data
        doctor_profile_data = validated_data.pop('doctor_profile', None)
        validated_data.pop('confirm_password')
        user = User.objects.create_user(**validated_data)

        # Create doctor profile if provided
        if doctor_profile_data:
            Doctor.objects.create(user=user, **doctor_profile_data)

        return user


class SpecializationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Specialization
        fields = ['id', 'name', 'description']

class DoctorSerializer(serializers.ModelSerializer):
    """Serializer for Doctor model with nested user info."""
    user = UserSerializer(read_only=True)
    specialization = SpecializationSerializer(read_only=True)
    specialization_id = serializers.PrimaryKeyRelatedField(
        queryset=Specialization.objects.all(),
        source='specialization',
        write_only=True,
        required=False
    )

    class Meta:
        model = Doctor
        fields = [
            'id', 'user', 'specialization', 'specialization_id', 'qualifications',
            'experience_years', 'bio', 'consultation_fee', 'rating', 'total_reviews',
            'is_available'
        ]
        read_only_fields = ['rating', 'total_reviews']  # these might be calculated

    def create(self, validated_data):
        # If we need to create a doctor from scratch, but usually doctors are created via user registration.
        # This can be used by admin.
        return super().create(validated_data)

class DoctorListSerializer(serializers.ModelSerializer):
    name = serializers.SerializerMethodField()
    specialization_name = serializers.CharField(source='specialization.name', read_only=True)
    rating_display = serializers.SerializerMethodField()
    profile_picture = serializers.SerializerMethodField()  # <-- add this

    class Meta:
        model = Doctor
        fields = [
            'id', 'name', 'specialization_name', 'experience_years', 'consultation_fee',
            'rating', 'total_reviews', 'rating_display', 'is_available', 'profile_picture'
        ]

    def get_name(self, obj):
        return f"Dr. {obj.user.get_full_name() or obj.user.username}"

    def get_rating_display(self, obj):
        return f"{obj.rating:.1f}" if obj.rating else "New"

    def get_profile_picture(self, obj):
        if obj.user.profile_picture:
            return obj.user.profile_picture.url
        return None

# ------------------- Appointments Serializers -------------------

class AppointmentSerializer(serializers.ModelSerializer):
    """Serializer for Appointment model with nested patient/doctor details."""
    patient = UserSerializer(read_only=True)
    doctor = DoctorListSerializer(read_only=True)
    patient_id = serializers.PrimaryKeyRelatedField(
        queryset=User.objects.filter(role='patient'),
        source='patient',
        write_only=True,
        required=False
    )
    doctor_id = serializers.PrimaryKeyRelatedField(
        queryset=Doctor.objects.all(),
        source='doctor',
        write_only=True,
        required=False
    )
    status_display = serializers.CharField(source='get_status_display', read_only=True)

    class Meta:
        model = Appointment
        fields = [
            'id', 'patient', 'patient_id', 'doctor', 'doctor_id', 'date', 'time',
            'status', 'status_display', 'notes', 'created_at'
        ]
        read_only_fields = ['created_at', 'status']  # status may be set by system or doctor

    def validate(self, data):
        # Custom validation for appointments
        date = data.get('date')
        time = data.get('time')
        doctor = data.get('doctor')
        patient = data.get('patient')

        # Ensure date is not in the past
        if date and date < timezone.now().date():
            raise serializers.ValidationError({"date": "Cannot book appointments in the past."})

        # Check for duplicate (doctor already booked at that time)
        if doctor and date and time:
            if Appointment.objects.filter(doctor=doctor, date=date, time=time).exclude(status='cancelled').exists():
                raise serializers.ValidationError({"time": "This time slot is already taken."})

        # Business hours check (optional)
        if time and (time < datetime.min.replace(hour=9, minute=0).time() or time > datetime.min.replace(hour=17, minute=0).time()):
            raise serializers.ValidationError({"time": "Appointments are only available between 09:00 and 17:00."})

        return data

class AppointmentCreateSerializer(serializers.ModelSerializer):
    """Serializer specifically for creating a new appointment (patient books)."""
    class Meta:
        model = Appointment
        fields = ['doctor_id', 'date', 'time', 'notes']
        extra_kwargs = {
            'doctor_id': {'write_only': True},
            'notes': {'required': False},
        }

    def validate(self, data):
        # Additional validations for booking
        doctor_id = data.get('doctor_id')
        date = data.get('date')
        time = data.get('time')

        # Check if doctor exists and is available
        try:
            doctor = Doctor.objects.get(id=doctor_id, is_available=True)
        except Doctor.DoesNotExist:
            raise serializers.ValidationError({"doctor_id": "Doctor not found or not available."})

        # Check for duplicate
        if Appointment.objects.filter(doctor=doctor, date=date, time=time).exclude(status='cancelled').exists():
            raise serializers.ValidationError({"time": "This time slot is already taken."})

        # Business hours
        if time < datetime.min.replace(hour=9, minute=0).time() or time > datetime.min.replace(hour=17, minute=0).time():
            raise serializers.ValidationError({"time": "Appointments are only available between 09:00 and 17:00."})

        return data

    def create(self, validated_data):
        # The patient is the current user (set in view)
        # We'll expect patient to be passed via context or set in view
        patient = self.context.get('request').user
        doctor = validated_data.pop('doctor_id')
        appointment = Appointment.objects.create(patient=patient, doctor=doctor, **validated_data)
        return appointment

# ------------------- Medical Records Serializers -------------------

class MedicalRecordSerializer(serializers.ModelSerializer):
    """Serializer for MedicalRecord model with nested patient/doctor info."""
    patient = UserSerializer(read_only=True)
    doctor = DoctorListSerializer(read_only=True)
    record_type_display = serializers.CharField(source='get_record_type_display', read_only=True)
    file_url = serializers.SerializerMethodField()

    class Meta:
        model = MedicalRecord
        fields = [
            'id', 'patient', 'doctor', 'appointment', 'record_type', 'record_type_display',
            'title', 'description', 'file', 'file_url', 'date_issued', 'created_at', 'updated_at'
        ]
        read_only_fields = ['created_at', 'updated_at']

    def get_file_url(self, obj):
        if obj.file:
            return obj.file.url
        return None

class MedicalRecordCreateSerializer(serializers.ModelSerializer):
    """Serializer for creating a new medical record (by doctor or admin)."""
    class Meta:
        model = MedicalRecord
        fields = ['patient', 'doctor', 'appointment', 'record_type', 'title', 'description', 'file', 'date_issued']
        extra_kwargs = {
            'doctor': {'required': False},
            'appointment': {'required': False},
            'file': {'required': False},
        }

    def validate(self, data):
        # Ensure patient is a patient user
        patient = data.get('patient')
        if patient and patient.role != 'patient':
            raise serializers.ValidationError({"patient": "The user must be a patient."})
        return data
    
