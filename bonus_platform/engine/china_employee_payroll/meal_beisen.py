"""Read monthly staff scope and daily attendance without recomputing Beisen records."""
from calendar import monthrange
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, timedelta

from .meal_allowance import ParsedAttendance, REQUIRED_COLUMNS, MealAllowanceConfig, _is_eligible_org, _parse_date, _parse_datetime
from .relocation import BeisenMonthlySource, RelocationError, ROOT_ORG_ID, _org_id, _organization_covers, validate_month

ATTENDANCE_PATH = "/AttendanceOpen/api/v1/AttendanceStatistics/GetLateArrival"
SHIFT_PATH = "/AttendanceOpen/api/v1/WorkShift/GetWorkShiftInfo"
COLUMNS = ["UserId", "StaffId", "SwipingCardDate", "FirstCardIncludeFillCheck", "LastCardIncludeFillCheck",
           "OIdWorkShift", "DateType", "RetroactiveRemark", "AttendanceOrgId"]


def value(record, key, default=None):
    if not isinstance(record, dict):
        return default
    return next((v for k, v in record.items() if k.lower() == key.lower()), default)


def org_names(org):
    labels = org.get("translateProperties") or {}
    names = {name: labels.get(field + "Text") or "" for name, field in
             zip(("二级组织", "三级组织", "四级组织", "五级组织"),
                 ("SecondLevelOrganization", "ThirdLevelOrganization", "FourthLevelOrganization", "FifthLevelOrganization"))}
    if not names["二级组织"]:
        raise RelocationError("北森组织名称缺失，无法判断集团技术部核算范围。")
    config = MealAllowanceConfig()
    if names["二级组织"] in config.eligible_second_orgs and not names["三级组织"] and org.get("oId") != org.get("secondLevelOrganization"):
        raise RelocationError("北森三级组织名称缺失，无法判断集团技术部核算范围。")
    if names["二级组织"] == "HRAS人力综合条线" and names["三级组织"] in config.special_third_orgs and not names["四级组织"] and org.get("oId") != org.get("thirdLevelOrganization"):
        raise RelocationError("北森四级组织名称缺失，无法判断集团技术部核算范围。")
    return names


class _MonthlyScope(BeisenMonthlySource):
    def load_organizations(self, org_ids, query_date, progress=lambda message: None):
        payload = self.request("/TenantBaseExternal/api/v5/Organization/GetSubOrganizations", {
            "oId": ROOT_ORG_ID, "queryDate": query_date, "isWithDisable": True,
            "isWithSelf": False, "isWithDeleted": True, "enableTranslate": True,
            "columns": ["OId", "Name", "StartDate", "StopDate", "SecondLevelOrganization",
                        "ThirdLevelOrganization", "FourthLevelOrganization", "FifthLevelOrganization"],
        })
        data = payload.get("data")
        if not isinstance(data, list):
            raise RelocationError("北森核算月组织信息不完整，本次未生成餐补结果。")
        return [o for o in data if _organization_covers(o, query_date)]


def normalize_attendance(records, month, staff, organizations, shifts, date_types):
    rows, seen = [], set()
    config = MealAllowanceConfig()
    for record in records:
        sid = _org_id(value(record, "StaffId") or value(record, "UserId"))
        if sid not in staff:
            raise RelocationError("北森日考勤返回了查询范围外的员工，本次未生成结果。")
        day = _parse_date(value(record, "SwipingCardDate"))
        if not day or day.isoformat()[:7] != month:
            raise RelocationError("北森日考勤日期与核算月份不一致。")
        key = (sid, day)
        if key in seen:
            raise RelocationError("北森日考勤存在重复员工日期，已停止核算以避免重复发放。")
        seen.add(key)
        lower = {k.lower() for k in record}
        # Beisen omits null punch times and remarks instead of returning JSON null.
        required = {k.lower() for k in COLUMNS if k not in {"UserId", "StaffId", "FirstCardIncludeFillCheck", "LastCardIncludeFillCheck", "RetroactiveRemark"}}
        if not required <= lower:
            raise RelocationError("北森日考勤缺少核算字段，请核对含补签首末打卡、班次、日期类型和备注接口字段。")
        org = organizations.get(_org_id(value(record, "AttendanceOrgId")))
        if org is None:
            raise RelocationError("日考勤组织无法匹配核算月组织层级，本次未生成结果。")
        names = org_names(org)
        if not _is_eligible_org(names, config):
            continue
        date_type = value(record, "DateType")
        if str(date_type) in date_types:
            date_type = date_types[str(date_type)]
        elif date_type not in {"工作日", "休息日", "节假日", "休息", "法定节假日"}:
            raise RelocationError("北森日期类型无法映射为中文工作日类型，本次未生成结果。")
        shift_id = value(record, "OIdWorkShift")
        shift = shifts.get(str(shift_id), "")
        if shift_id and not shift:
            raise RelocationError("北森班次编码无法匹配班次名称，本次未生成结果。")
        if date_type == "工作日" and not shift:
            raise RelocationError("北森工作日记录缺少班次，无法准确核算餐补。")
        for field in ("FirstCardIncludeFillCheck", "LastCardIncludeFillCheck"):
            raw_punch = value(record, field)
            if raw_punch not in (None, "", "-"):
                punch = _parse_datetime(raw_punch)
                if not punch or not day <= punch.date() <= day + timedelta(days=1):
                    raise RelocationError("北森含补签打卡时间无效或超出考勤日及次日范围，请核对源记录。")
        identity = staff[sid]
        rows.append({"员工": identity["name"], "工号": identity["jobNumber"], "人员状态": identity.get("status", ""),
                     **names, "考勤日期": day, "首打卡(含补签)": value(record, "FirstCardIncludeFillCheck"),
                     "末打卡(含补签)": value(record, "LastCardIncludeFillCheck"), "当前班次": shift,
                     "日期类型": date_type, "备注": value(record, "RetroactiveRemark") or ""})
    return rows


