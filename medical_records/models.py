# medical_records/models.py
from django.db import models
from django.utils import timezone
from accounts.models import User
from doctors.models import Doctor
from appointments.models import Appointment

class MedicalRecord(models.Model):
    RECORD_TYPES = (
        ('lab', 'Lab Result'),
        ('imaging', 'Imaging Report'),
        ('prescription', 'Prescription'),
        ('vaccination', 'Vaccination Record'),
        ('clinical_note', 'Clinical Note'),
        ('discharge_summary', 'Discharge Summary'),
        ('other', 'Other'),
    )

    patient = models.ForeignKey(
        User, 
        on_delete=models.CASCADE, 
        related_name='medical_records',
        limit_choices_to={'role': 'patient'}
    )
    doctor = models.ForeignKey(
        Doctor,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='authored_records'
    )
    appointment = models.OneToOneField(
        Appointment,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='medical_record'
    )
    record_type = models.CharField(max_length=20, choices=RECORD_TYPES, default='other')
    title = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    file = models.FileField(upload_to='medical_records/%Y/%m/%d/', blank=True, null=True)
    date_issued = models.DateField(default=timezone.now)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-date_issued']

    def __str__(self):
        return f"{self.patient.get_full_name()} - {self.title} ({self.date_issued})"