import json
from pathlib import Path

import pytest

from bonus_platform.engine.social_insurance.sync_snapshot import _confirmation_decision

CASES = json.loads((Path(__file__).resolve().parents[1] / 'social_insurance_connector/test/fixtures/early-dimission.json').read_text())


@pytest.mark.parametrize('scenario', CASES, ids=lambda case: case['name'])
def test_early_dimission_snapshot_parity(scenario):
    records = [dict(lastWorkDate=scenario['last'], voluntaryStopFlag=scenario['flag'],
                    processTimeReliable=False, source='beisen-dimission-record')]
    if scenario.get('extraFlag'):
        records.append({**records[0], 'voluntaryStopFlag': scenario['extraFlag']})
    decision, _ = _confirmation_decision(
        dict(currentEntryDate=scenario['entry'], dimissionRecords=records),
        confirmation_date=scenario.get('cutoff', '2026-09-30'))
    assert decision == scenario['expected']
