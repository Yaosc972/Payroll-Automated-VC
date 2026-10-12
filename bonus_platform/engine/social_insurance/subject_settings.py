"""Local per-subject reporting settings, shared across periods on this workstation."""
import hashlib
import json
import os
import tempfile
from .runs import get_run_dir, RunValidationError


def _path(run):
    key = hashlib.sha256(run['subject'].strip().encode()).hexdigest()
    return get_run_dir(run['id']).parent / 'subject-settings' / f'{key}.json'


def read_settings(run):
    path = _path(run)
    if path.exists():
        return json.loads(path.read_text(encoding='utf-8'))
    return {'subject': run['subject'], 'unitNumber': '572226' if run['subject'] == '深圳易可达科技有限公司' else ''}


def save_settings(run, value):
    number = str(value or '').strip()
    if not number.isascii() or not number.isdigit() or not 1 <= len(number) <= 30:
        raise RunValidationError('社保账号／单位编号须为 1–30 位数字')
    path = _path(run)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {'subject': run['subject'], 'unitNumber': number}
    fd, temporary = tempfile.mkstemp(dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as output:
            json.dump(data, output, ensure_ascii=False)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    return data
