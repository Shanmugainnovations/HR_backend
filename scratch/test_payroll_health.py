import os
import sys
import django

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'hr_backend.settings')
django.setup()

from rest_framework.test import APIRequestFactory
from employees.views.payroll.payroll_views import (
    monthly_payroll_view,
    get_late_hours_deductions_report,
    export_bank_transfer_sheet,
    export_pf_ecr,
    export_esi_return
)
from pymongo import MongoClient
from employees.views.common.utils import get_mongo_client

factory = APIRequestFactory()

def run_payroll_diagnostics():
    print("==================================================")
    print("1. MongoDB Payroll Collections Status Check")
    print("==================================================")
    client = get_mongo_client()
    db = client[os.environ.get('GLOBAL_DB_NAME', 'Global')]
    
    payroll_count = db['backend_diagnostics_payroll'].count_documents({})
    print(f"Total documents in backend_diagnostics_payroll: {payroll_count}")
    
    sample_docs = list(db['backend_diagnostics_payroll'].find({}, {'_id': 0, 'month': 1, 'periodKey': 1, 'employeeId': 1, 'grossSalary': 1, 'netSalary': 1, 'status': 1}).limit(5))
    for d in sample_docs:
        print(" Sample payroll doc:", d)

    print("\n==================================================")
    print("2. Testing GET /payroll/monthly/")
    print("==================================================")
    req_get = factory.get('/payroll/monthly/?month=2026-09&cycle=hospital')
    resp_get = monthly_payroll_view(req_get)
    print("GET Status Code:", resp_get.status_code)
    if resp_get.status_code == 200:
        data = resp_get.data
        print(f" Month: {data.get('month')}, Period: {data.get('fromDate')} to {data.get('toDate')}")
        print(f" Status: {data.get('status')}")
        summary = data.get('summary', {})
        print(f" Total Employees in Summary: {summary.get('totalEmployees')}")
        print(f" Total Gross: ₹{summary.get('totalGross'):,}")
        print(f" Total Net Payout: ₹{summary.get('totalNetPayout'):,}")
        print(f" Total Deductions: ₹{summary.get('totalDeductions'):,}")
    else:
        print("GET Error response:", resp_get.data)

    print("\n==================================================")
    print("3. Testing GET /payroll/late-hours-deductions/")
    print("==================================================")
    req_late = factory.get('/payroll/late-hours-deductions/?month=2026-09')
    resp_late = get_late_hours_deductions_report(req_late)
    print("Late Hours Report Status Code:", resp_late.status_code)
    if resp_late.status_code == 200:
        late_data = resp_late.data
        print(f" Total Employees in Late Hours report: {len(late_data.get('records', []))}")
        print(f" Summary: {late_data.get('summary')}")
    else:
        print("Late Hours Error:", resp_late.data)

    print("\n==================================================")
    print("4. Testing Exports (Bank Transfer, PF ECR, ESI Return)")
    print("==================================================")
    req_bank = factory.get('/payroll/export-bank-sheet/?month=2026-09')
    resp_bank = export_bank_transfer_sheet(req_bank)
    print(f"Bank Export Status Code: {resp_bank.status_code}, Content-Type: {resp_bank.get('Content-Type')}")

    req_pf = factory.get('/payroll/export-pf-ecr/?month=2026-09')
    resp_pf = export_pf_ecr(req_pf)
    print(f"PF ECR Export Status Code: {resp_pf.status_code}, Content-Type: {resp_pf.get('Content-Type')}")

    req_esi = factory.get('/payroll/export-esi-return/?month=2026-09')
    resp_esi = export_esi_return(req_esi)
    print(f"ESI Export Status Code: {resp_esi.status_code}, Content-Type: {resp_esi.get('Content-Type')}")

if __name__ == '__main__':
    run_payroll_diagnostics()
