"""ABU relocation allowance: monthly Beisen data, explicit review reasons."""
from __future__ import annotations

import calendar
import json
import math
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
import httpx

RULE_VERSION = "2026.09.30-04"
GRADES = {f"{prefix}{step}" for prefix in ("P1-", "P2-", "M2-") for step in (1, 2, 3)}
EXCLUDED = {"zt18927", "zt25820", "zt27838", "zt27439"}
INCLUDED = {"zt25631", "zt28124"}
# Organization OIds verified through Organization/GetByIds on 2026-09-30.
# Use unit identifiers, not names or time-axis record objectIds.
ROOT_ORG_ID = 900109025  # Verified parent of ABU / HRAS / FES
ABU_ORG_ID = 2404320
FUNCTIONAL_ORG_IDS = {(3362203, 3713424), (3362202, 2957015)}  # HRAS / HRBP; FES / finance
ABU_DEPARTMENT_IDS = {3694315, 3930588, 3930594}  # route, platform, operations
PRODUCT_ORG_ID = 700388823
PRODUCT_TEAM_ORG_ID = 700388843


class RelocationError(ValueError):
    pass


def validate_month(month):
    if not isinstance(month, str) or not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", month):
        raise RelocationError("请选择有效的核算月份。")
    if not "2000" <= month[:4] <= "2099":
        raise RelocationError("请选择 2000 至 2099 年的核算月份。")
    return month


class BeisenReadError(RelocationError):
    pass


def report_progress(callback, message, stage, completed=0, total=None, unit="条"):
    callback({"message": message, "stage": stage, "completed": completed, "total": total, "unit": unit})


def tracked_rows(rows, callback):
    total = len(rows)
    report_progress(callback, "正在按规则核算补贴", 3, 0, total)
    for index, row in enumerate(rows, 1):
        yield row
        if index % 100 == 0 or index == total:
            report_progress(callback, f"正在生成明细：{index}/{total}", 3, index, total)


