import base64
from datetime import datetime
import pytz
from django.utils import timezone
from django.db import models
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from employees.models import Employee, CanteenItem, CanteenQuotaRule, CanteenTokenIssue, SpoofingAttempt
from employees.face_utils import (
    base64_to_encoding,
    SpoofingDetectedError,
    match_face_1_to_n
)
from employees.views.attendance import get_optimized_encodings

from employees.decorators import token_required

IST = pytz.timezone('Asia/Kolkata')


@api_view(['POST'])
@permission_classes([AllowAny])
def issue_canteen_token(request):

    """
    Scans employee face, verifies identity & anti-spoofing, checks daily quota (1 token per employee per day),
    and issues a Canteen Tea Token.
    """
    try:
        data = request.data
        image_b64 = data.get('image') or data.get('image_b64')
        device_id = data.get('device_id', 'CANTEEN_KIOSK_1')
        item_name = data.get('item_name', 'Tea')

        if not image_b64:
            return Response({
                'status': 'error',
                'message': 'Image is required for face recognition'
            }, status=400)

        # 1. Extract face encoding & check liveness (anti-spoofing)
        try:
            res = base64_to_encoding(image_b64)
            if isinstance(res, tuple):
                face_encoding, is_real = res
            else:
                face_encoding, is_real = res, True
        except SpoofingDetectedError:
            # Log spoofing attempt
            SpoofingAttempt.objects.create(
                image=image_b64[:200],
                device_id=device_id,
                category="SPFM_CANTEEN"
            )
            return Response({
                'status': 'error',
                'error_code': 'SPOOF_DETECTED',
                'message': 'Fake face or photo detected! Real face required.'
            }, status=400)
        except Exception as e:
            return Response({
                'status': 'error',
                'error_code': 'NO_FACE',
                'message': str(e) or 'No clear face detected in the image.'
            }, status=400)

        if not face_encoding:
            return Response({
                'status': 'error',
                'error_code': 'NO_FACE',
                'message': 'No face detected in the frame.'
            }, status=400)


        # 2. Match 1:N against active employees
        matrix, employees_meta = get_optimized_encodings()

        if len(employees_meta) == 0:
            return Response({
                'status': 'error',
                'error_code': 'NO_BIOMETRICS',
                'message': 'No active registered employee faces in database.'
            }, status=404)

        match, distance, err_reason = match_face_1_to_n(face_encoding, matrix, employees_meta, threshold=0.45)

        if err_reason or not match:
            return Response({
                'status': 'error',
                'error_code': 'FACE_NOT_MATCHED',
                'message': err_reason or 'Face not recognized. Please register biometrics or scan again.'
            }, status=404)


        matched_employee_id = match['employee_id']
        matched_employee_name = match['name']

        dept_name = 'General'
        try:
            emp_obj = Employee.objects.get(employee_id=matched_employee_id)
        except Employee.DoesNotExist:
            pass

        # 3. Check Daily Quota (Exactly 1 token per day per employee)
        today = timezone.now().astimezone(IST).date()
        today_start = IST.localize(datetime.combine(today, datetime.min.time()))
        today_end = IST.localize(datetime.combine(today, datetime.max.time()))

        existing_tokens = CanteenTokenIssue.objects.filter(
            employee_id=matched_employee_id,
            issued_at__range=(today_start, today_end)
        )

        quota_rule = CanteenQuotaRule.objects.first()

        max_quota = quota_rule.max_daily_quota if quota_rule else 1

        if existing_tokens.count() >= max_quota:
            last_token = existing_tokens.order_by('-issued_at').first()
            time_str = last_token.issued_at.astimezone(IST).strftime('%I:%M %p') if last_token else ''
            
            # Check single reprint limit per day (max 1 reprint)
            curr_reprint_count = getattr(last_token, 'reprint_count', 0)
            if curr_reprint_count >= 1:
                return Response({
                    'status': 'error',
                    'error_code': 'REPRINT_LIMIT_REACHED',
                    'message': f"Today's tea token already claimed & reprint limit reached! (Max 1 reprint per day)",
                    'employee': {
                        'employee_id': matched_employee_id,
                        'name': matched_employee_name,
                    },
                    'can_reprint': False,
                    'reprint_count': curr_reprint_count,
                    'remaining_quota': 0,
                    'last_token_number': last_token.token_number if last_token else None,
                    'last_issued_at': last_token.issued_at.astimezone(IST).strftime('%Y-%m-%d %I:%M:%S %p') if last_token else None
                }, status=400)

            # Record the 1-time reprint
            last_token.reprint_count = curr_reprint_count + 1
            last_token.save()

            return Response({
                'status': 'error',
                'error_code': 'QUOTA_EXCEEDED',
                'message': f"Today's tea token already claimed! ({time_str}) - Re-printing 1/1 Token",
                'employee': {
                    'employee_id': matched_employee_id,
                    'name': matched_employee_name,
                },
                'can_reprint': True,
                'reprint_count': last_token.reprint_count,
                'remaining_quota': 0,
                'last_token_number': last_token.token_number if last_token else None,
                'last_issued_at': last_token.issued_at.astimezone(IST).strftime('%Y-%m-%d %I:%M:%S %p') if last_token else None
            }, status=400)


        # 4. Generate unique sequential token number
        today_str = today.strftime('%Y%m%d')
        daily_count = CanteenTokenIssue.objects.filter(issued_at__range=(today_start, today_end)).count() + 1
        token_number = f"TEA-{today_str}-{daily_count:04d}"

        token_record = CanteenTokenIssue(
            token_number=token_number,
            employee_id=matched_employee_id,
            employee_name=matched_employee_name,
            department=dept_name,
            item_name=item_name,
            confidence=round(float(distance), 4) if distance is not None else None,

            device_id=device_id,
            status='ISSUED'
        )
        token_record.save_with_audit(request)

        return Response({
            'status': 'success',
            'message': 'Tea token issued successfully!',
            'token': {
                'token_number': token_record.token_number,
                'item_name': token_record.item_name,
                'issued_at': token_record.issued_at.astimezone(IST).strftime('%Y-%m-%d %I:%M:%S %p'),
                'status': token_record.status,
            },
            'employee': {
                'employee_id': matched_employee_id,
                'name': matched_employee_name,
                'department': dept_name
            },
            'remaining_quota': max_quota - 1
        }, status=200)

    except Exception as e:
        import traceback
        print("🚨 CANTEEN ISSUE ERROR TRACEBACK:")
        traceback.print_exc()
        return Response({
            'status': 'error',
            'message': f"Canteen Token Issue Error: {str(e)}"
        }, status=500)


