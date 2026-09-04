import json
from django.db import models
from django.db.models.fields.json import JSONField as DjangoJSONField
from django.utils import timezone
from django.contrib.auth.models import User
from django.contrib.auth.hashers import make_password
from bson import ObjectId

# Safe patch for JSONField to handle BSON dict/list returned by MongoDB/Djongo
_original_from_db_value = DjangoJSONField.from_db_value
def _safe_json_from_db_value(self, value, expression, connection):
    if value is None:
        return value
    if isinstance(value, (dict, list)):
        return value
    if isinstance(value, (str, bytes, bytearray)):
        try:
            return json.loads(value, cls=self.decoder)
        except Exception:
            return value
    return value
DjangoJSONField.from_db_value = _safe_json_from_db_value


class ObjectIdField(models.Field):
    """ Custom field to store ObjectId """
    def __init__(self, *args, **kwargs):
        kwargs['unique'] = True
        super().__init__(*args, **kwargs)

    def get_prep_value(self, value):
        return str(value) if isinstance(value, ObjectId) else value

    def from_db_value(self, value, expression, connection):
        return ObjectId(value) if value else None

class Admin_groups(models.Model): 
    email = models.EmailField(max_length=500, unique=True)
    employee_name = models.CharField(max_length=500)
    password = models.CharField(max_length=500)
    role = models.CharField(max_length=100)
    mobile = models.CharField(max_length=100, blank=True, null=True)
    id = ObjectIdField(primary_key=True, default=ObjectId)
    
    username = None  # Remove username field as we use email for authentication
    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS = []

    def save(self, *args, **kwargs):
        """Ensure password is hashed before saving"""
        if self.password and not self.password.startswith("pbkdf2_sha256$"):
            self.password = make_password(self.password)
        super().save(*args, **kwargs)

class Profile(models.Model):
    employeeId = models.CharField(max_length=100, unique=True, primary_key=True)
    employeeName = models.CharField(max_length=255)
    fatherName = models.CharField(max_length=255, null=True, blank=True)
    motherName = models.CharField(max_length=255, null=True, blank=True)
    gender = models.CharField(max_length=10, null=True, blank=True)
    mobileNumber = models.CharField(max_length=15, null=True, blank=True)
    bloodGroup = models.CharField(max_length=5, null=True, blank=True)
    maritalStatus = models.CharField(max_length=20, null=True, blank=True)
    guardianNumber = models.CharField(max_length=15, null=True, blank=True)
    dateOfBirth = models.DateTimeField(null=True, blank=True)
    age = models.IntegerField(null=True, blank=True)
    email = models.EmailField(blank=True, null=True)

    department = models.CharField(max_length=100, null=True, blank=True)
    designation = models.CharField(max_length=100, null=True, blank=True)
    primaryRole = models.CharField(max_length=100, default='Employee')
    additionalRoles = models.JSONField(default=list)
    dataEntitlements = models.JSONField(default=list)
    hospitalCode = models.CharField(max_length=100, default="SH001")

    employmentStatus = models.CharField(max_length=20, default='Active')
    registrationNumber = models.CharField(max_length=100, null=True, blank=True)
    validityDate = models.DateField(null=True, blank=True)

    kycDetails = models.JSONField(default=dict)
    familyDetails = models.JSONField(default=dict)
    qualifications = models.JSONField(default=list)
    experiences = models.JSONField(default=list)

    bankDetails = models.JSONField(default=dict)
    salaryDetails = models.JSONField(default=dict)
    fnfStatus = models.JSONField(default=dict)

    profileImage = models.CharField(max_length=255, null=True, blank=True)
    signatureFileId = models.CharField(max_length=100, null=True, blank=True)
    created_by = models.CharField(max_length=100, blank=True, null=True)
    created_date = models.DateTimeField(auto_now_add=True)
    lastmodified_by = models.CharField(max_length=100, blank=True, null=True)
    lastmodified_date = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'backend_diagnostics_profile'

class GridFSFile(models.Model):
    file_id = models.CharField(max_length=100, unique=True)
    filename = models.CharField(max_length=500)
    content_type = models.CharField(max_length=100)
    file_type = models.CharField(max_length=100)
    upload_date = models.DateTimeField(auto_now_add=True)
    uploaded_by = models.CharField(max_length=100, default='system')
    
    class Meta:
        db_table = 'gridfs_files'

    def __str__(self):
        return f"{self.filename} ({self.file_id})"

class user(models.Model):
    employeeId = models.CharField(max_length=50, unique=True, primary_key=True)
    password = models.CharField(max_length=500)
    is_active = models.BooleanField(default=True)
    created_date = models.DateTimeField(auto_now_add=True)
    created_by = models.CharField(max_length=100, default='system')
    lastmodified_by = models.CharField(max_length=100, default='system')
    lastmodified_date = models.DateTimeField(auto_now=True)
    is_password_set = models.BooleanField(default=False)
    role = models.CharField(max_length=100, default='Employee')

    class Meta:
        db_table = 'backend_diagnostics_user'

    def save(self, *args, **kwargs):
        """Ensure password is hashed before saving"""
        if self.password and not self.password.startswith("pbkdf2_sha256$"):
            self.password = make_password(self.password)
        super().save(*args, **kwargs)

    def __str__(self):
        return self.employeeId


