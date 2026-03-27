from django.db import models
from django.utils import timezone
from django.contrib.auth.models import User

class Employee(models.Model):
    employee_id = models.CharField(max_length=50, primary_key=True)
    name = models.CharField(max_length=100)
    
    # Latest/current face encoding
    current_face_encoding = models.JSONField(blank=True, null=True, default=list)
    
    # Store all past face encodings
    face_encoding_data_history = models.JSONField(blank=True, null=True, default=list)
    
    # Store image hash (for duplicate check)
    image_md5 = models.CharField(max_length=64, blank=True, null=True)
    
    is_active = models.BooleanField(default=True)
    
    # Audit fields
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='created_biometrics')
    created_date = models.DateTimeField(auto_now_add=True)
    lastmodified_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='modified_biometrics')
    lastmodified_date = models.DateTimeField(auto_now=True)

    def update_encoding(self, new_encoding, new_image_md5=None):
        """Save previous encoding to history, update current encoding and optional image MD5."""
        if self.current_face_encoding:
            self.face_encoding_data_history.append(self.current_face_encoding)
        self.current_face_encoding = new_encoding
        if new_image_md5:
            self.image_md5 = new_image_md5
        self.save(update_fields=['current_face_encoding', 'face_encoding_data_history', 'image_md5', 'lastmodified_date'])

    def __str__(self):
        return f"{self.employee_id} - {self.name} - Active: {self.is_active}"

class EmployeeAttendance(models.Model):
    ATTEND_TYPE = (('IN','IN'),('OUT','OUT'))

    attendence_id = models.AutoField(primary_key=True)
    employee_id = models.CharField(max_length=50)  # store actual employee ID
    device_id = models.CharField(max_length=50, blank=True, null=True)
    attendence_time = models.DateTimeField(auto_now_add=True)
    attendence_type = models.CharField(max_length=3, choices=ATTEND_TYPE, default='IN')
    confidence = models.FloatField(null=True, blank=True)  # optional similarity score

    def __str__(self):
        return f"{self.employee_id} - {self.attendence_type} @ {self.attendence_time}"

class Register(models.Model):
    id               = models.AutoField(primary_key=True)
    name             = models.CharField(max_length=500)
    role             = models.CharField(max_length=500)
    password         = models.CharField(max_length=500)
    confirmPassword  = models.CharField(max_length=500)
    allowed_ip       = models.CharField(max_length=45, unique=True, null=True, blank=True)
    employee_id      = models.CharField(max_length=50, null=True, blank=True)
    department       = models.CharField(max_length=100, null=True, blank=True)
    device           = models.CharField(max_length=255, unique=True, null=True, blank=True)
    fingerprint      = models.CharField(max_length=255, unique=True, null=True, blank=True)

    def __str__(self):
        return f"{self.name} ({self.role}) — IP: {self.allowed_ip or 'N/A'}"

class AllowedDevice(models.Model):
    """Global whitelist for face recognition endpoints."""
    id         = models.AutoField(primary_key=True)
    label      = models.CharField(max_length=100, help_text="e.g. 'OPD Kiosk 1'")
    ip_address = models.CharField(max_length=45, unique=True)
    fingerprint = models.CharField(max_length=255, unique=True, null=True, blank=True)
    is_active  = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.label} ({self.ip_address}) — {'Active' if self.is_active else 'Inactive'}"

class SpoofingAttempt(models.Model):
    id          = models.AutoField(primary_key=True)
    employee_id = models.CharField(max_length=50, null=True, blank=True)
    image       = models.TextField()  # Storing as base64 string
    timestamp   = models.DateTimeField(auto_now_add=True)
    device_id   = models.CharField(max_length=50, blank=True, null=True)

    def __str__(self):
        return f"Spoofing Attempt @ {self.timestamp}"    

class Shift(models.Model):
    id         = models.AutoField(primary_key=True)
    name       = models.CharField(max_length=50, unique=True)
    start_time = models.TimeField()
    end_time   = models.TimeField()
    is_active  = models.BooleanField(default=True)

    def __str__(self):
        return f"{self.name} ({self.start_time} - {self.end_time})"

class Department(models.Model):
    id     = models.AutoField(primary_key=True)
    name   = models.CharField(max_length=100, unique=True)
    shifts = models.ManyToManyField(Shift, related_name='departments', blank=True)

    def __str__(self):
        return self.name

class EmployeeShiftSchedule(models.Model):
    id       = models.AutoField(primary_key=True)
    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name='shift_schedules')
    shift    = models.ForeignKey(Shift, on_delete=models.CASCADE)
    date     = models.DateField()
    
    class Meta:
        unique_together = ('employee', 'date')
        indexes = [
            models.Index(fields=['employee', 'date']),
            models.Index(fields=['date']),
        ]

    def __str__(self):
        return f"{self.employee.name} - {self.date} - {self.shift.name}"