@api_view(['GET'])
@permission_classes([AllowAny])
@token_required
def get_canteen_today_summary(request):
    try:
        today = timezone.now().astimezone(IST).date()
        today_start = IST.localize(datetime.combine(today, datetime.min.time()))
        today_end = IST.localize(datetime.combine(today, datetime.max.time()))

        tokens = CanteenTokenIssue.objects.filter(issued_at__range=(today_start, today_end))

        total_issued = tokens.count()
        total_redeemed = tokens.filter(status='REDEEMED').count()
        total_pending = tokens.filter(status='ISSUED').count()

        return Response({
            'status': 'success',
            'date': today.strftime('%Y-%m-%d'),
            'summary': {
                'total_issued': total_issued,
                'total_redeemed': total_redeemed,
                'total_pending': total_pending
            }
        }, status=200)

    except Exception as e:
        return Response({'status': 'error', 'message': str(e)}, status=500)


@api_view(['GET'])
@permission_classes([AllowAny])
@token_required
def get_canteen_token_history(request):
    try:
        employee_id = request.query_params.get('employee_id')
        date_str = request.query_params.get('date')

        queryset = CanteenTokenIssue.objects.all().order_by('-issued_at')

        if employee_id:
            queryset = queryset.filter(employee_id=employee_id)

        if date_str:
            target_date = datetime.strptime(date_str, '%Y-%m-%d').date()
            t_start = IST.localize(datetime.combine(target_date, datetime.min.time()))
            t_end = IST.localize(datetime.combine(target_date, datetime.max.time()))
            queryset = queryset.filter(issued_at__range=(t_start, t_end))

        tokens_data = []
        for t in queryset[:200]:
            tokens_data.append({
                'id': t.id,
                'token_number': t.token_number,
                'employee_id': t.employee_id,
                'employee_name': t.employee_name,
                'department': t.department,
                'item_name': t.item_name,
                'issued_at': t.issued_at.isoformat() if t.issued_at else '',
                'issued_at_formatted': t.issued_at.astimezone(IST).strftime('%Y-%m-%d %I:%M:%S %p') if t.issued_at else '',
                'confidence': t.confidence,
                'status': t.status
            })

        return Response({
            'status': 'success',
            'count': len(tokens_data),
            'tokens': tokens_data
        }, status=200)

    except Exception as e:
        return Response({'status': 'error', 'message': str(e)}, status=500)


@api_view(['GET', 'POST'])
@permission_classes([AllowAny])
@token_required
def manage_canteen_rules(request):
    """
    GET or update canteen token quota rules.
    """
    rule, _ = CanteenQuotaRule.objects.get_or_create(id=1, defaults={'max_daily_quota': 1})

    if request.method == 'POST':
        max_quota = request.data.get('max_daily_quota')
        if max_quota is not None:
            rule.max_daily_quota = int(max_quota)
            rule.save_with_audit(request)
            return Response({
                'status': 'success',
                'message': 'Canteen rules updated successfully!',
                'max_daily_quota': rule.max_daily_quota
            }, status=200)

    return Response({
        'status': 'success',
        'max_daily_quota': rule.max_daily_quota,
        'is_active': rule.is_active
    }, status=200)