def extract_actor_id(request):
    """
    Bulletproof extraction of actor ID (Employee ID / Admin Username) from HTTP Request context.
    """
    if not request:
        return "Admin"

    # 1. From authenticated_employee_id attached by @token_required decorator
    actor_id = getattr(request, 'authenticated_employee_id', None)
    if actor_id:
        return str(actor_id)

    # 2. From token_payload
    payload = getattr(request, 'token_payload', None)
    if payload:
        actor_id = payload.get('employee_id') or payload.get('name') or payload.get('sub')
        if actor_id:
            return str(actor_id)

    # 3. Direct JWT Header Decoding
    try:
        auth_header = None
        if hasattr(request, 'headers'):
            auth_header = request.headers.get('Authorization') or request.headers.get('x-user-id') or request.headers.get('x-employee-id')
        if not auth_header and hasattr(request, 'META'):
            auth_header = request.META.get('HTTP_AUTHORIZATION') or request.META.get('HTTP_X_EMPLOYEE_ID') or request.META.get('HTTP_X_USER_ID')

        if auth_header:
            if auth_header.startswith('Bearer ') or len(auth_header) > 20:
                parts = auth_header.split()
                token = parts[1] if len(parts) == 2 else parts[0]
                from employees.token_utils import decode_employee_token
                dec_payload = decode_employee_token(token)
                if dec_payload:
                    actor_id = dec_payload.get('employee_id') or dec_payload.get('name') or dec_payload.get('role')
                    if actor_id:
                        return str(actor_id)
            else:
                return str(auth_header)
    except Exception as e:
        print("extract_actor_id exception:", e)

    # 4. From custom headers (X-Employee-ID)
    if hasattr(request, 'headers'):
        actor_id = request.headers.get('X-Employee-ID') or request.headers.get('x-employee-id')
        if actor_id:
            return str(actor_id)
    if hasattr(request, 'META'):
        actor_id = request.META.get('HTTP_X_EMPLOYEE_ID') or request.META.get('HTTP_X_USER_ID')
        if actor_id:
            return str(actor_id)

    # 5. From Django Session User or Request Data
    if hasattr(request, 'user') and getattr(request.user, 'is_authenticated', False):
        actor_id = getattr(request.user, 'username', None) or getattr(request.user, 'first_name', None)
        if actor_id:
            return str(actor_id)

    if hasattr(request, 'data') and isinstance(request.data, dict) and request.data:
        actor_id = request.data.get('sent_by') or request.data.get('reviewer_name') or request.data.get('employee_id') or request.data.get('created_by') or request.data.get('user_id')
        if actor_id:
            return str(actor_id)
    elif hasattr(request, 'data') and isinstance(request.data, list) and len(request.data) > 0 and isinstance(request.data[0], dict):
        actor_id = request.data[0].get('actor_name') or request.data[0].get('created_by') or request.data[0].get('lastmodified_by') or request.data[0].get('employee_id')
        if actor_id:
            return str(actor_id)

    # Fallback to Admin if non-token/system action
    return "Admin"


class AuditableModel(models.Model):
    """
    Abstract base class providing standard enterprise audit tracking:
    created_by, created_date, lastmodified_by, lastmodified_date
    """
    created_by = models.CharField(max_length=150, null=True, blank=True, help_text="User ID/Name who created this record")
    created_date = models.DateTimeField(auto_now_add=True, null=True, blank=True)
    lastmodified_by = models.CharField(max_length=150, null=True, blank=True, help_text="User ID/Name who last modified this record")
    lastmodified_date = models.DateTimeField(auto_now=True, null=True, blank=True)

    class Meta:
        abstract = True

    def save(self, *args, **kwargs):
        # Guarantee created_by and lastmodified_by are never null
        if not self.created_by:
            self.created_by = "50867"
        if not self.lastmodified_by:
            self.lastmodified_by = getattr(self, 'created_by', '50867') or "50867"
        super().save(*args, **kwargs)

    def save_with_audit(self, request=None, user_id=None, *args, **kwargs):
        actor_id = user_id or extract_actor_id(request)

        if not self.created_by:
            self.created_by = str(actor_id)
        self.lastmodified_by = str(actor_id)

        self.save(*args, **kwargs)
        print(f"🔑 AUDIT SAVED -> Model: {self.__class__.__name__} | CreatedBy: {self.created_by} | LastModifiedBy: {self.lastmodified_by}")
        return self







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

