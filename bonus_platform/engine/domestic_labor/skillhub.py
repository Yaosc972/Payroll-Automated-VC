"""Reproducible domestic payroll skills and content-based release catalog."""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime
from functools import lru_cache
from hashlib import sha256
from io import BytesIO
import json
from pathlib import Path
import re
import runpy
from threading import RLock
from zipfile import ZipFile, ZIP_DEFLATED, ZipInfo
from zoneinfo import ZoneInfo

ROOT = Path(__file__).parent
ASSETS = ROOT / "skillhub_assets"
LOCK = RLock()
SKILLS = {
    "canbu": ("hras-canbu", "操作线餐补", "按地区、岗位与出勤情况核算餐补。", "操作线补贴", "utensils"),
    "waisu_butie": ("hras-waisu-butie", "操作线外宿补贴", "结合完整住宿区间与出勤记录，核算外宿补贴。", "操作线补贴", "home"),
    "yeban_butie": ("hras-yeban-butie", "操作线夜班补贴", "按实际打卡、夜班窗口与班次休息配置核算。", "操作线补贴", "moon"),
    "gangwei_butie": ("hras-gangwei-butie", "操作线岗位补贴", "匹配地区和岗位资格，按出勤及缺勤折算。", "操作线补贴", "briefcase"),
    "gaowen_butie": ("hras-gaowen-butie", "操作线高温补贴", "匹配网点、日期、班次测温，并应用不享有名单。", "操作线补贴", "sun"),
    "quanqinjiang": ("hras-quanqinjiang", "全区域全勤奖", "检查迟到、缺勤与整月排班，核算全勤奖。", "全区域奖金", "calendar"),
    "gonglingjiang": ("hras-gonglingjiang", "全区域工龄奖", "按地区、部门与司龄核算工龄奖及入离职折算。", "全区域奖金", "clock"),
}
INITIAL_UPDATES = {
    "canbu": ["同步岗位资格与岗位名称修正", "保留逐人核算解释与线下金额核验"],
    "waisu_butie": ["同步地区资格、低出勤复核及退宿后缺勤扣减", "支持跨月、持续在宿与多次入住；校验空名单及重叠区间", "附住宿名单与填写说明工作簿"],
    "yeban_butie": ["普通夜班从取整后的实际打卡起算", "东莞理货员不享有夜班补贴", "班次休息配置须按适用月份明确确认"],
    "gangwei_butie": ["同步当前岗位补贴规则与输入契约", "本次未改变核心核算公式"],
    "gaowen_butie": ["优先采用日考勤明确填写的白/夜班，兼容班次分类列", "测温班次与班次分类冲突时提示核对", "支持不享有名单按生效、结束日期排除"],
    "quanqinjiang": ["同步当前全勤奖规则与完整日历校验", "本次未改变核心核算公式"],
    "gonglingjiang": ["东南B2B枢纽组沿用东南枢纽工龄奖规则", "保留岗位资格、入离职折算与封顶规则"],
}


