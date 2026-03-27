# api/views.py

from rest_framework import viewsets, permissions, status
from rest_framework.decorators import action
from rest_framework.response import Response
from django.shortcuts import get_object_or_404
from django.utils import timezone
from datetime import datetime, timedelta

from accounts.models import User
from doctors.models import Doctor, Specialization
from appointments.models import Appointment
from medical_records.models import MedicalRecord

from .serializers import (
    UserSerializer, UserCreateSerializer, UserUpdateSerializer,
    UserRegistrationSerializer,
    DoctorSerializer, DoctorListSerializer, SpecializationSerializer,
    AppointmentSerializer, AppointmentCreateSerializer,
    MedicalRecordSerializer, MedicalRecordCreateSerializer
)


class UserViewSet(viewsets.ModelViewSet):
    """Manage users (patients & doctors)."""
    queryset = User.objects.all()
    permission_classes = [permissions.IsAuthenticated]

    def get_serializer_class(self):
        if self.action == 'create':
            return UserCreateSerializer
        elif self.action == 'register':
            return UserRegistrationSerializer
        elif self.action in ['update', 'partial_update']:
            return UserUpdateSerializer
        return UserSerializer

    def get_permissions(self):
        # Allow anyone to register, but require authentication for other actions
        if self.action == 'register':
            return [permissions.AllowAny()]
        return super().get_permissions()

    def get_queryset(self):
        user = self.request.user
        # Admins can see all; regular users see only themselves
        if user.is_staff:
            return super().get_queryset()
        return User.objects.filter(id=user.id)

    @action(detail=False, methods=['post'])
    def register(self, request):
        """Public endpoint to register a new user (patient or doctor)."""
        serializer = self.get_serializer(data=request.data)
        if serializer.is_valid():
            user = serializer.save()
            return Response(
                {'message': 'User created successfully', 'user_id': user.id},
                status=status.HTTP_201_CREATED
            )
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class SpecializationViewSet(viewsets.ReadOnlyModelViewSet):
    """List all medical specializations."""
    queryset = Specialization.objects.all()
    serializer_class = SpecializationSerializer
    permission_classes = [permissions.AllowAny]  # Publicly readable

class DoctorViewSet(viewsets.ReadOnlyModelViewSet):
    permission_classes = [permissions.AllowAny]

    def get_queryset(self):
        queryset = Doctor.objects.filter(is_available=True).order_by('id')
        specialty = self.request.query_params.get('specialty')
        if specialty:
            queryset = queryset.filter(specialization__name__icontains=specialty)
        location = self.request.query_params.get('location')
        if location:
            queryset = queryset.filter(user__city__icontains=location)
        return queryset

    def get_serializer_class(self):
        if self.action == 'list':
            return DoctorListSerializer
        return DoctorSerializer

    @action(detail=True, methods=['get'],url_path='available-dates')
    def available_dates(self, request, pk=None):
        """Return list of dates in the given month that have available slots."""
        doctor = self.get_object()
        year = int(request.query_params.get('year', timezone.now().year))
        month = int(request.query_params.get('month', timezone.now().month))
        first_day = datetime(year, month, 1).date()
        last_day = (first_day.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)
        # Business hours 9:00 to 17:00, 30-min slots
        business_hours = [(h, m) for h in range(9, 17) for m in (0, 30)]
        available_dates = []
        for day in range(1, last_day.day + 1):
            date = datetime(year, month, day).date()
            if date < timezone.now().date():
                continue
            free_slots = []
            for hour, minute in business_hours:
                slot_time = datetime.min.replace(hour=hour, minute=minute).time()
                if not Appointment.objects.filter(doctor=doctor, date=date, time=slot_time).exclude(status='cancelled').exists():
                    free_slots.append(slot_time)
            if free_slots:
                available_dates.append(date.isoformat())
        return Response({'dates': available_dates})

    @action(detail=True, methods=['get'],url_path='available-slots')
    def available_slots(self, request, pk=None):
        """Return available time slots for a given date."""
        doctor = self.get_object()
        date_str = request.query_params.get('date')
        if not date_str:
            return Response({'error': 'date parameter required'}, status=status.HTTP_400_BAD_REQUEST)
        try:
            date = datetime.strptime(date_str, '%Y-%m-%d').date()
        except ValueError:
            return Response({'error': 'Invalid date format. Use YYYY-MM-DD.'}, status=status.HTTP_400_BAD_REQUEST)
        if date < timezone.now().date():
            return Response({'slots': []})
        business_hours = [(h, m) for h in range(9, 17) for m in (0, 30)]
        slots = []
        for hour, minute in business_hours:
            slot_time = datetime.min.replace(hour=hour, minute=minute).time()
            if not Appointment.objects.filter(doctor=doctor, date=date, time=slot_time).exclude(status='cancelled').exists():
                slots.append(slot_time.strftime('%H:%M'))
        return Response({'slots': slots})