class BeisenMonthlySource:
    """Read-only API client. Tokens stay in memory and never enter run files."""
    def __init__(self):
        self.key = os.getenv("BEISEN_APP_KEY")
        self.secret = os.getenv("BEISEN_APP_SECRET")
        self.base = (os.getenv("BEISEN_BASE_URL") or "https://openapi.italent.cn").rstrip("/")
        if self.base != "https://openapi.italent.cn":
            raise RelocationError("北森接口地址未通过校验。")
        if not self.key or not self.secret:
            raise RelocationError("当前核算服务尚未配置北森读取凭据。")
        self.token = ""
        self.client = httpx.Client(timeout=30, limits=httpx.Limits(max_connections=4, max_keepalive_connections=4))

    def request(self, path, body, authenticate=False):
        headers = {"Content-Type": "application/json", "Accept-Encoding": "gzip"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        try:
            for attempt in range(2):
                try:
                    response = self.client.post(self.base + path, json=body, headers=headers)
                    if response.status_code in (429, 502, 503, 504) and attempt == 0:
                        time.sleep(1)
                        continue
                    break
                except httpx.TransportError:
                    if attempt:
                        raise
                    time.sleep(1)
            response.raise_for_status()
            payload = response.json()
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code in (401, 403):
                raise RelocationError("北森接口读取权限不足或授权已失效，请检查考勤、任职和组织接口授权。") from None
            raise RelocationError("北森接口暂时不可用，请稍后重新核算。") from None
        except httpx.TransportError:
            raise BeisenReadError("北森接口请求超时或连接中断，本次未生成核算结果，请稍后重试。") from None
        except (httpx.HTTPError, ValueError):
            raise RelocationError("北森接口请求失败，本次未生成核算结果。") from None
        if authenticate:
            token = payload.get("access_token")
            if not token:
                raise RelocationError("北森认证失败。")
            self.token = token
        elif str(payload.get("Code", payload.get("code"))) not in {"200", "Succeed"}:
            raise RelocationError("北森返回未成功，本次未生成核算结果。")
        return payload

    def load_organizations(self, org_ids, query_date, progress=lambda message: None):
        # GetSubOrganizations returns all descendants at queryDate. Its self record
        # is current even for past dates, so query from the verified tenant root.
        report_progress(progress, f"正在读取 {query_date} 的组织层级", 2, unit="个组织")
        try:
            payload = self.request("/TenantBaseExternal/api/v5/Organization/GetSubOrganizations", {
                "oId": ROOT_ORG_ID, "queryDate": query_date, "isWithDisable": True,
                "isWithSelf": False, "isWithDeleted": True, "enableTranslate": True,
                "columns": ["OId", "Name", "StartDate", "StopDate", "SecondLevelOrganization",
                            "ThirdLevelOrganization", "FourthLevelOrganization"],
            })
        except RelocationError as exc:
            if "权限" in str(exc) or "授权" in str(exc):
                raise RelocationError("北森历史组织查询接口权限不足，无法读取核算月组织信息，请开通 GetSubOrganizations 读取权限后重试。") from None
            raise
        data = payload.get("data")
        if not isinstance(data, list):
            raise RelocationError("北森历史组织返回格式不完整。")
        requested, versions = set(org_ids), {}
        for index, organization in enumerate(data, 1):
            oid = organization.get("oId")
            if oid in requested and _organization_covers(organization, query_date):
                if oid in versions:
                    raise RelocationError("核算月组织版本存在多条匹配记录，请核对北森组织时间轴。")
                versions[oid] = organization
            if index % 100 == 0 or index == len(data):
                report_progress(progress, f"正在核对组织版本：{index}/{len(data)}", 2, index, len(data), "个组织")
        return list(versions.values())

    def load(self, month, progress=lambda message: None):
        try:
            self.request("/token", {"grant_type": "client_credentials", "app_key": self.key, "app_secret": self.secret}, True)
            def request_page(index, size):
                p = self.request("/AttendanceOpen/api/v1/Monthly/GetList", {"Month": month + "-01", "PageIndex": index, "PageSize": size})
                d = p.get("Data", p.get("data"))
                if not isinstance(d, dict) or not isinstance(d.get("DailyReportList"), list):
                    raise RelocationError("北森月报返回格式不完整。")
                return d
            def page(index):
                try:
                    return request_page(index, 100)
                except BeisenReadError:
                    # The same 100-row window can be read as two smaller pages.
                    halves = [request_page(index * 2 - 1, 50), request_page(index * 2, 50)]
                    if halves[0].get("Total") != halves[1].get("Total"):
                        raise RelocationError("取数期间月报发生变化，请重新核算。")
                    return {"Total": halves[0].get("Total"), "DailyReportList": halves[0]["DailyReportList"] + halves[1]["DailyReportList"]}
            report_progress(progress, "正在读取北森月报", 0)
            first = page(1)
            total = first.get("Total")
            if not isinstance(total, int) or not 0 <= total <= 100000:
                raise RelocationError("北森月报总数异常。")
            attendance = first["DailyReportList"]
            report_progress(progress, f"正在读取北森月报：{len(attendance)}/{total}", 0, len(attendance), total)
            with ThreadPoolExecutor(max_workers=4) as pool:
                # Schedule one bounded group at a time so failures do not leave all pages queued.
                for first_page in range(2, math.ceil(total / 100) + 1, 4):
                    futures = [pool.submit(page, index) for index in range(first_page, min(first_page + 4, math.ceil(total / 100) + 1))]
                    for future in as_completed(futures):
                        d = future.result()
                        if d.get("Total") != total:
                            raise RelocationError("取数期间月报发生变化，请重新核算。")
                        attendance.extend(d["DailyReportList"])
                        report_progress(progress, f"正在读取北森月报：{len(attendance)}/{total}", 0, len(attendance), total)
            if len(attendance) != total:
                raise RelocationError("北森月报分页不完整。")
            if not total:
                raise RelocationError("所选月份没有北森月报，请确认月报已生成。")
            ids = list({r.get("StaffId") for r in attendance})
            if any(not isinstance(v, int) or v <= 0 for v in ids):
                raise RelocationError("月报缺少有效员工标识。")
            people, services, organizations = [], [], []
            report_progress(progress, "正在匹配员工任职", 1, 0, len(ids), "人")
            for offset in range(0, len(ids), 300):
                batch = ids[offset:offset + 300]
                s = self.request("/TenantBaseExternal/api/v5/Employee/GetServiceInfoByIds", {
                    "option": "None", "oIds": batch, "approvalStatus": ["Effective"], "serviceType": [0],
                    "isWithDeleted": False, "enableTranslate": True,
                    "columns": ["UserID", "JobNumber", "EntryDate", "LastWorkDate", "StartDate", "StopDate", "OIdDepartment", "OIdJobLevel", "EmployeeStatus", "EmployType", "PObjectDataID"],
                })
                b = self.request("/TenantBaseExternal/api/v5/Employee/GetBasicInfoByIds", {
                    "oIds": batch, "isWithDeleted": False, "enableTranslate": True, "columns": ["UserID", "Name"],
                })
                if not isinstance(s.get("data"), list) or not isinstance(b.get("data"), list):
                    raise RelocationError("北森任职或员工返回格式不完整。")
                services.extend(s["data"])
                people.extend(b["data"])
                report_progress(progress, f"正在匹配员工任职：{min(offset + 300, len(ids))}/{len(ids)}", 1, min(offset + 300, len(ids)), len(ids), "人")
            org_ids = list({int(r["AttendanceOrg"]) for r in attendance})
            query_date = f"{month}-{calendar.monthrange(int(month[:4]), int(month[5:]))[1]:02d}"
            organizations = self.load_organizations(org_ids, query_date, progress)
            return {"attendance": attendance, "services": services, "people": people, "organizations": organizations,
                    "organizationQueryDate": query_date}
        finally:
            self.token = self.key = self.secret = ""
            self.client.close()


def _number(value):
    if value is None or isinstance(value, bool):
        raise ValueError("缺少数值")
    number = Decimal(str(value))
    if not number.is_finite() or number < 0:
        raise ValueError("无效数值")
    return number


def _org_id(value):
    if isinstance(value, bool):
        return None
    if isinstance(value, int) and value > 0:
        return value
    if isinstance(value, str) and value.isdecimal() and int(value) > 0:
        return int(value)
    return None


def _organization_covers(organization, query_date):
    start, stop = [(organization.get(k) or "")[:10] for k in ("startDate", "stopDate")]
    try:
        datetime.strptime(start, "%Y-%m-%d")
        datetime.strptime(stop, "%Y-%m-%d")
    except ValueError:
        return False
    return start <= query_date <= stop


def calculate_relocation(month, source, progress=lambda message: None):
    validate_month(month)
    last_day = f"{month}-{calendar.monthrange(int(month[:4]), int(month[5:]))[1]:02d}"
    services = {s["objectId"]: s for s in source["services"]}
    people = {p["userID"]: p.get("name") for p in source["people"]}
    orgs = {o["oId"]: o for o in source["organizations"]}
    histories = {}
    for s in source["services"]:
        histories.setdefault(s["userID"], []).append(s)
    rows, warnings, seen = [], [], set()
    attendance_source = []
    for a in tracked_rows(source["attendance"], progress):
        sid = a.get("StaffId")
        if sid in seen:
            raise RelocationError("月报包含同一员工多条记录，需确认主职或分段口径后核算。")
        seen.add(sid)
        if str(a.get("Month", ""))[:7] != month:
            raise RelocationError("月报月份与所选月份不一致。")
        s = services.get(a.get("EmpRecordOID"))
        o = orgs.get(int(a.get("AttendanceOrg") or 0))
        if not s or s.get("userID") != sid or not o:
            warnings.append(f"员工记录 {sid} 缺少月报关联任职或组织，无法判定适用范围。")
            continue
        t = o.get("translateProperties") or {}
        second, third, fourth = [t.get(k) or "" for k in ("SecondLevelOrganizationText", "ThirdLevelOrganizationText", "FourthLevelOrganizationText")]
        job = s.get("jobNumber") or ""
        second_id, third_id, fourth_id = [_org_id(o.get(k)) for k in
                                         ("secondLevelOrganization", "thirdLevelOrganization", "fourthLevelOrganization")]
        functional = (second_id, third_id) in FUNCTIONAL_ORG_IDS
        organization = second_id == ABU_ORG_ID and (
            third_id in ABU_DEPARTMENT_IDS or
            (third_id == PRODUCT_ORG_ID and fourth_id == PRODUCT_TEAM_ORG_ID))
        if second_id is None and job not in INCLUDED:
            warnings.append(f"员工记录 {sid} 缺少组织层级 ID，无法判定适用范围。")
            continue
        if not (functional or organization or job in INCLUDED):
            continue
        attendance_source.append({"employeeId": job, "employeeName": people.get(sid) or "",
                                  "secondOrg": second, "thirdOrg": third, "fourthOrg": fourth, "raw": a})
        st = s.get("translateProperties") or {}
        entry = (s.get("entryDate") or "")[:10]
        grade = st.get("OIdJobLevelText") or ""
        employment_type = st.get("EmployTypeText") or ""
        reasons, reviews = [], []
        if job in EXCLUDED:
            reasons.append("指定排除人员")
        try:
            datetime.strptime(entry, "%Y-%m-%d")
        except (ValueError, TypeError):
            reviews.append("入职日期缺失或无效")
        else:
            if entry >= "2026-05-01":
                reasons.append("入职日期不符合")
        if not employment_type:
            reviews.append("缺少人员类型")
        elif employment_type != "内部员工":
            reasons.append("人员类型不符合正式工范围")
        if not grade:
            reviews.append("缺少职级")
        elif grade not in GRADES:
            reasons.append("职级不符合")
        if not job or not people.get(sid):
            reviews.append("缺少工号或姓名")
        departures = sorted({r["lastWorkDate"][:10] for r in histories[sid] if r.get("lastWorkDate") and (r.get("entryDate") or "")[:10] == entry and entry <= r["lastWorkDate"][:10]})
        departure = departures[-1] if departures else ""
        if (o.get("startDate") or "")[:10] > last_day:
            reviews.append("组织版本晚于核算月")
        if (s.get("startDate") or "")[:10] > last_day:
            reviews.append("关联任职晚于核算月")
        amount = normal = None
        values = {}
        try:
            props = a.get("Properties") or {}
            target = _number(a.get("TargetDays"))
            sick = _number(props.get("AttendanceItem6")) / 8
            casual = _number(props.get("AttendanceItem5")) / 8
            absent = _number(a.get("AbsenteeismDuration"))
            maternity = _number(props.get("AttendanceItem16"))
            normal = max(Decimal(0), target - sick - casual - absent - maternity)
            amount = float((min(normal, Decimal(20)) * 50).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))
            values = dict(zip(("targetDays", "sickDays", "casualDays", "absentDays", "maternityDays"), map(float, (target, sick, casual, absent, maternity))))
        except (ValueError, ArithmeticError):
            reviews.append("考勤字段缺失或数值无效")
        if reasons:
            amount = 0
            reviews = []
        status = "不发放" if reasons else "待确认" if reviews else "已试算"
        rows.append({"employeeId": job, "employeeName": people.get(sid) or "", "secondOrg": second,
                     "attendanceOrgId": _org_id(o.get("oId")), "secondOrgId": second_id,
                     "thirdOrgId": third_id, "fourthOrgId": fourth_id,
                     "thirdOrg": third, "fourthOrg": fourth, "grade": grade, "employmentType": employment_type, "entryDate": entry,
                     "departureDate": departure, **values, "normalDays": float(normal) if normal is not None else None,
                     "amount": amount, "status": status, "reason": "；".join(reasons + reviews)})
    rows.sort(key=lambda r: (r["thirdOrg"], r["employeeId"]))
    jobs = [r["employeeId"] for r in rows if r["employeeId"]]
    if len(jobs) != len(set(jobs)):
        raise RelocationError("候选名单包含重复工号，本次未生成核算结果。")
    for job in INCLUDED:
        if job not in jobs:
            warnings.append(f"指定补充人员 {job} 无本月月报或无法匹配任职，请复核。")
    warnings.insert(0, "补贴适用起止月份尚未确认；当前结果为按规则试算，待确认项须复核。")
    if not rows:
        warnings.append("未找到符合组织范围的候选人员，请核对本月组织数据。")
    return {"month": month, "ruleVersion": RULE_VERSION, "warnings": warnings, "results": rows,
            "attendanceSource": attendance_source,
            "summary": {"sourceCount": len(source["attendance"]), "employeeCount": len(rows),
                        "payableCount": sum((r["amount"] or 0) > 0 for r in rows),
                        "amount": float(sum(Decimal(str(r["amount"] or 0)) for r in rows)),
                        "reviewCount": sum(r["status"] == "待确认" for r in rows),
                        "missingScopeCount": len(warnings) - 1 - sum(w.startswith("指定补充人员") or w.startswith("未找到") for w in warnings)}}
