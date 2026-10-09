#!/usr/bin/env python3
"""Offline real-material replay. Inputs remain outside Git; output contains aggregates only.

Uses a local queue and file object adapters to exercise the same worker. Optional
MySQL must be an isolated loopback database; no production storage or online UAT.
"""
import argparse
from datetime import date
import hashlib
from io import BytesIO
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
from unittest.mock import patch
from urllib.parse import urlsplit
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fastapi.testclient import TestClient
from openpyxl import load_workbook
import bonus_platform.app as application
from bonus_platform.engine.china_employee_payroll import activities, durable, worker
from bonus_platform.engine.china_employee_payroll.durable_store import Store
from bonus_platform.engine.china_employee_payroll.meal_allowance import ParsedAttendance


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--meal-directory', type=Path, required=True)
    parser.add_argument('--wx-file', type=Path, required=True)
    parser.add_argument('--wx-baseline', type=Path, required=True)
    parser.add_argument('--relocation-source', type=Path, required=True)
    parser.add_argument('--organizations', type=Path, required=True)
    parser.add_argument('--baseline-ref', required=True)
    parser.add_argument('--production-ref', required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--mysql-url', default='')
    args = parser.parse_args()
    if args.mysql_url:
        target = urlsplit(args.mysql_url)
        assert target.hostname in {'127.0.0.1', 'localhost'} and target.path.startswith('/sigma_features_test'), 'Only isolated loopback test databases are allowed'
    meal_source = json.loads((args.meal_directory / 'data-source.json').read_text())
    meal_baseline = json.loads((args.meal_directory / 'result.json').read_text())
    for row in meal_source['rows']:
        row['考勤日期'] = date.fromisoformat(row['考勤日期'])
    parsed = ParsedAttendance(rows=meal_source['rows'], headers=meal_source['columns'], files=[], missing_columns=[], source_label=meal_source['sourceLabel'])
    wx_baseline = json.loads(args.wx_baseline.read_text())
    relocation_source = json.loads(args.relocation_source.read_text())
    relocation_source['organizations'] = json.loads(args.organizations.read_text())
    relocation_month = str(relocation_source['attendance'][0]['Month'])[:7]
    current = {'user': {'id': 'offline-verification', 'name': '本地验证账号', 'status': 'active'}, 'modules': [{'id': 'employee', 'enabled': True, 'canEnter': True}]}
    report = {'mode': ('offline MySQL' if args.mysql_url else 'offline SQLite') + ' queue, file object adapter, simulated session; no production writes', 'baselineRef': args.baseline_ref, 'subjects': []}
    with TemporaryDirectory(prefix='sigma-payroll-replay-') as temp:
        root = Path(temp)
        env = {'SIGMA_CHINA_PAYROLL_BACKEND': 'sqlite', 'SIGMA_CHINA_PAYROLL_SQLITE_PATH': str(root / 'state.sqlite'), 'SIGMA_LABOR_STORAGE_ENV': 'local', 'VERCEL': '', 'VERCEL_ENV': ''}
        if args.mysql_url:
            env.update(SIGMA_CHINA_PAYROLL_BACKEND='mysql', ADMIN_DATABASE_URL=args.mysql_url, SIGMA_LABOR_STORAGE_ENV='replay-' + uuid4().hex)
        original = root / 'original_relocation.py'
        original.write_bytes(subprocess.check_output(['git', 'show', args.baseline_ref + ':bonus_platform/engine/china_employee_payroll/relocation.py']))
        spec = importlib.util.spec_from_file_location('baseline_relocation', original)
        baseline = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(baseline)
        relocation_baseline = baseline.calculate_relocation(relocation_month, relocation_source)
        def load_meal(ref, name):
            target = root / (name + '.py')
            target.write_bytes(subprocess.check_output(['git', 'show', ref + ':bonus_platform/engine/china_employee_payroll/meal_allowance.py']))
            module_spec = importlib.util.spec_from_file_location(name, target)
            module = importlib.util.module_from_spec(module_spec)
            sys.modules[name] = module
            module_spec.loader.exec_module(module)
            return module
        production_meal = load_meal(args.production_ref, 'production_meal')
        source_meal = load_meal(args.baseline_ref, 'source_meal')
        source_result = source_meal.calculate_meal_allowance(parsed)
        assert source_result['summary'] == meal_baseline['summary']
        meal_baseline = production_meal.calculate_meal_allowance(parsed)
        from collections import Counter
        changes = Counter()
        previous = {(row['employeeId'], row['attendanceDate']): row for row in source_result['dailyRows']}
        for row in meal_baseline['dailyRows']:
            old = previous[(row['employeeId'], row['attendanceDate'])]
            if row['amount'] != old['amount']:
                changes[f"{old['reason']} → {row['reason']} ({row['shift']})"] += row['amount'] - old['amount']
        report['productionRuleComparison'] = {'productionRef': args.production_ref, 'sourceAmount': source_result['summary']['totalAmount'], 'productionAmount': meal_baseline['summary']['totalAmount'], 'deltaByReason': dict(changes)}

        def location(key):
            return root / hashlib.sha256(key.encode()).hexdigest()
        def put(key, content, **kwargs):
            location(key).write_bytes(content)
        def get(key, **kwargs):
            path = location(key)
            return path.read_bytes() if path.exists() else None
        with patch.dict(os.environ, env), patch.object(application, 'CHINA_EMPLOYEE_PAYROLL_RUNS_DIR', root / 'legacy'), patch.object(activities.relocation_router, 'RUNS_DIR', root / 'relocation'), patch.object(application, 'current_user_from_request', return_value=current), patch.object(application, '_labor_current_user_from_request', return_value=current), patch('bonus_platform.auth.current_user_from_request', return_value=current), patch.object(activities, 'current_user_from_request', return_value=current), patch.object(durable.storage, 'put_labor_supabase_private_object', side_effect=put), patch.object(durable.storage, 'get_labor_supabase_private_object', side_effect=get), patch.object(worker.BeisenMealSource, '__init__', return_value=None), patch.object(worker.BeisenMealSource, 'load', return_value=parsed), patch.object(worker.BeisenMonthlySource, '__init__', return_value=None), patch.object(worker.BeisenMonthlySource, 'load', return_value=relocation_source):
            store, client = Store(), TestClient(application.app)
            if not args.mysql_url:
                store.initialize_local()
            inputs = [('meal-allowance', meal_baseline['summary']['dateStart'][:7], meal_baseline), ('wx-meal-allowance', wx_baseline['summary']['dateStart'][:7], wx_baseline), ('relocation-allowance', relocation_month, relocation_baseline)]
            created = [client.post('/api/china-employee-payroll/activities', json={'subject': subject, 'month': month}).json() for subject, month, _ in inputs]
            for index, ((subject, month, expected), activity) in enumerate(zip(inputs, created)):
                identifier = activity['activityId']
                if subject == 'wx-meal-allowance':
                    raw = args.wx_file.read_bytes()
                    key = durable.object_key(store.get(identifier), args.wx_file.name, 'inputs')
                    put(key, raw)
                    store.uploads(identifier, [{'objectKey': key, 'name': args.wx_file.name, 'size': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()}])
                response = client.post(f'/api/china-employee-payroll/activities/{identifier}/start')
                assert response.status_code == 200, response.text
                assert worker.process_one(store)
                # Reconstruct state in another interpreter after the worker has exited.
                code = 'import json,sys; from bonus_platform.engine.china_employee_payroll.durable_store import Store; print(json.dumps(Store().get(sys.argv[1])))'
                recovered = json.loads(subprocess.check_output([sys.executable, '-c', code, identifier]))
                assert recovered['status'] == 'completed', recovered.get('progress')
                job = store.job(recovered['runId'])
                result = durable.get_run(job['runId'], subject == 'relocation-allowance')
                actual = result['result'] if subject == 'relocation-allowance' else result
                assert actual['summary'] == expected['summary'], (subject, actual['summary'], expected['summary'])
                expected_rows = [{k: v for k, v in row.items() if k != 'daily'} for row in expected['results']]
                assert actual['results'] == expected_rows, subject
                book = load_workbook(BytesIO(durable.read_file(job['export'])), read_only=True, data_only=True)
                assert len(book.sheetnames) == 2
                amount = actual['summary'].get('totalAmount', actual['summary'].get('amount'))
                # Meal amount is column 9; relocation amount is column 11.
                column = 17 if subject == 'relocation-allowance' else 9
                rows = list(book.worksheets[0].iter_rows(values_only=True))
                excel_amount = sum(row[column-1] for row in rows[1:] if isinstance(row[column-1], (int, float))) if subject == 'relocation-allowance' else rows[-1][column-1]
                assert abs(excel_amount - amount) < 0.001, (subject, 'Excel total')
                report['subjects'].append({'subject': subject, 'month': month, 'summary': actual['summary'], 'excelSheets': book.sheetnames, 'exactRowComparison': True, 'restartRecovery': True, 'snapshotSha256': job['snapshot']['sha256'], 'exportSha256': job['export']['sha256']})
                book.close()
                for later in created[index + 1:]:
                    assert store.get(later['activityId'])['status'] == 'draft'
                assert client.get(f'/api/china-employee-payroll/activities/{identifier}').json()['creator']['avatarUrl'] == activities.DEFAULT_AVATAR
                assert client.post(f'/api/china-employee-payroll/activities/{identifier}/start').json()['runId'] == job['runId']
            assert client.get('/api/china-employee-payroll/activities').json()['total'] == 3
    report['inputSha256'] = {name: hashlib.sha256(path.read_bytes()).hexdigest() for name, path in [('groupSource', args.meal_directory / 'data-source.json'), ('wxWorkbook', args.wx_file), ('relocationSource', args.relocation_source), ('historicalOrganizations', args.organizations)]}
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
