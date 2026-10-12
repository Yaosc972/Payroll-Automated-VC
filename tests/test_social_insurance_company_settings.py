from __future__ import annotations

import json

import pytest

from bonus_platform.engine.social_insurance import persistent_storage as storage
from bonus_platform.engine.social_insurance import subject_settings as settings
from bonus_platform.engine.social_insurance.runs import RunValidationError


@pytest.fixture(params=['obs', 's3'])
def remote(monkeypatch, request):
    objects = {}
    monkeypatch.setenv('SIGMA_SOCIAL_INSURANCE_STORAGE_BACKEND', request.param)
    monkeypatch.setenv('SIGMA_SOCIAL_INSURANCE_STORAGE_ENV', 'company-test')
    monkeypatch.setattr(storage, 'obs_storage_configured', lambda: True)
    monkeypatch.setattr(storage, 'obs_put_bytes', lambda key, content, **kw: objects.__setitem__(key, content))
    monkeypatch.setattr(storage, 'obs_get_bytes', lambda key: objects.get(key))
    return objects


def test_account_survives_new_instance_and_period_with_subject_and_environment_isolation(remote, tmp_path, monkeypatch):
    first = {'id': 'sir_settings_a', 'subject': '深圳易可达科技有限公司'}
    monkeypatch.setenv('SIGMA_SOCIAL_INSURANCE_RUNS_DIR', str(tmp_path / 'instance-a'))
    settings.save_settings(first, '001234')
    monkeypatch.setenv('SIGMA_SOCIAL_INSURANCE_RUNS_DIR', str(tmp_path / 'instance-b'))
    assert settings.read_settings({**first, 'id': 'sir_settings_b'})['unitNumber'] == '001234'
    assert settings.read_settings({**first, 'subject': '另一个主体'})['unitNumber'] == ''
    assert not (tmp_path / 'instance-b').exists()
    monkeypatch.setenv('SIGMA_SOCIAL_INSURANCE_STORAGE_ENV', 'another-environment')
    assert settings.read_settings(first)['unitNumber'] == '572226'


def test_storage_failure_does_not_claim_success_or_change_previous_account(remote, monkeypatch):
    run = {'id': 'sir_settings_a', 'subject': '深圳易可达科技有限公司'}
    settings.save_settings(run, '001234')
    before = dict(remote)
    def fail(*args, **kwargs):
        raise RuntimeError('vendor failure includes credential-must-not-leak')
    monkeypatch.setattr(storage, 'obs_put_bytes', fail)
    with pytest.raises(RunValidationError, match='未能保存') as caught:
        settings.save_settings(run, '572226')
    assert 'credential-must-not-leak' not in str(caught.value)
    assert remote == before
    assert settings.read_settings(run)['unitNumber'] == '001234'
    monkeypatch.setattr(storage, 'obs_get_bytes', fail)
    with pytest.raises(RunValidationError, match='读取失败') as caught:
        settings.read_settings(run)
    assert 'credential-must-not-leak' not in str(caught.value)


def test_corrupt_or_wrong_subject_settings_fail_closed(remote):
    run = {'id': 'sir_settings_a', 'subject': '深圳易可达科技有限公司'}
    settings.save_settings(run, '001234')
    key = next(iter(remote))
    for payload in [{'subject': '另一个主体', 'unitNumber': '001234'}, {'subject': run['subject'], 'unitNumber': '=1+1'}]:
        remote[key] = json.dumps(payload).encode()
        with pytest.raises(RunValidationError, match='配置无效'):
            settings.read_settings(run)


def test_unconfigured_company_storage_never_falls_back_to_local_file(tmp_path, monkeypatch):
    monkeypatch.setenv('SIGMA_SOCIAL_INSURANCE_STORAGE_BACKEND', 'obs')
    monkeypatch.setenv('SIGMA_SOCIAL_INSURANCE_RUNS_DIR', str(tmp_path / 'runs'))
    monkeypatch.setattr(storage, 'obs_storage_configured', lambda: False)
    run = {'id': 'sir_settings_a', 'subject': '深圳易可达科技有限公司'}
    with pytest.raises(RunValidationError, match='读取失败'):
        settings.read_settings(run)
    with pytest.raises(RunValidationError, match='未能保存'):
        settings.save_settings(run, '572226')
    assert not (tmp_path / 'runs').exists()