class BeisenMealSource(BeisenMonthlySource):
    def request(self, path, body, authenticate=False):
        try:
            return super().request(path, body, authenticate)
        except RelocationError as exc:
            if "权限" in str(exc) or "授权" in str(exc):
                endpoint = path.rsplit("/", 1)[-1]
                raise RelocationError(f"北森 {endpoint} 只读接口尚未授权，请开通后重新核算。") from None
            raise

    def _shifts(self):
        shifts, count, total = {}, 0, None
        for page in range(1, 1001):
            payload = self.request(SHIFT_PATH, {"PageIndex": page, "PageSize": 100})
            data = value(payload, "Data", {})
            batch = value(data, "WorkShiftInfos")
            new_total = value(data, "Total")
            if not isinstance(batch, list) or not isinstance(new_total, int) or new_total < 0:
                raise RelocationError("北森班次列表返回格式不完整。")
            if total is not None and total != new_total:
                raise RelocationError("取数期间班次列表发生变化，请重新核算。")
            total = new_total
            for shift in batch:
                oid, name = value(shift, "OId"), value(shift, "Name")
                if not oid or not name or str(oid) in shifts:
                    raise RelocationError("北森班次编码或名称不完整、重复。")
                shifts[str(oid)] = name
            count += len(batch)
            if count == total:
                return shifts
            if not batch or count > total:
                break
        raise RelocationError("北森班次分页不完整。")

    def _date_types(self):
        payload = self.request("/dataservice/api/DataSource/GetDataSource", {
            "app": "Attendance", "metaObjectName": "Attendance.AttendanceStatistics",
            "listFilter": [{"dsName": "Attendance.DateType", "fieldName": "DateType"}],
        })
        data = payload.get("data")
        if not isinstance(data, list) or len(data) != 1:
            raise RelocationError("北森日期类型选项返回格式不完整。")
        options = data[0].get("dataSourceResults")
        if not isinstance(options, list):
            raise RelocationError("北森日期类型选项缺失。")
        mapping = {}
        for option in options:
            if not isinstance(option, dict) or option.get("value") is None or not option.get("text") or str(option["value"]) in mapping:
                raise RelocationError("北森日期类型选项缺失或重复，无法核算。")
            mapping[str(option["value"])] = option["text"]
        if "工作日" not in mapping.values():
            raise RelocationError("北森日期类型选项缺少工作日，无法核算。")
        return mapping

    def load(self, month, progress=lambda message: None):
        validate_month(month)
        year, month_number = map(int, month.split("-"))
        end = date(year, month_number, monthrange(year, month_number)[1]).isoformat()
        def emit(message, stage=0, completed=0, total=None, unit="条"):
            progress(dict(message=message, stage=stage, completed=completed, total=total, unit=unit))
        try:
            emit("正在连接北森并读取班次")
            self.request("/token", {"grant_type": "client_credentials", "app_key": self.key, "app_secret": self.secret}, True)
            shifts = self._shifts()
            date_types = self._date_types()
            emit("正在匹配核算月份的技术部人员与组织")
            source = _MonthlyScope().load(month, lambda event: emit(event.get("message", "正在匹配人员") if isinstance(event, dict) else event))
            orgs = {o["oId"]: o for o in source["organizations"]}
            services = {s["objectId"]: s for s in source["services"]}
            people = {p["userID"]: p.get("name") or "" for p in source["people"]}
            eligible_history = set()
            for service in source["services"]:
                start = str(service.get("startDate") or "")[:10]
                stop = str(service.get("stopDate") or "9999-12-31")[:10]
                previous_org = orgs.get(service.get("oIdDepartment"))
                if start and start <= end and stop >= month + "-01":
                    if previous_org is None:
                        raise RelocationError("核算月内任职组织无法匹配组织层级，无法完整确认技术部人员范围。")
                    if _is_eligible_org(org_names(previous_org), MealAllowanceConfig()):
                        eligible_history.add(service.get("userID"))
            staff = {}
            for monthly in source["attendance"]:
                if str(monthly.get("Month", ""))[:7] != month:
                    raise RelocationError("北森月报与所选核算月份不一致。")
                service = services.get(monthly.get("EmpRecordOID"))
                sid = monthly.get("StaffId")
                if not service or service.get("userID") != sid:
                    raise RelocationError("月报员工任职关联不完整，无法确认集团技术部范围。")
                org = orgs.get(_org_id(monthly.get("AttendanceOrg")))
                if org is None:
                    raise RelocationError("月报组织信息缺失，无法确认集团技术部范围。")
                if not _is_eligible_org(org_names(org), MealAllowanceConfig()) and sid not in eligible_history:
                    continue
                if not service.get("jobNumber") or not people.get(sid):
                    raise RelocationError("技术部员工缺少工号或姓名，无法核算。")
                if sid in staff:
                    raise RelocationError("核算月包含重复员工月报，请确认主职记录后再核算。")
                staff[sid] = {"jobNumber": service["jobNumber"], "name": people[sid],
                              "status": (service.get("translateProperties") or {}).get("EmployeeStatusText") or ""}
            if not staff:
                raise RelocationError("所选月份未找到集团技术部月报人员，请核对月报及组织范围。")
            ids = sorted(staff)
            batches = [ids[i:i + 100] for i in range(0, len(ids), 100)]
            def read_page(batch, page):
                payload = self.request(ATTENDANCE_PATH, {"startDate": month + "-01", "stopDate": end,
                    "userIds": batch, "searchColumns": COLUMNS, "pageIndex": page, "pageSize": 100})
                data = value(payload, "Data", {})
                records, total = value(data, "Items"), value(data, "TotalCount")
                if not isinstance(records, list) or not isinstance(total, int) or not 0 <= total <= len(batch) * 31:
                    raise RelocationError("北森日考勤总量或返回格式异常。")
                expected = max(0, min(100, total - (page - 1) * 100))
                if len(records) != expected:
                    raise RelocationError("北森日考勤分页不完整。")
                if any(_org_id(value(r, "StaffId") or value(r, "UserId")) not in batch for r in records):
                    raise RelocationError("北森日考勤返回了当前查询批次外的员工。")
                return records, total
            emit("正在读取北森日考勤", 1)
            records, pending, total = [], [], 0
            for batch in batches:
                first, count = read_page(batch, 1)
                records.extend(first); total += count
                for page in range(2, (count + 99) // 100 + 1):
                    pending.append((batch, page, count))
            emit(f"已读取 {len(records)}/{total} 条日考勤", 1, len(records), total)
            with ThreadPoolExecutor(max_workers=4) as pool:
                for offset in range(0, len(pending), 4):
                    jobs = {pool.submit(read_page, batch, page): count for batch, page, count in pending[offset:offset + 4]}
                    for job in as_completed(jobs):
                        page_rows, count = job.result()
                        if count != jobs[job]:
                            raise RelocationError("取数期间北森日考勤发生变化，请重新核算。")
                        records.extend(page_rows)
                        emit(f"已读取 {len(records)}/{total} 条日考勤", 1, len(records), total)
            if len(records) != total or not total:
                raise RelocationError("所选月份没有完整的北森日考勤数据，请确认数据已生成。")
            emit("正在核对考勤并生成餐补结果", 2)
            rows = normalize_attendance(records, month, staff, orgs, shifts, date_types)
            if not rows:
                raise RelocationError("日考勤中未找到集团技术部范围内的记录。")
            return ParsedAttendance(rows=rows, files=[], headers=REQUIRED_COLUMNS, missing_columns=[],
                                    source_type="hr", source_label="集团技术部 · 北森考勤")
        finally:
            self.token = self.key = self.secret = ""
            self.client.close()
