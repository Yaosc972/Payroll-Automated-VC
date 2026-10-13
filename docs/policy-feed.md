# 政策资讯试接入

首页抽屉读取 `/api/workbench/policies?q=&offset=0`，仅已登录用户可用。查询不触发外部抓取。列表展示官方标题、发布日期和原文；不生成政策解读、不推断生效日期、不更改核算规则。地区标签表示来源所属地区，不替代政策适用范围。

## 来源及覆盖

来源清单：`bonus_platform/engine/policy/sources.json`，当前启用以下 15 个官方来源。每个来源仅采集当前列表页中最多 20 篇符合企业人事主题的文章，不代表完整历史库或全国覆盖。

| 类型 | 官方网站 | 采集栏目 |
| --- | --- | --- |
| 医保 | 国家医疗保障局 | [官方栏目](https://www.nhsa.gov.cn/col/col104/index.html) |
| 公积金 | 北京住房公积金管理中心 | [官方栏目](https://gjj.beijing.gov.cn/) |
| 社保 | 上海市人力资源和社会保障局 | [官方栏目](https://rsj.sh.gov.cn/tshbx_17729/) |
| 公积金 | 广州住房公积金管理中心 | [官方栏目](https://gjj.gz.gov.cn/gg/tzgg/index.html) |
| 公积金 | 深圳市住房和建设局 | [官方栏目](https://zjj.sz.gov.cn/ztfw/zfgjj/zcfg/) |
| 社保 | 广州市人力资源和社会保障局 | [官方栏目](https://rsj.gz.gov.cn/ywzt/shbz/tzgg/) |
| 社保 | 北京市人力资源和社会保障局 | [官方栏目](https://rsj.beijing.gov.cn/zzcwj/) |
| 社保 | 深圳市社会保险基金管理局 | [官方栏目](https://hrss.sz.gov.cn/szsi/sbjxxgk/zcfggfxwj/zcfg/) |
| 医保 | 山西省医疗保障局 | [官方栏目](https://ybj.shanxi.gov.cn/xxfb/fdzdgknr/gfxwj/) |
| 医保 | 黑龙江省医疗保障局 | [官方栏目](https://ybj.hlj.gov.cn/ybj/c105387/list.shtml) |
| 医保 | 江苏省医疗保障局 | [官方栏目](https://ybj.jiangsu.gov.cn/col/col73935/index.html) |
| 医保 | 河南省医疗保障局 | [官方栏目](https://ylbz.henan.gov.cn/zcfg/) |
| 医保 | 湖南省医疗保障局 | [官方栏目](https://ybj.hunan.gov.cn/ybj/first113541/firstF/f2113606/index.html) |
| 医保 | 广东省医疗保障局 | [官方栏目](https://hsa.gd.gov.cn/zwgk/zcfg/) |
| 医保 | 陕西省医疗保障局 | [官方栏目](https://ybj.shaanxi.gov.cn/zfxxgk/fdzdgknr/zcwj/) |

2026-10-13 修复：上海采集入口更换为现行规范性文件“社会保险”栏目，并限制文章路径；使用修复后的采集器，本地实采上海社保 6 篇、广州公积金 2 篇、深圳社保 6 篇、山西医保 1 篇、湖南医保 1 篇，5 个来源均返回 `ok`。真实官方链接和发布日期片段保留在 `tests/fixtures/policy/`，覆盖解析回归。诊断中默认 HTTP 客户端访问上海、深圳曾返回 403 拦截页，使用采集器声明的请求身份读取成功；不能把这次本地成功当作生产网络已恢复，发布后必须核验真实 `policy_source_checks`。

连接建立超时由 8 秒调整为 15 秒，读取超时仍为 8 秒；连接失败或连接超时只重试一次。HTTP 拒绝、重定向、证书验证失败不通过重试或降低安全校验掩盖。详情失败记录失败篇数及首个安全错误码，方便定位。

页面持续展示成功、失败、部分失败、待首次抓取的来源数量及最近抓取检查时间（北京时间）。展开来源可查看网站、最近检查、最近完整成功及失败原因；超过 3 小时未检查另行提示。最近检查时间不是文章发布日期，也不代表全部来源成功。检查成功可以包含零篇符合条件的文章，不等于有近期更新。失败保留已有文章和上次完整成功时间。

全国候选目录：`bonus_platform/engine/policy/national-directory.json`，来源为国家医保局官方地方医保网站目录 `https://www.nhsa.gov.cn/col/col28/index.html`，包含 31 个省级医保部门及新疆生产建设兵团。目录入口经过本地访问检查；能读取首页仍可能只返回动态页面，因此 `needs_adapter` 不代表已接通。`adapter_verified` 仅表示该日期已完成当前栏目采集验证；`unreachable` 表示本次请求失败。快照不是持续健康监控，最新已启用来源状态以数据库 `policy_source_checks` 为准。未纳入 `sources.json` 的候选不会被定时采集。此目录不覆盖各市县人社、公积金等全部部门，不能宣称全国全部政策覆盖。

扩展城市时核验官方域名、列表地址、文章路径模式、发布日期元数据，并完成真实采集验证。不得绕过网站访问控制。公告正文不存储；链接及标题去重键为规范化官方原文 URL 的 SHA256。

## 本地验证

```sh
python3 -m scripts.policy_feed migrate --db /tmp/policy-local.sqlite
python3 -m scripts.policy_feed refresh --all --db /tmp/policy-local.sqlite
python3 -m pytest -q tests/test_policy_feed.py tests/test_static_branding.py
```

## 公司生产调度与验证

公司环境通过 `bonus_platform/engine/policy/scheduler.py` 调度：`SIGMA_POLICY_REFRESH_ENABLED=true` 时启动，依赖持久 MySQL，启动后约 60 秒首次检查，此后每小时一次。默认按最久未检查排序，每次最多 8 个来源，15 个来源正常约两轮检查完成。使用 MySQL 命名锁防止多个应用副本同时执行。定时任务不等于所有来源抓取成功，结果以数据库逐来源状态为准。

独立初始化迁移由 `python3 -m scripts.policy_feed migrate` 执行；Web 请求不建表。当前修复不新增表或修改 schema。全量初始化可通过 `python3 -m scripts.policy_feed refresh --all` 执行，但需要对应环境操作授权；本次验证仅使用本地数据与官方页面，没有刷新生产数据库。

原 Vercel 的 `vercel.json` 每日 cron 声明保留，接口复用 `CRON_SECRET` Bearer 校验；不能将这一声明视为公司生产的运行计划。查询接口仅返回数据，不触发外部抓取。

发布后检查：政策接口的 15 个来源状态、时间、失败原因；观察两轮公司定时任务后的检查时间是否推进，并确认失败来源真实恢复。不能用页面显示“抓取成功”的测试数据代替生产验收。

默认列表和关键词/类型查询均只展示最近 180 天（含边界）且不晚于当前北京时间日期的文章。旧记录保留在数据库，不因发布时间直接标为失效。招聘、采购、个案催缴及标题明确标注已失效/已废止的记录不显示；此规则不代表已完成政策法律效力审查。

企业人事相关性：采集和查询共用标题规则，优先收录缴费/缴存、参保增减员、费率、退休、生育待遇、工伤办理等主题；剔除医药行业监管、药品、医用设备、居民专属政策等。规则只依据标题，可能漏掉标题不明确的相关政策，需要定期人工复核；不代表已对正文作出业务适用性判断。

征求意见稿、诊疗项目及医疗机构制剂目录暂不进入正式政策资讯；详情页完整标题会再次校验，避免列表截断标题误收录。官方页面的发布日期可能是补录或重发时间，不代表政策生效日期或文件制定年份。
