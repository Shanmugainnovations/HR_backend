import os
from django.http import JsonResponse
from rest_framework.decorators import api_view, permission_classes
from employees.permissions import HasRoleAndDataPermission
from employees.models import Register
from employees.views.common.utils import (
    get_mongo_client,
    get_active_user_employee_ids,
    get_inactive_employee_ids,
    get_request_user_approval_context
)


@api_view(['GET'])
@permission_classes([HasRoleAndDataPermission])
def get_approver_hierarchy(request):
    """
    Returns the organization 4-tier hierarchy:
    AVP -> HOD -> Incharge -> Departments (with employee counts and supervisor profiles).
    Role-based visibility:
    - Admin / HR: Sees complete organization (All AVPs, HODs, Incharges, Departments + Direct HODs).
    - AVP: Sees only their AVP portfolio and subordinates (their HODs -> their Incharges -> their Departments).
    - HOD: Sees only their HOD division (their Incharges -> their Departments) + reporting AVP context.
    - Incharge: Sees only their unit (their managed Departments) + reporting HOD/AVP context.
    - Employee: Sees their department reporting chain.
    """
    try:
        client = get_mongo_client()
        global_db_name = os.environ.get('GLOBAL_DB_NAME', 'Global')
        db = client[global_db_name] if client else None

        # 1. Department code to name lookup
        dept_map = {}
        if db is not None:
            for d in db['backend_diagnostics_Departments'].find({}, {'department_code': 1, 'department_name': 1, '_id': 0}):
                code = d.get('department_code')
                if code:
                    dept_map[code] = d.get('department_name', code)

        # 2. Active employees count per department & profiles
        active_user_ids = get_active_user_employee_ids()
        inactive_ids = get_inactive_employee_ids()
        dept_counts = {}
        profile_map = {}

        if db is not None:
            profiles = list(db['backend_diagnostics_profile'].find({}, {
                'employeeId': 1, 'employeeName': 1, 'department': 1,
                'designation': 1, 'email': 1, 'mobileNumber': 1,
                'profileImage': 1, 'is_active': 1, 'status': 1, '_id': 0
            }))
            for p in profiles:
                eid = str(p.get('employeeId') or '').strip()
                if not eid or (active_user_ids and eid not in active_user_ids) or eid in inactive_ids:
                    continue
                if p.get('is_active') is False:
                    continue
                p_status = str(p.get('status') or '').lower()
                if p_status in ['inactive', 'disabled', 'resigned', 'left']:
                    continue

                profile_map[eid] = {
                    'name': p.get('employeeName') or '',
                    'designation': p.get('designation') or '',
                    'email': p.get('email') or '',
                    'mobile': p.get('mobileNumber') or '',
                    'profileImage': p.get('profileImage') or None,
                    'department': str(p.get('department') or '').strip()
                }

                raw_depts = str(p.get('department') or '').strip()
                for c in raw_depts.split(','):
                    c = c.strip()
                    if c:
                        dept_counts[c] = dept_counts.get(c, 0) + 1

        # 3. Query AVPs, HODs, Incharges from Register
        avp_records = Register.objects.filter(role__in=['HR-R-AVP', 'AVP'])
        hod_records = Register.objects.filter(role__in=['HR-R-HOD', 'HOD'])
        inc_records = Register.objects.filter(role__in=['HR-R-INC', 'Incharge', 'INCHARGE'])

        # Build Incharges
        incharges = []
        seen_inc_eids = set()
        for i in inc_records:
            eid = str(i.employee_id or '').strip()
            if not eid or eid in seen_inc_eids:
                continue
            seen_inc_eids.add(eid)

            depts = set()
            if i.department:
                for d in i.department.split(','):
                    if d.strip():
                        depts.add(d.strip())
            if i.assigned_departments:
                for d in i.assigned_departments.split(','):
                    if d.strip():
                        depts.add(d.strip())

            sup_hods = [x.strip() for x in str(i.supervising_hod_ids or '').split(',') if x.strip()]
            parent_appr = str(i.parent_approver_id or '').strip()
            prof = profile_map.get(eid, {})

            incharges.append({
                'id': i.id,
                'employee_id': eid,
                'name': prof.get('name') or i.name or 'Incharge',
                'role': 'INCHARGE',
                'primary_department_code': str(i.department or '').split(',')[0].strip() if i.department else '',
                'departments': sorted(list(depts)),
                'supervising_hod_ids': sup_hods,
                'parent_approver_id': parent_appr,
                'profileImage': prof.get('profileImage'),
                'designation': prof.get('designation') or 'Incharge',
                'email': prof.get('email') or '',
                'mobile': prof.get('mobile') or '',
            })

        # Build HODs
        hods = []
        seen_hod_eids = set()
        for h in hod_records:
            eid = str(h.employee_id or '').strip()
            if not eid or eid in seen_hod_eids:
                continue
            seen_hod_eids.add(eid)

            depts = set()
            if h.department:
                for d in h.department.split(','):
                    if d.strip():
                        depts.add(d.strip())
            if h.assigned_departments:
                for d in h.assigned_departments.split(','):
                    if d.strip():
                        depts.add(d.strip())

            sup_incs = [x.strip() for x in str(h.supervising_incharge_ids or '').split(',') if x.strip()]
            parent_appr = str(h.parent_approver_id or '').strip()
            prof = profile_map.get(eid, {})

            hods.append({
                'id': h.id,
                'employee_id': eid,
                'name': prof.get('name') or h.name or 'Department Head',
                'role': 'HOD',
                'primary_department_code': str(h.department or '').split(',')[0].strip() if h.department else '',
                'departments': sorted(list(depts)),
                'supervising_incharge_ids': sup_incs,
                'parent_approver_id': parent_appr,
                'profileImage': prof.get('profileImage'),
                'designation': prof.get('designation') or 'Head of Department',
                'email': prof.get('email') or '',
                'mobile': prof.get('mobile') or '',
            })

        # Build AVPs
        avps = []
        seen_avp_eids = set()
        for a in avp_records:
            eid = str(a.employee_id or '').strip()
            if not eid or eid in seen_avp_eids:
                continue
            seen_avp_eids.add(eid)

            depts = set()
            if a.department:
                for d in a.department.split(','):
                    if d.strip():
                        depts.add(d.strip())
            if a.assigned_departments:
                for d in a.assigned_departments.split(','):
                    if d.strip():
                        depts.add(d.strip())

            prof = profile_map.get(eid, {})
            avps.append({
                'id': a.id,
                'employee_id': eid,
                'name': prof.get('name') or a.name or 'Assistant Vice President',
                'role': 'AVP',
                'primary_department_code': str(a.department or '').split(',')[0].strip() if a.department else '',
                'departments': sorted(list(depts)),
                'profileImage': prof.get('profileImage'),
                'designation': prof.get('designation') or 'Assistant Vice President',
                'email': prof.get('email') or '',
                'mobile': prof.get('mobile') or '',
            })

        # 4. Construct complete 4-tier tree: AVP -> HOD -> Incharge -> Departments
        # Helper to construct an HOD sub-tree
        def build_hod_subtree(h, restrict_depts=None):
            h_dept_set = set(h['departments'])
            if restrict_depts:
                h_dept_set = h_dept_set.intersection(restrict_depts)

            matched_incharges = []
            covered_depts_by_incs = set()

            for inc in incharges:
                inc_dept_set = set(inc['departments'])
                overlap = inc_dept_set.intersection(h_dept_set)
                is_explicit = (
                    (h['employee_id'] in inc['supervising_hod_ids']) or
                    (h['employee_id'] == inc['parent_approver_id']) or
                    (inc['employee_id'] in h['supervising_incharge_ids'])
                )

                if is_explicit or len(overlap) > 0:
                    target_depts = sorted(list(overlap if overlap else inc_dept_set.intersection(h_dept_set)))
                    if not target_depts and is_explicit:
                        target_depts = sorted(list(inc_dept_set))

                    covered_depts_by_incs.update(target_depts)

                    inc_dept_details = []
                    inc_staff_sum = 0
                    for dcode in target_depts:
                        emp_cnt = dept_counts.get(dcode, 0)
                        inc_staff_sum += emp_cnt
                        inc_dept_details.append({
                            'department_code': dcode,
                            'department_name': dept_map.get(dcode, dcode),
                            'employee_count': emp_cnt
                        })

                    matched_incharges.append({
                        'employee_id': inc['employee_id'],
                        'name': inc['name'],
                        'role': 'INCHARGE',
                        'designation': inc['designation'],
                        'profileImage': inc['profileImage'],
                        'email': inc['email'],
                        'mobile': inc['mobile'],
                        'departments_count': len(inc_dept_details),
                        'total_staff_count': inc_staff_sum,
                        'departments': inc_dept_details
                    })

            direct_dept_codes = sorted(list(h_dept_set - covered_depts_by_incs))
            direct_dept_details = []
            direct_staff_sum = 0
            for dcode in direct_dept_codes:
                emp_cnt = dept_counts.get(dcode, 0)
                direct_staff_sum += emp_cnt
                direct_dept_details.append({
                    'department_code': dcode,
                    'department_name': dept_map.get(dcode, dcode),
                    'employee_count': emp_cnt
                })

            hod_staff_total = sum(dept_counts.get(d, 0) for d in h_dept_set)

            return {
                'hod_id': h['employee_id'],
                'hod_name': h['name'],
                'role': 'HOD',
                'designation': h['designation'],
                'profileImage': h['profileImage'],
                'email': h['email'],
                'mobile': h['mobile'],
                'primary_department_code': h['primary_department_code'],
                'primary_department_name': dept_map.get(h['primary_department_code'], h['primary_department_code']),
                'total_departments_count': len(h_dept_set),
                'incharges_count': len(matched_incharges),
                'total_staff_count': hod_staff_total,
                'incharges': matched_incharges,
                'direct_departments': direct_dept_details,
                'all_department_codes': sorted(list(h_dept_set))
            }

        # Build full AVP trees
        avp_trees = []
        assigned_hod_eids = set()
        assigned_incharge_eids_global = set()

        for a in avps:
            a_dept_set = set(a['departments'])
            matched_hod_nodes = []
            covered_depts_by_hods = set()

            for h in hods:
                h_dept_set = set(h['departments'])
                overlap = h_dept_set.intersection(a_dept_set)
                is_explicit = (h['parent_approver_id'] == a['employee_id'])

                if is_explicit or len(overlap) > 0:
                    assigned_hod_eids.add(h['employee_id'])
                    # Subtree for this HOD
                    hod_subtree = build_hod_subtree(h, restrict_depts=a_dept_set if len(overlap) > 0 else None)
                    matched_hod_nodes.append(hod_subtree)
                    covered_depts_by_hods.update(hod_subtree['all_department_codes'])
                    for m_inc in hod_subtree['incharges']:
                        assigned_incharge_eids_global.add(m_inc['employee_id'])

            # Direct Incharges under AVP (departments under AVP that have Incharge but no HOD)
            direct_incharge_nodes = []
            covered_depts_by_direct_incs = set()
            for inc in incharges:
                if inc['employee_id'] not in assigned_incharge_eids_global:
                    inc_dept_set = set(inc['departments'])
                    overlap = inc_dept_set.intersection(a_dept_set - covered_depts_by_hods)
                    if len(overlap) > 0:
                        assigned_incharge_eids_global.add(inc['employee_id'])
                        inc_dept_details = []
                        inc_staff_sum = 0
                        for dcode in sorted(list(overlap)):
                            covered_depts_by_direct_incs.add(dcode)
                            emp_cnt = dept_counts.get(dcode, 0)
                            inc_staff_sum += emp_cnt
                            inc_dept_details.append({
                                'department_code': dcode,
                                'department_name': dept_map.get(dcode, dcode),
                                'employee_count': emp_cnt
                            })
                        direct_incharge_nodes.append({
                            'employee_id': inc['employee_id'],
                            'name': inc['name'],
                            'role': 'INCHARGE',
                            'designation': inc['designation'],
                            'profileImage': inc['profileImage'],
                            'email': inc['email'],
                            'mobile': inc['mobile'],
                            'departments_count': len(inc_dept_details),
                            'total_staff_count': inc_staff_sum,
                            'departments': inc_dept_details
                        })

            # Direct Departments under AVP (neither HOD nor Incharge)
            direct_dept_codes = sorted(list(a_dept_set - covered_depts_by_hods - covered_depts_by_direct_incs))
            direct_dept_details = []
            direct_staff_sum = 0
            for dcode in direct_dept_codes:
                emp_cnt = dept_counts.get(dcode, 0)
                direct_staff_sum += emp_cnt
                direct_dept_details.append({
                    'department_code': dcode,
                    'department_name': dept_map.get(dcode, dcode),
                    'employee_count': emp_cnt
                })

            avp_staff_total = sum(dept_counts.get(d, 0) for d in a_dept_set)

            avp_trees.append({
                'avp_id': a['employee_id'],
                'avp_name': a['name'],
                'role': 'AVP',
                'designation': a['designation'],
                'profileImage': a['profileImage'],
                'email': a['email'],
                'mobile': a['mobile'],
                'primary_department_code': a['primary_department_code'],
                'primary_department_name': dept_map.get(a['primary_department_code'], a['primary_department_code']),
                'total_departments_count': len(a_dept_set),
                'hods_count': len(matched_hod_nodes),
                'direct_incharges_count': len(direct_incharge_nodes),
                'total_staff_count': avp_staff_total,
                'hods': matched_hod_nodes,
                'direct_incharges': direct_incharge_nodes,
                'direct_departments': direct_dept_details,
                'all_department_codes': sorted(list(a_dept_set))
            })

        # HODs not under any AVP (Direct Institutional HODs)
        direct_hod_nodes = []
        for h in hods:
            if h['employee_id'] not in assigned_hod_eids:
                hod_subtree = build_hod_subtree(h)
                direct_hod_nodes.append(hod_subtree)
                for m_inc in hod_subtree['incharges']:
                    assigned_incharge_eids_global.add(m_inc['employee_id'])

        # Incharges not under any HOD or AVP
        unassigned_incharge_nodes = []
        for inc in incharges:
            if inc['employee_id'] not in assigned_incharge_eids_global:
                inc_dept_details = []
                inc_staff_sum = 0
                for dcode in inc['departments']:
                    emp_cnt = dept_counts.get(dcode, 0)
                    inc_staff_sum += emp_cnt
                    inc_dept_details.append({
                        'department_code': dcode,
                        'department_name': dept_map.get(dcode, dcode),
                        'employee_count': emp_cnt
                    })
                unassigned_incharge_nodes.append({
                    'employee_id': inc['employee_id'],
                    'name': inc['name'],
                    'role': 'INCHARGE',
                    'designation': inc['designation'],
                    'profileImage': inc['profileImage'],
                    'email': inc['email'],
                    'mobile': inc['mobile'],
                    'departments_count': len(inc_dept_details),
                    'total_staff_count': inc_staff_sum,
                    'departments': inc_dept_details
                })

        # 5. Extract User Context & Role-Based Filtering
        user_ctx = get_request_user_approval_context(request)
        logged_in_eid = str(user_ctx.get('employee_id') or '').strip()

        # Check if Admin wants to view specific branch
        requested_scope = request.GET.get('scope') or ''
        requested_avp_id = request.GET.get('avp_id') or ''
        requested_hod_id = request.GET.get('hod_id') or ''

        # Determine effective scope
        effective_scope = 'ALL'
        if user_ctx.get('is_avp'):
            effective_scope = 'AVP'
        elif user_ctx.get('is_hod'):
            effective_scope = 'HOD'
        elif user_ctx.get('is_incharge'):
            effective_scope = 'INCHARGE'
        elif user_ctx.get('is_admin'):
            effective_scope = 'ALL'
            if requested_avp_id:
                effective_scope = 'AVP'
                logged_in_eid = requested_avp_id
            elif requested_hod_id:
                effective_scope = 'HOD'
                logged_in_eid = requested_hod_id
        else:
            # Regular employee
            effective_scope = 'EMPLOYEE'

        # Filter tree according to effective scope
        filtered_avp_trees = []
        filtered_direct_hods = []
        filtered_unassigned_incs = []
        reporting_chain = None

        if effective_scope == 'ALL':
            filtered_avp_trees = avp_trees
            filtered_direct_hods = direct_hod_nodes
            filtered_unassigned_incs = unassigned_incharge_nodes

        elif effective_scope == 'AVP':
            # Match AVP by employee_id
            matched_avp = next((a for a in avp_trees if a['avp_id'] == logged_in_eid), None)
            if matched_avp:
                filtered_avp_trees = [matched_avp]
            else:
                # Fallback: if AVP record matched user context
                filtered_avp_trees = avp_trees[:1] if avp_trees else []

        elif effective_scope == 'HOD':
            # Match HOD by employee_id
            # Also find reporting AVP
            target_hod_node = None
            parent_avp_info = None

            # Search in AVP trees first
            for avp_tree in avp_trees:
                for h in avp_tree['hods']:
                    if h['hod_id'] == logged_in_eid:
                        target_hod_node = h
                        parent_avp_info = {
                            'role': 'AVP',
                            'name': avp_tree['avp_name'],
                            'employee_id': avp_tree['avp_id'],
                            'designation': avp_tree['designation'],
                            'email': avp_tree['email'],
                            'profileImage': avp_tree['profileImage']
                        }
                        break
                if target_hod_node:
                    break

            if not target_hod_node:
                # Check direct HODs
                target_hod_node = next((h for h in direct_hod_nodes if h['hod_id'] == logged_in_eid), None)

            if target_hod_node:
                filtered_direct_hods = [target_hod_node]
                reporting_chain = {
                    'level': 'HOD',
                    'reporting_avp': parent_avp_info
                }
            else:
                filtered_direct_hods = direct_hod_nodes[:1] if direct_hod_nodes else []

        elif effective_scope == 'INCHARGE':
            # Match Incharge by employee_id
            target_inc_node = None
            parent_hod_info = None
            parent_avp_info = None

            # Search inside AVP trees
            for avp_tree in avp_trees:
                for h in avp_tree['hods']:
                    for inc in h['incharges']:
                        if inc['employee_id'] == logged_in_eid:
                            target_inc_node = inc
                            parent_hod_info = {
                                'role': 'HOD',
                                'name': h['hod_name'],
                                'employee_id': h['hod_id'],
                                'designation': h['designation']
                            }
                            parent_avp_info = {
                                'role': 'AVP',
                                'name': avp_tree['avp_name'],
                                'employee_id': avp_tree['avp_id']
                            }
                            break
                    if target_inc_node:
                        break
                if target_inc_node:
                    break

            # Search inside direct HODs
            if not target_inc_node:
                for h in direct_hod_nodes:
                    for inc in h['incharges']:
                        if inc['employee_id'] == logged_in_eid:
                            target_inc_node = inc
                            parent_hod_info = {
                                'role': 'HOD',
                                'name': h['hod_name'],
                                'employee_id': h['hod_id'],
                                'designation': h['designation']
                            }
                            break
                    if target_inc_node:
                        break

            # Search unassigned incharges
            if not target_inc_node:
                target_inc_node = next((i for i in unassigned_incharge_nodes if i['employee_id'] == logged_in_eid), None)

            if target_inc_node:
                filtered_unassigned_incs = [target_inc_node]
                reporting_chain = {
                    'level': 'INCHARGE',
                    'reporting_hod': parent_hod_info,
                    'reporting_avp': parent_avp_info
                }
            else:
                filtered_unassigned_incs = unassigned_incharge_nodes[:1] if unassigned_incharge_nodes else []

        elif effective_scope == 'EMPLOYEE':
            # Find employee's department and build their line to Incharge -> HOD -> AVP
            emp_prof = profile_map.get(logged_in_eid, {})
            emp_depts = [d.strip() for d in str(emp_prof.get('department') or '').split(',') if d.strip()]
            reporting_chain = {
                'level': 'EMPLOYEE',
                'employee_name': emp_prof.get('name'),
                'department_code': emp_depts[0] if emp_depts else '',
                'department_name': dept_map.get(emp_depts[0], emp_depts[0]) if emp_depts else ''
            }
            # Find which AVP covers this dept
            if emp_depts:
                target_code = emp_depts[0]
                for a in avp_trees:
                    if target_code in a['all_department_codes']:
                        filtered_avp_trees = [a]
                        break
                if not filtered_avp_trees:
                    for h in direct_hod_nodes:
                        if target_code in h['all_department_codes']:
                            filtered_direct_hods = [h]
                            break

        # Calculate dynamic statistics based on effective scope
        total_staff_in_scope = 0
        total_depts_in_scope = set()
        total_hods_in_scope = 0
        total_incs_in_scope = 0

        for a in filtered_avp_trees:
            total_staff_in_scope += a['total_staff_count']
            total_depts_in_scope.update(a['all_department_codes'])
            total_hods_in_scope += len(a['hods'])
            for h in a['hods']:
                total_incs_in_scope += len(h['incharges'])
            total_incs_in_scope += len(a.get('direct_incharges', []))

        for h in filtered_direct_hods:
            total_staff_in_scope += h['total_staff_count']
            total_depts_in_scope.update(h['all_department_codes'])
            total_hods_in_scope += 1
            total_incs_in_scope += len(h['incharges'])

        for inc in filtered_unassigned_incs:
            total_staff_in_scope += inc['total_staff_count']
            for d in inc['departments']:
                total_depts_in_scope.add(d['department_code'])
            total_incs_in_scope += 1

        stats = {
            'total_avps': len(filtered_avp_trees) if effective_scope in ['ALL', 'AVP'] else 0,
            'total_hods': total_hods_in_scope,
            'total_incharges': total_incs_in_scope,
            'total_managed_departments': len(total_depts_in_scope),
            'total_active_staff': total_staff_in_scope if total_staff_in_scope > 0 else len(profile_map),
            'global_total_avps': len(avps),
            'global_total_hods': len(hods),
            'global_total_incharges': len(incharges),
            'global_total_departments': len(dept_map),
            'global_total_staff': len(profile_map)
        }

        # Available AVPs and HODs for admin switcher dropdown
        available_avps = [{'employee_id': a['avp_id'], 'name': a['avp_name']} for a in avp_trees]
        available_hods = [{'employee_id': h['employee_id'], 'name': h['name']} for h in hods]

        return JsonResponse({
            'success': True,
            'scope': effective_scope,
            'current_user': {
                'employee_id': logged_in_eid,
                'role': user_ctx.get('role_str'),
                'is_admin': user_ctx.get('is_admin', False),
                'is_avp': user_ctx.get('is_avp', False),
                'is_hod': user_ctx.get('is_hod', False),
                'is_incharge': user_ctx.get('is_incharge', False),
            },
            'reporting_chain': reporting_chain,
            'stats': stats,
            'hierarchy': filtered_avp_trees,
            'direct_hods': filtered_direct_hods,
            'unassigned_incharges': filtered_unassigned_incs,
            'switcher_options': {
                'avps': available_avps,
                'hods': available_hods
            } if user_ctx.get('is_admin') else None
        }, status=200)

    except Exception as e:
        import traceback
        traceback.print_exc()
        return JsonResponse({'error': str(e)}, status=500)