class AppointmentViewSet(viewsets.ModelViewSet):
    """Manage appointments (patients book, doctors view)."""
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        user = self.request.user
        if user.role == 'patient':
            return Appointment.objects.filter(patient=user)
        elif user.role == 'doctor':
            return Appointment.objects.filter(doctor__user=user)
        return Appointment.objects.none()

    def get_serializer_class(self):
        if self.action == 'create':
            return AppointmentCreateSerializer
        return AppointmentSerializer

    @action(detail=False, methods=['post'])
    def book(self, request):
        """Custom endpoint for booking an appointment."""
        user = request.user
        if user.role != 'patient':
            return Response(
                {'detail': 'Only patients can book appointments.'},
                status=status.HTTP_403_FORBIDDEN
            )
        serializer = AppointmentCreateSerializer(
            data=request.data,
            context={'request': request}
        )
        if serializer.is_valid():
            appointment = serializer.save()
            return Response(
                AppointmentSerializer(appointment).data,
                status=status.HTTP_201_CREATED
            )
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=True, methods=['post'])
    def cancel(self, request, pk=None):
        """Cancel an existing appointment."""
        appointment = self.get_object()
        user = request.user
        if appointment.patient != user and appointment.doctor.user != user:
            return Response(
                {'detail': 'You do not have permission to cancel this appointment.'},
                status=status.HTTP_403_FORBIDDEN
            )
        if appointment.status not in ['pending', 'confirmed']:
            return Response(
                {'detail': 'This appointment cannot be cancelled.'},
                status=status.HTTP_400_BAD_REQUEST
            )
        appointment.status = 'cancelled'
        appointment.save()
        return Response(
            {'detail': 'Appointment cancelled successfully.'},
            status=status.HTTP_200_OK
        )

    @action(detail=True, methods=['post'])
    def confirm(self, request, pk=None):
        """Confirm an appointment (doctor only)."""
        appointment = self.get_object()
        user = request.user
        if user.role != 'doctor' or appointment.doctor.user != user:
            return Response(
                {'detail': 'Only the assigned doctor can confirm appointments.'},
                status=status.HTTP_403_FORBIDDEN
            )
        if appointment.status != 'pending':
            return Response(
                {'detail': 'Appointment cannot be confirmed in its current state.'},
                status=status.HTTP_400_BAD_REQUEST
            )
        appointment.status = 'confirmed'
        appointment.save()
        return Response(
            {'detail': 'Appointment confirmed successfully.'},
            status=status.HTTP_200_OK
        )


class MedicalRecordViewSet(viewsets.ModelViewSet):
    """Manage medical records (patients view own, doctors create)."""
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        user = self.request.user
        queryset = MedicalRecord.objects.all()
        if user.role == 'patient':
            queryset = queryset.filter(patient=user)
        elif user.role == 'doctor':
            queryset = queryset.filter(doctor__user=user)
        else:
            return MedicalRecord.objects.none()
        # Filter by record_type if provided
        record_type = self.request.query_params.get('record_type')
        if record_type:
            queryset = queryset.filter(record_type=record_type)
        return queryset

    def get_serializer_class(self):
        if self.action in ['create', 'update', 'partial_update']:
            return MedicalRecordCreateSerializer
        return MedicalRecordSerializer

    def perform_create(self, serializer):
        user = self.request.user
        if user.role == 'doctor':
            doctor = get_object_or_404(Doctor, user=user)
            serializer.save(doctor=doctor)
        else:
            serializer.save()