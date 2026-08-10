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

    # Active pool of encodings used for 1:N matching (e.g. up to 3 angles captured at
    # registration). Falls back to current_face_encoding alone when empty, so employees
    # registered before this field existed keep matching exactly as before.
    face_encodings = models.JSONField(blank=True, null=True, default=list)
    
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
    allowed_ip       = models.CharField(max_length=45, null=True, blank=True)
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
    category = models.CharField(max_length=50, blank=True, null=True) #values=unknown device and image spoofing UNDV and UNDM SPFV SPFM
    

    def __str__(self):
        return f"Spoofing Attempt @ {self.timestamp}"    

class FaceMismatchLog(models.Model):
    id                   = models.AutoField(primary_key=True)
    timestamp            = models.DateTimeField(auto_now_add=True)
    verified_employee_id = models.CharField(max_length=50)
    mark_employee_id     = models.CharField(max_length=50, null=True, blank=True)
    image                = models.TextField()  # Storing as base64 string
    device_id            = models.CharField(max_length=50, blank=True, null=True)

    def __str__(self):
        return f"Mismatch: Verified {self.verified_employee_id} vs {self.mark_employee_id or 'Unknown'} @ {self.timestamp}"

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

def generate_leavetype_id():
    last_leave_type = LeaveType.objects.all().order_by('id').last()
    if not last_leave_type:
        return 1
    return last_leave_type.id + 1

class LeaveType(models.Model):
    id        = models.IntegerField(primary_key=True, default=generate_leavetype_id, editable=False)
    name      = models.CharField(max_length=50, unique=True)
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return self.name

def generate_leave_id():
    last_leave = LeaveRequest.objects.all().order_by('id').last()
    if not last_leave:
        return 1
    return last_leave.id + 1

class LeaveRequest(models.Model):
    id = models.IntegerField(primary_key=True, default=generate_leave_id, editable=False)
    employee_id = models.CharField(max_length=50) # Matching employee_id type
    employee_name = models.CharField(max_length=150, null=True, blank=True)
    department = models.CharField(max_length=100, null=True, blank=True)
    department_id = models.CharField(max_length=50, null=True, blank=True)
    start_date = models.DateField()
    end_date = models.DateField()
    leave_type = models.CharField(max_length=50) # e.g. Sick, Casual, Annual
    reason = models.TextField()
    status = models.CharField(max_length=20, default='Pending') # Pending, Approved, Rejected
    applied_on = models.DateTimeField(auto_now_add=True)
    reviewed_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='reviewed_leaves')
    reviewed_by_name = models.CharField(max_length=150, null=True, blank=True)

    def __str__(self):
        return f"{self.employee_id} - {self.leave_type} - {self.status}"