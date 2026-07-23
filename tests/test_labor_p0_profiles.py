from __future__ import annotations

import json
from pathlib import Path

import pytest

import bonus_platform.app as app_module
from bonus_platform.engine.labor.profiles import (
    generate_profile_from_extraction,
    load_supplier_profiles,
    resolve_supplier_profile,
    save_supplier_profile,
)


def _write_profile(path: Path, **overrides: object) -> Path:
    profile = {
        "key": "candidate",
        "aliases": ["candidate staffing"],
        "prompt_notes": ["Candidate guidance must not run before approval."],
        "image_page_policy": "all",
        "version": 1,
        "created_from": "manual_review",
        "status": "approved",
        "approvedBy": "payroll-admin@example.com",
        "approvedAt": "2026-07-15T09:30:00+08:00",
    }
    profile.update(overrides)
    path.write_text(json.dumps(profile), encoding="utf-8")
    return path


def test_auto_generated_profile_is_draft_and_not_active(tmp_path: Path) -> None:
    generated = generate_profile_from_extraction("Candidate Staffing", [])
    profile_path = save_supplier_profile(generated, tmp_path)

    assert generated["status"] == "draft"
    assert resolve_supplier_profile("Candidate Staffing", profiles_path=profile_path).key == "default"


@pytest.mark.parametrize(
    ("overrides", "expected_status"),
    [
        ({"status": None}, "draft"),
        ({"status": "draft"}, "draft"),
        ({"status": "approved", "approvedBy": ""}, "approved"),
        ({"status": "approved", "approvedAt": ""}, "approved"),
        ({"status": "approved", "approvedAt": "2026-07-15 09:30:00"}, "approved"),
        ({"status": "approved", "version": 0}, "approved"),
        ({"status": "approved", "deprecated": True}, "approved"),
    ],
)
def test_unapproved_or_invalid_profile_fails_closed(
    tmp_path: Path,
    overrides: dict[str, object],
    expected_status: str,
) -> None:
    profile_path = _write_profile(tmp_path / "candidate.json", **overrides)

    loaded = load_supplier_profiles(profile_path)[0]

    assert loaded.status == expected_status
    assert resolve_supplier_profile("Candidate Staffing", profiles_path=profile_path).key == "default"


def test_explicitly_approved_profile_is_active(tmp_path: Path) -> None:
    profile_path = _write_profile(tmp_path / "candidate.json")

    loaded = load_supplier_profiles(profile_path)[0]
    resolved = resolve_supplier_profile("Candidate Staffing", profiles_path=profile_path)

    assert loaded.status == "approved"
    assert loaded.approved_by == "payroll-admin@example.com"
    assert loaded.approved_at == "2026-07-15T09:30:00+08:00"
    assert resolved.key == "candidate"


def test_broad_new_profile_alias_cannot_hijack_more_specific_builtin_supplier(tmp_path: Path) -> None:
    profile_path = _write_profile(
        tmp_path / "new-vendor.json",
        key="new-vendor",
        aliases=["source"],
    )

    resolved = resolve_supplier_profile("One Source Staffing Inc.", profiles_path=profile_path)

    assert resolved.key == "onesource"


def test_equal_specificity_profile_conflict_fails_closed(tmp_path: Path) -> None:
    _write_profile(
        tmp_path / "candidate-a.json",
        key="candidate-a",
        aliases=["candidate staffing"],
    )
    _write_profile(
        tmp_path / "candidate-b.json",
        key="candidate-b",
        aliases=["candidate staffing"],
    )

    resolved = resolve_supplier_profile("Candidate Staffing LLC", profiles_path=tmp_path)

    assert resolved.key == "default"


def test_repository_auto_generated_profiles_are_explicit_drafts() -> None:
    profiles_dir = Path(__file__).resolve().parents[1] / "data" / "supplier_profiles"

    for profile_path in sorted(profiles_dir.glob("*.json")):
        profile = json.loads(profile_path.read_text(encoding="utf-8"))
        if profile.get("created_from") == "auto_generation":
            assert profile.get("status") == "draft", profile_path.name

    assert resolve_supplier_profile("invoice", profiles_path=profiles_dir).key == "default"


def test_run_local_draft_profile_cannot_override_formal_extraction() -> None:
    governance = {
        "activeProfiles": [
            {
                "decision": "active",
                "status": "active",
                "supplier": "Candidate Staffing",
                "profileData": {
                    "key": "candidate",
                    "aliases": ["candidate staffing"],
                    "version": 1,
                    "status": "draft",
                    "created_from": "auto_generation",
                },
            }
        ]
    }

    assert app_module._active_supplier_profile_override("Candidate Staffing", governance) is None


def test_run_local_approved_profile_can_override_only_with_complete_approval_metadata() -> None:
    governance = {
        "activeProfiles": [
            {
                "decision": "active",
                "status": "active",
                "supplier": "Candidate Staffing",
                "profileData": {
                    "key": "candidate",
                    "aliases": ["candidate staffing"],
                    "version": 1,
                    "status": "approved",
                    "approvedBy": "payroll-admin@example.com",
                    "approvedAt": "2026-07-15T09:30:00+08:00",
                    "created_from": "manual_review",
                },
            }
        ]
    }

    profile = app_module._active_supplier_profile_override("Candidate Staffing", governance)

    assert profile is not None
    assert profile.key == "candidate"
    assert profile.status == "approved"


def _active_profile_record(*, key: str, supplier: str, aliases: list[str]) -> dict:
    return {
        "decision": "active",
        "status": "active",
        "supplier": supplier,
        "profileKey": key,
        "profileData": {
            "key": key,
            "aliases": aliases,
            "version": 1,
            "status": "approved",
            "approvedBy": "payroll-admin@example.com",
            "approvedAt": "2026-07-15T09:30:00+08:00",
            "created_from": "manual_review",
        },
    }


def test_run_local_broad_alias_cannot_hijack_specific_builtin_profile() -> None:
    governance = {
        "activeProfiles": [
            _active_profile_record(key="new-vendor", supplier="New Vendor", aliases=["source"])
        ]
    }

    assert app_module._active_supplier_profile_override("One Source Staffing Inc.", governance) is None


def test_run_local_equal_specificity_conflict_fails_closed() -> None:
    governance = {
        "activeProfiles": [
            _active_profile_record(key="candidate-a", supplier="Candidate Staffing", aliases=["candidate staffing"]),
            _active_profile_record(key="candidate-b", supplier="Candidate Staffing", aliases=["candidate staffing"]),
        ]
    }

    assert app_module._active_supplier_profile_override("Candidate Staffing LLC", governance) is None


def test_run_local_exact_supplier_scope_can_intentionally_override_builtin() -> None:
    governance = {
        "activeProfiles": [
            _active_profile_record(
                key="onesource-approved-override",
                supplier="One Source Staffing Inc.",
                aliases=["one source staffing inc"],
            )
        ]
    }

    profile = app_module._active_supplier_profile_override("One Source Staffing Inc.", governance)

    assert profile is not None
    assert profile.key == "onesource-approved-override"