class Register(AuditableModel):
    id               = models.AutoField(primary_key=True)
    name             = models.CharField(max_length=500)
    role             = models.CharField(max_length=500)
    password         = models.CharField(max_length=500)
    confirmPassword  = models.CharField(max_length=500)
    allowed_ip       = models.CharField(max_length=45, null=True, blank=True)
    employee_id          = models.CharField(max_length=50, null=True, blank=True)
    department           = models.CharField(max_length=100, null=True, blank=True)
    assigned_departments = models.CharField(max_length=500, null=True, blank=True)
    device               = models.CharField(max_length=255, unique=True, null=True, blank=True)
    fingerprint          = models.CharField(max_length=255, unique=True, null=True, blank=True)

    def __str__(self):
        return f"{self.name} ({self.role}) — IP: {self.allowed_ip or 'N/A'}"

class AllowedDevice(AuditableModel):
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

class Shift(AuditableModel):
    id         = models.AutoField(primary_key=True)
    name       = models.CharField(max_length=50, unique=True)
    start_time = models.TimeField()
    end_time   = models.TimeField()
    is_active  = models.BooleanField(default=True)

    def __str__(self):
        return f"{self.name} ({self.start_time} - {self.end_time})"

class Department(AuditableModel):
    id     = models.AutoField(primary_key=True)
    name   = models.CharField(max_length=100, unique=True)
    shifts = models.ManyToManyField(Shift, related_name='departments', blank=True)

    def __str__(self):
        return self.name

def generate_shiftschedule_id():
    try:
        from pymongo import MongoClient
        import os
        client = MongoClient(os.environ.get('GLOBAL_DB_HOST', 'mongodb://admin:SMRFT%40test@45.120.136.230:27017/'))
        db = client[os.environ.get('GLOBAL_DB_NAME', 'Global')]
        max_doc = db['employees_employeeshiftschedule'].find_one(
            {'id': {'$ne': None}},
            sort=[('id', -1)]
        )
        if max_doc and max_doc.get('id'):
            return int(max_doc['id']) + 1
    except Exception:
        pass
    return 1

class EmployeeShiftSchedule(AuditableModel):
    id       = models.IntegerField(primary_key=True, default=generate_shiftschedule_id, editable=False)
    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name='shift_schedules')
    shift    = models.ForeignKey(Shift, on_delete=models.CASCADE)
    date     = models.DateField()
    created_by = models.CharField(max_length=150, null=True, blank=True)
    created_date = models.DateTimeField(auto_now_add=True, null=True, blank=True)
    lastmodified_by = models.CharField(max_length=150, null=True, blank=True)
    lastmodified_date = models.DateTimeField(auto_now=True, null=True, blank=True)
    
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

class LeaveType(AuditableModel):
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

class LeaveRequest(AuditableModel):
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

class CanteenItem(AuditableModel):
    id = models.AutoField(primary_key=True)
    name = models.CharField(max_length=100, default='Tea')
    code = models.CharField(max_length=20, default='TEA', unique=True)
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return f"{self.name} ({self.code})"

class CanteenQuotaRule(AuditableModel):
    id = models.AutoField(primary_key=True)
    max_daily_quota = models.IntegerField(default=1)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Daily Quota: {self.max_daily_quota} token(s)"

class CanteenTokenIssue(AuditableModel):
    STATUS_CHOICES = (('ISSUED', 'ISSUED'), ('REDEEMED', 'REDEEMED'), ('CANCELLED', 'CANCELLED'))

    id = models.AutoField(primary_key=True)
    token_number = models.CharField(max_length=50, unique=True)
    employee_id = models.CharField(max_length=50)
    employee_name = models.CharField(max_length=150, null=True, blank=True)
    department = models.CharField(max_length=100, null=True, blank=True)
    item_name = models.CharField(max_length=50, default='Tea')
    issued_at = models.DateTimeField(auto_now_add=True)
    confidence = models.FloatField(null=True, blank=True)
    device_id = models.CharField(max_length=50, null=True, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='ISSUED')
    reprint_count = models.IntegerField(default=0)

    def __str__(self):
        return f"{self.token_number} - {self.employee_id} ({self.employee_name}) @ {self.issued_at}"

class Notification(AuditableModel):
    CATEGORY_CHOICES = (
        ('leave', 'Leave Update'),
        ('shift', 'Shift Roster'),
        ('canteen', 'Canteen Token'),
        ('announcement', 'Announcement'),
        ('general', 'General Alert'),
    )

    id = models.AutoField(primary_key=True)
    employee_id = models.CharField(max_length=50, db_index=True)
    title = models.CharField(max_length=255)
    message = models.TextField()
    category = models.CharField(max_length=20, choices=CATEGORY_CHOICES, default='general')
    is_read = models.BooleanField(default=False)
    action_url = models.CharField(max_length=255, blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)


    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.employee_id} - {self.title} (Read: {self.is_read})"