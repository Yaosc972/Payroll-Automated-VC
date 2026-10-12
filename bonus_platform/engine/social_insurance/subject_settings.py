"""Per-subject settings shared across periods through the configured private storage."""
import hashlib
import json
import os
import tempfile
from .runs import get_run_dir, RunValidationError
from . import persistent_storage as storage


def _path(run):
    key = hashlib.sha256(run['subject'].strip().encode()).hexdigest()
    return get_run_dir(run['id']).parent / 'subject-settings' / f'{key}.json'


def read_settings(run):
    try:
        storage.require_persistent_storage()
        if storage.persistent_storage_enabled():
            key = hashlib.sha256(run['subject'].strip().encode()).hexdigest()
            data = storage.load_json('subject-settings', key)
            if data is not None:
                number = str(data.get('unitNumber') or '')
                if data.get('subject') != run['subject'] or not number.isascii() or not number.isdigit() or not 1 <= len(number) <= 30:
                    raise RunValidationError('主体账号持久化配置无效，请重新保存。')
                return data
        else:
            path = _path(run)
            if path.exists():
                return json.loads(path.read_text(encoding='utf-8'))
    except RunValidationError:
        raise
    except Exception as exc:
        raise RunValidationError('主体账号配置读取失败，请稍后重试。') from exc
    return {'subject': run['subject'], 'unitNumber': '572226' if run['subject'] == '深圳易可达科技有限公司' else ''}


def save_settings(run, value):
    number = str(value or '').strip()
    if not number.isascii() or not number.isdigit() or not 1 <= len(number) <= 30:
        raise RunValidationError('社保账号／单位编号须为 1–30 位数字')
    data = {'subject': run['subject'], 'unitNumber': number}
    try:
        storage.require_persistent_storage()
        if storage.persistent_storage_enabled():
            key = hashlib.sha256(run['subject'].strip().encode()).hexdigest()
            storage.persist_json('subject-settings', key, data)
            return data
    except Exception as exc:
        raise RunValidationError('主体账号未能保存到持久化存储，请稍后重试。') from exc
    path = _path(run)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as output:
            json.dump(data, output, ensure_ascii=False)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    return data