def json_bytes(value):
    return (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode()


def zip_bytes(files):
    stream = BytesIO()
    with ZipFile(stream, "w", ZIP_DEFLATED) as archive:
        for name, data in sorted(files.items()):
            info = ZipInfo(name, (2000, 1, 1, 0, 0, 0))
            info.compress_type = ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            archive.writestr(info, data)
    return stream.getvalue()


@lru_cache(maxsize=8)
def _fresh_rules(source_digest):
    # Read the authoritative rule file after edits, even in a long-running preview.
    return runpy.run_path(str(ROOT / "rule_package.py"))["get_rule_package"]()


@lru_cache(maxsize=8)
def _workbook(subject, source_digest):
    from .templates import generate_template
    with ZipFile(BytesIO(generate_template(subject))) as archive:
        files = {name: archive.read(name) for name in archive.namelist()}
    # Workbook properties and ZIP timestamps must not create fictitious releases.
    core = files.get("docProps/core.xml", b"").decode()
    core = re.sub(r"(<dcterms:(?:created|modified)[^>]*>).*?(</dcterms:(?:created|modified)>)", r"\g<1>2000-01-01T00:00:00Z\2", core)
    files["docProps/core.xml"] = core.encode()
    return zip_bytes(files)


def build_material(subject):
    if subject not in SKILLS:
        raise KeyError(subject)
    slug, name, description, category, icon = SKILLS[subject]
    rule_digest = sha256((ROOT / "rule_package.py").read_bytes()).hexdigest()
    rule = next(item for item in _fresh_rules(rule_digest)["subjects"] if item["id"] == subject)
    contract = json.loads((ASSETS / f"{subject}.json").read_text())
    contract["rule_version"] = rule["version"]
    files = {
        "scripts/run.py": (ASSETS / "runner.py").read_bytes(),
        "scripts/vendor/__init__.py": b"",
        "scripts/vendor/engines/__init__.py": b"",
        "references/input-contract.json": json_bytes(contract),
        "references/rules.json": json_bytes(rule),
        "references/workflow.md": (ASSETS / "workflow.md").read_bytes(),
        "scripts/requirements.txt": b"openpyxl>=3.1,<4\n",
    }
    paths = ["models.py", "engines/base.py", "engines/position_rules.py", f"engines/{subject}.py"]
    if subject in {"waisu_butie", "gaowen_butie"}:
        paths += ["supplemental_inputs.py", "temperature_sites.py"]
        if subject != "gaowen_butie":
            paths += ["engines/gaowen_butie.py"]
        template_digest = sha256(b"".join((ROOT / path).read_bytes() for path in ["templates.py", "supplemental_inputs.py", "temperature_sites.py"])).hexdigest()
        files[f"assets/{'高温补贴补充资料' if subject == 'gaowen_butie' else '外宿补贴住宿名单'}.xlsx"] = _workbook(subject, template_digest)
    if subject == "yeban_butie":
        paths += ["night_shift_config.py", "data/night_shift_breaks.json"]
    hashes = {}
    for path in paths:
        data = (ROOT / path).read_bytes()
        hashes[path] = sha256(data).hexdigest()
        if path == "night_shift_config.py":
            text = data.decode().replace("from ...config import DOMESTIC_LABOR_RUNS_DIR", "DOMESTIC_LABOR_RUNS_DIR = Path(__file__).parent / '_disabled_storage'")
            text = re.sub(r"from \.persistent_storage import \([^)]*\)", "def domestic_labor_persistent_storage_enabled():\n    return False\n\ndef load_domestic_labor_metadata_from_persistent(*args, **kwargs):\n    raise RuntimeError('Standalone skills do not load platform storage')\n\ndef save_domestic_labor_metadata_to_persistent(*args, **kwargs):\n    raise RuntimeError('Standalone skills do not write platform storage')", text)
            data = text.encode()
        files[f"scripts/vendor/{path}"] = data
    source_template = {"month":"YYYYMM", "employees":[], "sources":{}}
    available_sources = list(dict.fromkeys(["employees"] + contract["sources"] +
        [source for mapping in (contract.get("conditional_sources_by_area", {}), contract.get("conditional_sources_by_department", {})) for sources in mapping.values() for source in sources]))
    for source in available_sources:
        source_template["sources"][source] = {"month":"YYYYMM", "status":"missing", "complete":False, "evidence":""}
        source_template[source] = {} if source == "night_config" else []
    if subject == "gaowen_butie":
        source_template["temperature_site_mapping"] = {}
    files["assets/input-template.json"] = json_bytes(source_template)
    rule_text = f"# {name}\n\n规则版本：{rule['version']}\n\n{rule.get('summary','')}\n"
    for region in rule.get("regions", []):
        rule_text += f"\n## {region['name']}\n\n{region.get('rule','')}\n"
        rule_text += "\n".join(f"- {line}" for line in region.get("details", [])) + "\n"
    files["references/rules.md"] = rule_text.encode()
    supplemental = {
        "waisu_butie":"住宿包含跨月仍在宿人员、完整入住及退宿区间；同一员工多次住宿分行填写。退宿后缺勤扣减涉及的日考勤请假字段见输入契约，缺列不能补零。",
        "gaowen_butie":"测温与不享有人员名单独立填写。日考勤优先使用测温班次，其次采用班次分类中明确的白班/夜班；均未明确时才按排班时间等推断，两列冲突时提示核对并优先采用测温班次。使用 temperature_exclusions 六列及 temperature_site_mapping 明确网点名称对照，结束日期持续有效时填 null。不享有原因只承接已确认规则；出库发运组过渡性高温补贴仍单独线下核算。",
        "yeban_butie":"按核算月份确认班次休息配置，晋江额外排除名单为空也要明确确认；随包历史基线不能作为当月已确认配置。",
        "canbu":"东莞另需日考勤。日考勤需保留实际异常及异常原因；不能以月度汇总替代逐日资格判断。",
        "quanqinjiang":"日考勤覆盖完整月份，包括非工作日。不能用自然周末猜测入离职期间排班。",
        "gonglingjiang":"第四纵队另需本月揽收线工龄奖名单。东南B2B枢纽组与东南枢纽规则一致，仍需按地区及岗位判断。",
    }.get(subject, "按真实地区、岗位及出勤字段判断，不扩大适用岗位或修改折算规则。")
    files["SKILL.md"] = f"""---
name: {slug}
description: {name}核算与线下金额核验。用于中国区外包工该科目的资料检查、逐人计算和差异分析。
---

# {name}

{description} 使用随包引擎与规则快照，不连接平台账号或生产服务。

先读取 `references/input-contract.json` 和 `references/workflow.md`，核对月份、字段映射及资料覆盖范围；适用规则见 `references/rules.md`，完整口径见 `references/rules.json`。

工号保留为文本；缺失值不能补零。空名单必须由资料提供方确认，记录证据后使用 `confirmed_empty`。不推断未确认岗位、网点别名或班次休息。

填写 `assets/input-template.json` 所示结构，保存成 input.json；模板的 missing 状态必须据真实资料更新。

{supplemental}

需要安装依赖时运行 `python3 -m pip install -r scripts/requirements.txt`。

```bash
python3 scripts/run.py input.json --mode validate --output validation.json
python3 scripts/run.py input.json --mode calculate --output calculation.json
python3 scripts/run.py input.json --mode reconcile --output reconciliation.json
```

验证通过不等于已核算。保留 details、warnings、逐日解释与来源。blocked 或 needs_review 结果不能用于最终发薪；amount 为 null 时 provisional_amount 只供复核。规则或实现更新后从 SkillHub 获取新包，旧包不会自动改变。
""".encode()
    files["agents/openai.yaml"] = f'interface:\n  display_name: "{name}"\n  short_description: "{name}资料检查、核算和金额核验"\n  default_prompt: "使用 ${slug} 检查本月资料并核算{name}，保留来源和异常解释。"\n'.encode()
    # Hash the actual portable content, independently of Git HEAD and release date.
    fingerprint = sha256(zip_bytes(files)).hexdigest()
    return files, {"id":subject, "slug":slug, "name":name, "description":description,
                   "category":category, "icon":icon, "rule_version":rule["version"],
                   "fingerprint":fingerprint, "source_sha256":hashes,
                   "inputs":[contract["source_labels"].get(key,key) + ("（按地区或部门需要）" if key not in ["employees"]+contract["sources"] else "") for key in available_sources],
                   "rules":rule, "contract":contract}


def _load_catalog(path):
    if path and path.exists():
        return json.loads(path.read_text())
    return {"skills":[], "releases":[]}


def sync_catalog(previous=None, now=None):
    previous = previous or {"skills":[], "releases":[]}
    now = now or datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(timespec="seconds")
    old = {item["id"]:item for item in previous.get("skills", [])}
    releases = deepcopy(previous.get("releases", []))
    skills, bundles = [], {}
    for subject in SKILLS:
        files, item = build_material(subject)
        last = old.get(subject, {})
        changed = last.get("fingerprint") != item["fingerprint"]
        item["released_at"] = now if changed else last["released_at"]
        item["package_version"] = (item["released_at"][:10].replace("-", ".") + "+" + item["fingerprint"][:8])
        updates = []
        if not last:
            updates = INITIAL_UPDATES[subject]
        elif last.get("rule_version") != item["rule_version"]:
            updates = [item["rules"].get("change_log", [{}])[0].get("changes", "同步最新核算规则")]
        elif last.get("source_sha256") != item["source_sha256"]:
            updates = ["同步最新核算引擎与配套输入校验", f"规则版本：{item['rule_version']}；实现内容已更新"]
        elif last.get("contract") != item["contract"]:
            updates = ["更新输入契约与所需资料", "请按新版契约准备本次核算数据"]
        else:
            updates = ["更新随包说明、填写模板或独立运行脚本", "核算规则版本保持不变，下载最新包使用"]
        item["updates"] = updates if changed else last["updates"]
        if changed:
            releases.insert(0, {"id":f"{subject}-{item['fingerprint']}", "skill_id":subject,
                "name":item["name"], "title":f"{item['name']} Skill 上新", "released_at":now,
                "kind":"update" if last else "new", "package_version":item["package_version"],
                "rule_version":item["rule_version"], "updates":item["updates"]})
        item["is_new"] = (datetime.fromisoformat(now) - datetime.fromisoformat(item["released_at"])).days < 30
        files["references/provenance.json"] = json_bytes({key:item[key] for key in
            ("id", "rule_version", "package_version", "released_at", "fingerprint", "source_sha256")})
        data = zip_bytes({f"{item['slug']}/{key}":value for key,value in files.items()})
        item["sha256"] = sha256(data).hexdigest()
        item["size_bytes"] = len(data)
        item["download_url"] = f"/api/domestic-labor/skillhub/{subject}/download?release={item['fingerprint']}"
        bundles[subject] = data
        skills.append(item)
    return {"skills":skills, "releases":releases, "updated_at":max(item["released_at"] for item in skills)}, bundles


def current_catalog():
    from ...config import OUTPUT_DIR
    path = OUTPUT_DIR / "domestic_skillhub" / "catalog.json"
    with LOCK:
        previous = _load_catalog(path if path.exists() else ASSETS / "releases.json")
        catalog, bundles = sync_catalog(previous)
        if catalog != previous:
            path.parent.mkdir(parents=True, exist_ok=True)
            temp = path.with_suffix(".tmp")
            temp.write_bytes(json_bytes(catalog))
            temp.replace(path)
        return catalog, bundles


def export_release(destination, catalog_path=None):
    """Build the durable release ledger and user-facing standalone ZIP packages."""
    previous = _load_catalog(catalog_path or ASSETS / "releases.json")
    catalog, bundles = sync_catalog(previous)
    ledger = catalog_path or ASSETS / "releases.json"
    temporary = ledger.with_suffix(".tmp")
    temporary.write_bytes(json_bytes(catalog))
    temporary.replace(ledger)
    destination.mkdir(parents=True, exist_ok=True)
    for item in catalog["skills"]:
        (destination / f"{item['name']} skill.zip").write_bytes(bundles[item["id"]])
    (destination / "全部中国区外包工薪酬 Skill.zip").write_bytes(zip_bytes({f"{item['name']} skill.zip":bundles[item["id"]] for item in catalog["skills"]}))
    return catalog
