/* Rule reader and illustrative calculators for the published 1.4.9 rule package. */
(function (global) {
  'use strict';
const copy = {
  gangwei_butie: {
    intro:'按地区、岗位及特殊人员标准计发，按排班天数与缺勤时数折算。',
    stats:[['56','小时','不超过此值不扣减'],['8','小时','超过门槛后折算 1 天']],
    formula:'月标准 ÷ 排班天数 ×（排班天数 − 扣减天数）',
    caption:'缺勤 ≤ 56 小时：扣减 0 天。缺勤 > 56 小时：全部缺勤小时 ÷ 8。金额最低为 0，保留两位小数。',
    standards:[[['内部初级 / 中级 / 高级安检员','300 / 450 / 650 元'],['民航初级 / 中级安检员','1,300 / 1,500 元'],['叉车司机 / 陈晓龙','800 元'],['HRBP专员、高级HRBP专员、高级招聘专员','2026年9月起不发']], [['内部初级 / 中级 / 高级安检员','300 / 450 / 650 元 · 待验证'],['民航初级 / 中级安检员','1,300 / 1,500 元 · 待验证']], [['贾万 · 特殊安检组长','600 元 · 已确认']]],
    rules:[['缺勤时数范围','事假、排休请假、病假、旷工、休年假、女神假、其他带薪假、调休及入离职缺勤，合并计算。女神假天数 × 8 折算为小时。'],['56小时临界值','不扣减。只有超过 56 小时，才把全部缺勤时数折算为扣减天数。'],['入离职缺勤折算','已有非零入离职缺勤时数时使用该值；否则按 max（排班天数 − 实际在职工作日天数，0）× 8 计算。'],['资格识别依据','按地区、岗位名称或特殊人员名单匹配；职级不参与。旧称安检员、民航高级安检员等未明确金额的岗位，不自行套档。'],['东莞人力岗位','HRBP专员、高级HRBP专员、高级招聘专员：2026年8月及以前按700元/月折算，9月起不再计发。'],['晋江特殊人员','贾万月标准600元已确认，实际金额仍按排班与缺勤规则折算。']],
    pending:[['部分岗位月标准','东莞旧称安检员、民航高级安检员、揽收充电司机；嘉善／义乌旧称安检员、民航高级安检员的标准仍待确认，当前暂计0元。'],['嘉善／义乌已套用的标准','内部初／中／高级与民航初／中级安检员标准仍需线下结果验证。']]
  },
  yeban_butie: {
    intro:'按适用范围、夜班窗口内的有效出勤及休息扣除时长逐日计发。',
    stats:[['22:00–08:00','','普通夜班窗口'],['3','元/小时','满 1 小时起计'],['25','元/日','早晚窗口合计封顶']],
    formula:'当日补贴 = 各夜班窗口有效时长 × 3 元/小时，合计最高 25 元',
    caption:'每个窗口先扣除休息，再独立判断满 1 小时门槛，按完整 30 分钟计发；月度汇总后保留两位小数。LB15 另按正班折算。',
    rules:[['打卡时间取整','上班向后、下班向前取整到半小时。普通夜班计薪起点不得早于排班开始时间。'],['只扣重叠休息','班次休息段、取整后的实际出勤段和夜班窗口，三者重叠的部分才扣除。夜班窗口外的休息不扣。'],['早晚两个窗口','分别扣休息、判断1小时门槛与半小时取整后合计，共用每天25元上限。'],['LB15 凌晨3点班','仅计算03:00–11:30正班区间。8小时发25元，不足按比例折算；正班后的加班不抵迟到或早退。'],['晋江不享有范围','计件岗、门禁岗，以及当月名单内不享有人员排除。考勤自动识别和名单可同时使用，同一人同一天重复命中只排除一次。'],['班次与打卡边界','缺卡当日不计补贴；应计补贴的班次必须先确认休息安排，生效日期需覆盖考勤。打卡跨度超过16小时本身不改变计发公式。']],
    pending:[['白班、早班与排班结束边界','白班或早班覆盖夜间时是否享有，以及排班结束后进入夜间的打卡是否计发，仍需统一口径。排班开始前不计发已确认。'],['周末休息日有打卡','周六、周日标记为休息但实际出勤的计发资格尚待确认。'],['连班特殊扣减','连班登记及特殊扣减规则仍待业务补充。'],['其他地区与异常有效时长','其他地区适用口径、扣除休息后有效时长异常的记录仍需复核，当前暂算金额计入应发。']]
  },
  waisu_butie: {
    intro:'按地区岗位资格、在职与住宿区间及地区缺勤口径核算。',
    stats:[['150','元/月','统一月标准'],['退宿当天','','不计入住宿扣除']],
    formula:'东莞／嘉善／义乌：150 元 ÷ 当月自然日天数 × 有效补贴天数',
    caption:'晋江按“150元 − 入离职扣减 − 请假扣减”计算；各地区缺勤口径不同。',
    rules:[['入住和退宿','入住当天计为住宿；退宿当天不计入住宿扣除，从退宿当天开始计外宿补贴。'],['在职与住宿重叠','在职天数按入职日期与最后工作日截取。外宿补贴天数 = max（在职天数 − 住宿扣除天数，0）。'],['东莞缺勤','事假、排休请假、病假、旷工和入离职缺勤计入；休年假等有薪假不计。全月在职缺勤达到56小时且仍在宿时为0；无住宿扣除时按缺勤小时折算。'],['嘉善／义乌缺勤','有薪假、事假、调休、旷工等计入，病假按60%计入。入离职当月同样折算；缺勤达到56小时且仍在宿时为0。'],['晋江扣减','入离职按未在职自然日扣减；请假旷工合计超过7天时，按天数折算请假扣减。'],['不发放情形','全月无打卡且非当月入离职时为0。所有地区正班出勤不超过1天且旷工达到1天时为0；旷工不足1天不因此归零。']],pending:[]
  },
  canbu:{
    intro:'按地区、部门、岗位及有效出勤计发，适用地区分别执行逐日或月度折算。',
    stats:[['19','元/天','东莞 · 月封顶500元'],['300','元/月','嘉善／义乌'],['0','元','晋江不发放']],
    formula:'东莞：逐日餐补合计，月封顶 500 元；嘉善／义乌：按月标准折算',
    caption:'东莞有效时数 = max（正班时数，刷卡加班）。不超过8小时按19÷8折算，超过8小时按19元计发。',
    rules:[['东莞资格','部门命中寮步区或莞深操作，且岗位属于享有名单。旷工日期不发。'],['嘉善／义乌资格','岗位属于享有名单，包含已确认的查验员。结果限制在0至300元。'],['嘉善／义乌折算','300 ÷ 排班天数 ×（实际在职工作日天数 − 事假时数÷8 − 旷工天数 − 病假时数÷8×0.4）。'],['地区归属','优先采用员工日考勤中出现次数最多的地区，缺失时采用月考勤地区。'],['安检岗位识别','安检员、民航初／中／高级、内部初／中／高级安检员，按这7个名称精确识别。'],['金额精度','东莞单日金额保持原始精度，月度汇总封顶后统一保留两位小数。上传的餐补标准不参与判断。']],pending:[]
  },
  quanqinjiang:{
    intro:'全区域月标准100元；迟到豁免档位互斥，需同时满足其他全勤条件。',
    stats:[['100','元/月','全部条件满足时'],['3','次','签卡次数上限']],
    formula:'迟到豁免符合 + 未命中排除项 + 满足入离职边界 → 100 元',
    caption:'任意一项不符合则为0元。各地区金额相同。',
    rules:[['迟到两档不能混用','6分钟内最多3次，或6–20分钟内最多1次；两档同时出现，即使次数分别未超，也不享有。20–30分钟内迟到不享有。'],['缺勤与扣款','旷工、工伤假、事假、病假、入离职缺勤或迟到早退30分钟内扣款任一大于0，不发放。'],['签卡与有薪假','签卡次数不超过3次；休年假和排休请假不单独影响全勤奖。'],['入离职边界','月初至入职日前有工作日时不发；最后工作日早于当月月末时不发。'],['特殊排除名单','工号 OWHN9535、OWHN9353、OWHX0190 固定不发放。'],['迟到分档','必须有三个迟到分档的次数，不能只根据迟到总次数判断是否享有豁免。']],pending:[]
  },
  gonglingjiang:{
    intro:'以每月1日的完整司龄确定标准，再按部门、岗位与缺勤规则计算。',
    stats:[['150','元/年','东莞操作／第四纵队 · 上限600元'],['100','元/年','FBU · 上限500元'],['50','元/年','晋江等适用范围 · 上限150元']],
    formula:'基础月标准 = 每年标准 × 完整司龄，达到地区／部门上限后不再增加',
    caption:'再按各范围的缺勤和入离职规则折算。FBU不设56小时门槛。',
    rules:[['完整司龄起算日期','以核算月1日计算。入职日不是当月1日时，对应周年当月未满整年，次月才增加一年。'],['东莞操作资格','中国操作部、B操作部的已确认一线岗位享有；保洁、组长、主管等未命中岗位不发放，职级不参与。'],['第四纵队揽收','工号命中揽收线工龄奖名单且岗位不包含组长，不限制工作地区。'],['56小时门槛','除FBU外，事假、病假、旷工和排休请假合计达到56小时后按排班折算；入离职缺勤按通用规则另行扣减。此门槛与岗位补贴不同。'],['FBU独立折算','入离职缺勤、事假、病假和旷工合并折算一次，不设56小时门槛，不包含排休请假；不因正班出勤为0直接归零。'],['不发放范围','嘉善／义乌操作条线，以及华东枢纽、华东揽收组、华东B2B枢纽、华西区操作部不发。其他非FBU范围正班出勤为0且有事假时为0。']],
    pending:[['重新入职是否重置司龄','自离后重新入职是否重新起算，尚待业务明确。'],['东莞文员资格','制度与线下结果存在差异；确认前暂不开放文员。']]
  },
  gaowen_butie:{
    intro:'每年6–10月，按同网点、同日期、同白／夜班温度及实际出勤计发。',
    stats:[['33','℃','当班最高温度门槛'],['6–10','月','每年计发期间']],
    formula:'当日金额 = 实际出勤时长 × 地区小时单价，先按日封顶，再按月封顶',
    caption:'同网点、同日、同班次最高温度达到33℃才进入计算。正班时数与刷卡加班取较大值。',
    standards:[[['小时标准 / 单日上限 / 月上限','1.725 / 13.80 / 300 元']],[['小时标准 / 单日上限 / 月上限','1.15 / 9.20 / 200 元']],[['小时标准 / 单日上限 / 月上限','1.50 / 12.00 / 260 元']]],
    rules:[['计发期间','每年6月1日至10月31日；其他月份不计发。'],['测温匹配范围','只取员工同网点、同出勤日期、同白／夜班最高温度，不能用白班温度替代夜班。'],['资格排除','办公地点明确有空调的员工不计发；各地固定排除名单仍适用。职级、领色不参与判断。'],['休息日与节假日','有符合条件的实际出勤时，工作日、休息日、法定节假日均用同一逐日公式。'],['测温缺失处理','测温区缺少同班次测温记录时为0，文件漏传不能按“无测温区域”全额发放。'],['金额精度','逐日金额保持原始精度，月度合计封顶后保留两位小数。']],
    pending:[['无测温区域和驻场人员','哪些区域／人员可以按月全额发放，须有明确名单，不能由测温记录缺失推断。'],['晋江33℃门槛','当前同样应用同网点、同日、同班次33℃门槛，最终适用口径仍待业务确认。']]
  }
};

const ORDER = ['canbu', 'waisu_butie', 'yeban_butie', 'gangwei_butie', 'gaowen_butie', 'quanqinjiang', 'gonglingjiang'];
const sessions = new Map();
const activeRegions = new Map();
const esc = value => String(value ?? '').replace(/[&<>"']/g, char => ({'&':'&amp;', '<':'&lt;', '>':'&gt;', '"':'&quot;', "'":'&#39;'}[char]));
const number = value => Number(Number(value).toFixed(4)).toLocaleString('zh-CN', {maximumFractionDigits:4});
const money = value => value.toLocaleString('zh-CN', {minimumFractionDigits:2, maximumFractionDigits:2});
const clamp = (value, min, max) => Math.min(max, Math.max(min, value));
function roundMoney(value, even = false) {
  const scaled = value * 100, lower = Math.floor(scaled);
  if (even && Math.abs(scaled - lower - .5) < 1e-8) return (lower % 2 === 0 ? lower : lower + 1) / 100;
  return Math.round((value + 1e-10) * 100) / 100;
}
const range = (key, label, value, min, max, step = 1, unit = '小时') => ({key, label, value, min, max, step, unit, type:'range'});
const select = (key, label, value, options) => ({key, label, value, options, type:'select'});
const monthDays = () => select('monthDays', '当月自然日天数', '31', [28,29,30,31].map(days => [String(days), `${days}天`]));
const scheduled = () => range('scheduled', '排班天数', 25, 1, 31, 1, '天');
const hoursCases = [
  {label:'56小时', values:{absence:56}},
  {label:'56.5小时', values:{absence:56.5}},
  {label:'81.5小时', values:{absence:81.5}},
];

function model(id, region, values = {}) {
  const c = copy[id];
  const m = {title:'互动计算示例', fields:[], presets:[], stats:c.stats, formula:c.formula, caption:c.caption,
    assumption:'示例假设员工符合所选范围的计发资格，其他排除条件未发生。'};
  if (id === 'gangwei_butie') {
    const security = [['300','内部初级安检员 · 300元'], ['450','内部中级安检员 · 450元'], ['650','内部高级安检员 · 650元'], ['1300','民航初级安检员 · 1,300元'], ['1500','民航中级安检员 · 1,500元']];
    const standards = region === 2 ? [['600','贾万 · 特殊人员标准600元']] : region === 1 ? security : [['800','叉车司机 / 陈晓龙 · 800元'], ...security];
    m.fields = [select('standard', '适用岗位 / 月标准', standards[0][0], standards), scheduled(), range('absence','缺勤合计时数',56,0,248,.5)];
    m.presets = hoursCases;
    m.assumption = `缺勤合计已包括本岗位适用的各类请假和入离职缺勤。${region === 1 ? '嘉善／义乌已套用的安检标准仍待线下结果验证。' : ''}`;
  } else if (id === 'canbu') {
    if (region === 2) {
      m.fixed = true; m.reason = '晋江不发放餐补。'; m.stats = [['0','元','晋江餐补标准']]; m.formula = '晋江餐补 = 0元'; m.caption = '本地区无餐补折算参数。';
    } else if (region === 0) {
      m.fields = [range('hours','每日有效出勤时数',8,0,16,.5), range('days','符合条件的出勤天数',25,0,31,1,'天')];
      m.stats = [['19','元/天','满8小时日标准'], ['500','元/月','月度上限']];
      m.formula = '月餐补 = min（日餐补 × 符合条件的出勤天数，500元）';
      m.caption = '日餐补 = min（有效出勤时数，8）× 19 ÷ 8；月度汇总后保留两位小数。';
      m.assumption = '假设各出勤日有效时数相同，均符合部门、岗位资格且无旷工；有效时数取正班时数与刷卡加班的较大值。';
      m.presets = [{label:'半天出勤',values:{hours:4,days:25}}, {label:'正常整月',values:{hours:8,days:25}}, {label:'月度封顶',values:{hours:8,days:31}}];
    } else {
      m.fields = [scheduled(), range('employed','实际在职工作日天数',25,0,Number(values.scheduled || 25),1,'天'), range('personal','事假时数',0,0,248,.5), range('sick','病假时数',0,0,248,.5), range('absentDays','旷工天数',0,0,31,.5,'天')];
      m.stats = [['300','元/月','月标准与上限'], ['40','%','病假扣减比例']];
      m.formula = '300 ÷ 排班天数 ×（在职工作日 − 事假÷8 − 旷工天数 − 病假÷8×40%）';
      m.caption = '结果限制在0至300元，保留两位小数。';
      m.presets = [{label:'无缺勤',values:{personal:0,sick:0,absentDays:0}}, {label:'事假8小时',values:{personal:8,sick:0,absentDays:0}}, {label:'病假8小时',values:{personal:0,sick:8,absentDays:0}}];
    }
  } else if (id === 'waisu_butie') {
    const days = Number(values.monthDays || 31);
    if (region === 2) {
      m.fields = [monthDays(), range('entryDays','入离职未在职自然日',0,0,days,1,'天'), range('leaveDays','请假与旷工合计天数',7,0,days,.5,'天')];
      m.stats = [['150','元/月','月标准'], ['7','天','请假旷工超过此值才扣减']];
      m.formula = '晋江外宿补贴 = max（150 − 入离职扣减 − 请假扣减，0）';
      m.caption = '两项扣减分别按150÷当月自然日折算；请假旷工超过7天时扣除全部天数。';
      m.presets = [{label:'请假7天',values:{leaveDays:7}}, {label:'请假7.5天',values:{leaveDays:7.5}}, {label:'请假10天',values:{leaveDays:10}}];
      m.assumption = '假设符合晋江外宿资格、未住宿且有正常出勤；入离职和请假天数按各自口径汇总。';
    } else {
      m.fields = [select('scenario','计算场景','checkout',[['checkout','退宿日期折算'],['absence','全月外宿 · 缺勤折算']]), monthDays()];
      if (values.scenario === 'absence') {
        m.fields.push(range('absence','按地区口径汇总的缺勤时数',56,0,248,.5));
        m.stats = [['150','元/月','月标准'], ['56','小时','达到此值开始缺勤折算']];
        m.formula = '150 ÷ 当月自然日 ×（当月自然日 − 缺勤扣减天数）';
        m.caption = '缺勤不足56小时不扣减，达到56小时后按全部缺勤时数÷8折算。';
        m.assumption = `假设全月在职、全月无住宿扣除且有正常出勤。${region === 1 ? '嘉善／义乌病假按60%计入缺勤，其他有薪假按地区规则计入。' : '东莞缺勤合计不含年假等有薪假。'}`;
        m.presets = [{label:'55.5小时',values:{absence:55.5}}, {label:'56小时',values:{absence:56}}, {label:'80小时',values:{absence:80}}];
      } else {
        m.fields.push(select('housing','住宿状态','checkout',[['checkout','当月退宿'],['staying','整月在宿']]));
        if(values.housing!=='staying')m.fields.push(range('checkout','退宿日期',10,1,days,1,'日'));
        m.formula = '外宿补贴 = 150 ÷ 当月自然日 × 外宿天数';
        m.caption = '本例从1日入住，退宿当天开始计发外宿补贴；整月在宿时不计发。';
        m.assumption = '假设全月在职、无缺勤，且符合所选地区的岗位资格。';
        m.presets = [{label:'1日退宿',values:{housing:'checkout',checkout:1}}, {label:'10日退宿',values:{housing:'checkout',checkout:10}}, {label:'整月未退宿',values:{housing:'staying'}}];
      }
    }
  } else if (id === 'yeban_butie') {
    if (region === 3) {
      m.fields = [range('late','迟到折算时长',0,0,8,.5), range('early','早退折算时长',0,0,8,.5)];
      m.stats = [['03:00–11:30','','LB15正班区间'], ['25','元/日','8小时满额标准']];
      m.formula = 'LB15补贴 = max（8 − 迟到折算 − 早退折算，0）÷ 8 × 25元';
      m.caption = '正班结束后的加班不抵消迟到或早退。';
      m.assumption = '输入时长已按打卡半小时取整规则折算，仅演示LB15正班扣减。';
      m.presets = [{label:'正班完整',values:{late:0,early:0}}, {label:'迟到半小时',values:{late:.5,early:0}}, {label:'早退1小时',values:{late:0,early:1}}];
    } else {
      m.fields = [range('evening','晚间窗口有效时数',8,0,10,.25), range('morning','早间窗口有效时数',0,0,8,.25)];
      m.presets = [{label:'不足1小时',values:{evening:.75,morning:0}}, {label:'两窗口各0.75小时',values:{evening:.75,morning:.75}}, {label:'单日封顶',values:{evening:8.5,morning:0}}];
      m.assumption = `输入为打卡取整、排班开始时间限制及重叠休息扣除后的各窗口有效时数；假设资格与休息配置已确认、无缺卡。${region === 4 ? '其他地区按当前通用口径暂算。' : ''}`;
    }
  } else if (id === 'quanqinjiang') {
    m.fields = [range('minor','6分钟内迟到次数',0,0,5,1,'次'), range('middle','6–20分钟迟到次数',0,0,3,1,'次'), range('major','20–30分钟迟到次数',0,0,2,1,'次'), range('signs','签卡次数',0,0,5,1,'次'), select('eligible','其他全勤条件','yes',[['yes','全部满足'],['no','存在不符合项']])];
    const base = {minor:0,middle:0,major:0,signs:0,eligible:'yes'};
    m.presets = [{label:'全勤',values:base}, {label:'短时迟到3次',values:{...base,minor:3}}, {label:'两档混用',values:{...base,minor:2,middle:1}}, {label:'签卡超限',values:{...base,signs:4}}];
    m.assumption = '“其他全勤条件”包括缺勤与扣款、入离职日期边界及特殊排除名单。';
  } else if (id === 'gonglingjiang') {
    const fbu = region === 2, rate = fbu ? 100 : region >= 4 ? 50 : 150, cap = fbu ? 500 : region >= 4 ? 150 : 600;
    m.rate = rate; m.cap = cap; m.fbu = fbu;
    if ([3,6].includes(region)) {
      m.fixed = true; m.reason = '所选部门范围不发放工龄奖。'; m.stats = [['0','元','本范围工龄奖标准']]; m.formula = '本范围工龄奖 = 0元'; m.caption = '适用范围以所选地区或部门的资格说明为准。';
    } else {
      m.fields = [range('years','每月1日的完整司龄',2,0,10,1,'年'), scheduled(), range('absence',fbu ? '事假、病假及旷工合计' : '事假、病假、旷工及排休合计',0,0,248,.5), range('entryHours','入离职缺勤时数',0,0,248,.5)];
      m.stats = [[String(rate),'元/年','每满一年的月标准增量'], [String(cap),'元/月','基础月标准上限'], ...(fbu ? [] : [['56','小时','达到此值开始请假折算']])];
      m.formula = fbu ? '月标准 ÷ 排班天数 ×〔排班天数 −（入离职缺勤 + 事病旷）÷ 8〕' : '月标准 − 请假扣减 − 入离职缺勤扣减';
      m.caption = `月标准 = min（${rate} × 完整司龄，${cap}）。${fbu ? '缺勤不含排休，不设56小时门槛，合并折算一次。' : '请假合计达到56小时后按全部时数扣减；入离职缺勤另行折算。'}`;
      m.assumption = '假设岗位及部门符合资格，未触发“正班出勤为0且存在事假”的归零条件；司龄为核算月1日已满的整年数。';
      m.presets = fbu ? [{label:'无缺勤',values:{absence:0,entryHours:0}}, {label:'请假8小时',values:{absence:8,entryHours:0}}, {label:'含入离职缺勤',values:{absence:8,entryHours:16}}] : [{label:'55.5小时',values:{absence:55.5,entryHours:0}}, {label:'56小时',values:{absence:56,entryHours:0}}, {label:'满3年司龄',values:{years:3}}];
    }
  } else if (id === 'gaowen_butie') {
    const [rate, daily, cap] = [[1.725,13.8,300],[1.15,9.2,200],[1.5,12,260]][region];
    m.rate = rate; m.daily = daily; m.cap = cap;
    m.stats = [[String(rate),'元/小时','地区小时标准'], [daily.toFixed(2),'元/日','单日上限'], [String(cap),'元/月','月度上限']];
    const calendarDays = [31,28,31,30,31,30,31,31,30,31,30,31][Number(values.month || 9)-1] || 31;
    m.fields = [select('month','计发月份','9',Array.from({length:12},(_,i)=>[String(i+1),`${i+1}月`])), select('shift','温度匹配班次','day',[['day','白班'],['night','夜班']]), range('temperature','当班最高温度',34.2,28,40,.1,'℃'), range('hours','每日有效出勤时数',8,0,16,.5), range('days','符合条件的出勤天数',25,0,calendarDays,1,'天')];
    m.formula = `当日补贴 = min（有效出勤时数 × ${rate}，${daily.toFixed(2)}元）；月度最高${cap}元`;
    m.caption = '6–10月，同网点、同日、同白／夜班最高温度达到33℃时计发；逐日金额不舍入，月度汇总后保留两位小数。';
    m.assumption = `假设员工符合资格且无空调排除条件，各出勤日的当班温度及有效时数均与设置一致；有效时数取正班与刷卡加班的较大值。${region === 2 ? '晋江33℃门槛仍待最终业务确认。' : ''}`;
    m.presets = [{label:'32.9℃',values:{temperature:32.9}}, {label:'33℃临界值',values:{temperature:33}}, {label:'34.2℃',values:{temperature:34.2}}];
  }
  return m;
}

function normalize(m, input) {
  const values = {};
  for (const field of m.fields) {
    const raw = input[field.key] ?? field.value;
    values[field.key] = field.type === 'select'
      ? (field.options.some(([value]) => value === String(raw)) ? String(raw) : field.value)
      : clamp(Number.isFinite(Number(raw)) ? Number(raw) : field.value, field.min, field.max);
    if (field.type === 'range') values[field.key] = Number((Math.round(values[field.key] / field.step) * field.step).toFixed(4));
  }
  return values;
}

// These calculations explain controlled examples. They do not write to payroll runs.
function calculate(id, region, input = {}) {
  let m = model(id, region, input);
  let v = normalize(m, input);
  m = model(id, region, v); v = normalize(m, v);
  const r = {amount:0, unit:'元/月', reason:'', equation:'', metrics:[], visual:'', values:v, model:m};
  if (m.fixed) return {...r, reason:m.reason, equation:'应发金额 = 0元'};
  if (id === 'gangwei_butie') {
    const deduction = v.absence > 56 ? v.absence / 8 : 0, payable = Math.max(v.scheduled - deduction, 0);
    r.amount = roundMoney(Number(v.standard) / v.scheduled * payable);
    r.reason = deduction ? `缺勤超过56小时，全部时数折算扣减${number(deduction)}天` : '缺勤不超过56小时，不扣减';
    r.equation = `${v.standard} ÷ ${v.scheduled} × max（${v.scheduled} − ${number(deduction)}，0）`;
    r.metrics = [['月标准',`${number(v.standard)}元`], ['扣减天数',`${number(deduction)}天`], ['计发天数',`${number(payable)}天`]];
    r.visual = 'absence'; r.deduction = deduction; r.payable = payable;
  } else if (id === 'canbu') {
    if (region === 0) {
      r.dayAmount = Math.min(v.hours,8) * 19 / 8; r.raw = r.dayAmount * v.days; r.cap = 500;
      r.amount = roundMoney(Math.min(r.raw,500)); r.reason = r.raw > 500 ? '月度合计超过500元，按上限计发' : '按有效出勤逐日折算';
      r.equation = `min〔（min（${number(v.hours)}，8）× 19 ÷ 8）× ${v.days}，500〕`;
      r.metrics = [['单日未舍入金额',`${number(r.dayAmount)}元`], ['月度未封顶金额',`${number(r.raw)}元`], ['月度上限','500元']]; r.visual = 'cap';
    } else {
      const effective = Number((v.employed-v.personal/8-v.absentDays-v.sick/8*.4).toFixed(4));
      r.amount = roundMoney(clamp(300/v.scheduled*effective,0,300),true);
      r.reason = effective > 0 ? '病假按40%折算扣减，月度金额不超过300元' : '扣减后有效天数不大于0，应发0元';
      r.equation = `300 ÷ ${v.scheduled} ×（${v.employed} − ${number(v.personal/8)} − ${number(v.absentDays)} − ${number(v.sick/8)} × 40%）`;
      r.metrics = [['在职工作日',`${v.employed}天`], ['病假扣减天数',`${number(v.sick/8*.4)}天`], ['有效计发天数',`${number(Math.max(effective,0))}天`]];
      r.visual = 'days'; r.payable = Math.max(effective,0); r.total = v.scheduled;
    }
  } else if (id === 'waisu_butie') {
    const days = Number(v.monthDays);
    if (region === 2) {
      const entry = roundMoney(150/days*v.entryDays,true), leave = v.leaveDays>7 ? roundMoney(150/days*v.leaveDays,true) : 0;
      r.amount = roundMoney(Math.max(150-entry-leave,0),true);
      r.reason = v.leaveDays>7 ? '请假旷工超过7天，按全部天数折算扣减' : '请假旷工不超过7天，仅扣除入离职未在职天数';
      r.equation = `max（150 − ${money(entry)} − ${money(leave)}，0）`;
      r.metrics = [['月标准','150元'],['入离职扣减',`${money(entry)}元`],['请假扣减',`${money(leave)}元`]];
      r.visual = 'deductions'; r.entry = entry; r.leave = leave;
    } else if (v.scenario === 'absence') {
      const deduction = v.absence>=56 ? v.absence/8 : 0; r.payable = Math.max(days-deduction,0); r.total=days;
      r.amount = roundMoney(150/days*r.payable,true);
      r.reason = v.absence>=56 ? '达到56小时门槛，按全部缺勤时数折算' : '缺勤不足56小时，按月标准计发';
      r.equation = `150 ÷ ${days} × max（${days} − ${number(deduction)}，0）`;
      r.metrics = [['自然日天数',`${days}天`],['扣减天数',`${number(deduction)}天`],['有效天数',`${number(r.payable)}天`]]; r.visual='days';
    } else {
      r.housed = v.housing==='staying' ? days : v.checkout-1; r.payable=days-r.housed; r.total=days;
      r.amount = roundMoney(150/days*r.payable,true);
      r.reason = v.housing==='staying' ? '整月未退宿，外宿补贴为0元' : `${v.checkout}日退宿，当天开始计发外宿补贴`;
      r.equation = `150 ÷ ${days} × ${r.payable}`;
      r.metrics = [['住宿扣除',`${r.housed}天`],['外宿天数',`${r.payable}天`],['退宿当天','计入外宿天数']]; r.visual='housing';
    }
  } else if (id === 'yeban_butie') {
    r.unit='元/日';
    if (region === 3) {
      r.payable = Math.max(8-v.late-v.early,0); r.total=8;
      r.amount=roundMoney(r.payable/8*25); r.reason='按LB15有效正班时数折算';
      r.equation=`max（8 − ${number(v.late)} − ${number(v.early)}，0）÷ 8 × 25`;
      r.metrics=[['迟到折算',`${number(v.late)}小时`],['早退折算',`${number(v.early)}小时`],['有效正班',`${number(r.payable)}小时`]]; r.visual='regular';
    } else {
      const payable = hours => hours>=1 ? Math.floor(hours*2)/2 : 0;
      r.evening=payable(v.evening); r.morning=payable(v.morning); r.amount=roundMoney(Math.min((r.evening+r.morning)*3,25));
      r.reason=(r.evening+r.morning)*3>25 ? '早晚窗口共用每日25元上限' : '每个窗口独立判断1小时门槛，再按完整半小时计发';
      r.equation=`min〔（${number(r.evening)} + ${number(r.morning)}）× 3，25〕`;
      r.metrics=[['晚间计发时数',`${number(r.evening)}小时`],['早间计发时数',`${number(r.morning)}小时`],['每日上限','25元']]; r.visual='night';
    }
  } else if (id === 'quanqinjiang') {
    const reasons=[];
    if(v.minor>3)reasons.push('6分钟内迟到超过3次');
    if(v.middle>1)reasons.push('6–20分钟迟到超过1次');
    if(v.minor>0&&v.middle>0)reasons.push('两档迟到混合出现');
    if(v.major>0)reasons.push('存在20–30分钟迟到');
    if(v.signs>3)reasons.push('签卡超过3次');
    if(v.eligible!=='yes')reasons.push('存在其他不符合全勤条件的事项');
    r.amount=reasons.length ? 0 : 100; r.reason=reasons.join('；')||'满足迟到豁免、签卡及其他全勤条件';
    r.equation=reasons.length ? '存在不符合项' : '全部全勤条件满足';
    r.checks=[['迟到豁免',v.minor<=3&&v.middle<=1&&!(v.minor>0&&v.middle>0)&&v.major===0],['签卡次数',v.signs<=3],['其他全勤条件',v.eligible==='yes']]; r.visual='attendance';
  } else if (id === 'gonglingjiang') {
    r.base=Math.min(v.years*m.rate,m.cap);
    const absence=m.fbu||v.absence>=56 ? v.absence : 0;
    r.amount=roundMoney(r.base/v.scheduled*(v.scheduled-(absence+v.entryHours)/8));
    r.reason=m.fbu ? 'FBU不设56小时门槛，入离职与事病旷合并折算一次' : `${v.absence>=56 ? '请假达到56小时，按全部时数扣减' : '请假未达到56小时，不扣减'}；入离职缺勤另行折算`;
    r.equation=`${r.base} ÷ ${v.scheduled} ×〔${v.scheduled} −（${number(absence)} + ${number(v.entryHours)}）÷ 8〕`;
    r.metrics=[['基础月标准',`${r.base}元`],['请假扣减',`${money(r.base/v.scheduled*absence/8)}元`],['入离职扣减',`${money(r.base/v.scheduled*v.entryHours/8)}元`]]; r.visual='seniority';
  } else if (id === 'gaowen_butie') {
    const inSeason=Number(v.month)>=6&&Number(v.month)<=10, hot=v.temperature>=33;
    r.dayAmount=inSeason&&hot ? Math.min(v.hours*m.rate,m.daily) : 0; r.raw=r.dayAmount*v.days; r.cap=m.cap;
    r.amount=roundMoney(Math.min(r.raw,m.cap));
    r.reason=!inSeason ? '当前月份不在6–10月计发期间' : !hot ? '当班最高温度未达到33℃' : r.raw>m.cap ? '温度及月份符合条件，月度合计按上限计发' : '温度及月份符合条件，按逐日标准计发';
    r.equation=inSeason&&hot ? `min〔min（${number(v.hours)} × ${m.rate}，${m.daily}）× ${v.days}，${m.cap}〕` : '未满足月份或当班温度条件';
    r.metrics=[['匹配班次',v.shift==='day'?'白班':'夜班'],['单日未舍入金额',`${number(r.dayAmount)}元`],['月度未封顶金额',`${number(r.raw)}元`]]; r.visual='temperature';
  }
  if (id==='gonglingjiang' && v.absence+v.entryHours>v.scheduled*8) {
    r.invalid=true;
    r.reason='请假与入离职缺勤合计超过排班对应时数，请核对本例参数。';
    r.metrics=[];
  }
  return r;
}

function bar(parts) {
  const total=parts.reduce((sum,part)=>sum+Math.max(part.value,0),0)||1;
  return `<div class="rb-bar" aria-hidden="true">${parts.filter(part=>part.value>0).map(part=>`<span class="${esc(part.kind||'')}" style="width:${clamp(part.value/total*100,0,100)}%"></span>`).join('')}</div><div class="rb-bar-labels">${parts.map(part=>`<span><i class="${esc(part.kind||'')}"></i>${esc(part.label)}</span>`).join('')}</div>`;
}
function nightTimeline() {
  return `<figure class="rb-night-example">
    <figcaption><strong>普通夜班 · 时段拆分示例</strong><span>出勤 18:00–次日07:00 · 休息 23:00–24:00</span></figcaption>
    <div class="rb-night-track" role="img" aria-label="18点至22点在夜班窗口外；22点至23点计发1小时；23点至24点休息扣除；次日0点至7点计发7小时；7点至8点无出勤。有效夜班合计8小时。">
      <span class="muted">窗口外</span><span class="paid">1h</span><span class="deducted">休息</span><span class="paid">7h</span><span class="muted">无出勤</span>
    </div>
    <div class="rb-night-ticks" aria-hidden="true"><span style="left:0%">18:00</span><span style="left:28.5714%">22:00</span><span style="left:35.7143%">23:00</span><span style="left:42.8571%">00:00</span><span style="left:92.8571%">07:00</span><span style="left:100%">08:00</span></div>
    <div class="rb-bar-labels"><span><i class="paid"></i>有效夜班</span><span><i class="deducted"></i>扣除休息</span><span><i class="muted"></i>不计时段</span></div>
    <div class="rb-night-example-result"><p>9小时窗口出勤 − 1小时休息 = 8小时；8 × 3元 = <strong>24.00元</strong></p><button type="button" data-rb-night-example>代入此例</button></div>
  </figure>`;
}
function illustration(r) {
  const v=r.values;
  if(r.visual==='absence')return `<div class="rb-branches"><div class="rb-branch ${v.absence<=56?'is-active':''}"><span>缺勤合计 ≤ 56小时</span><strong>不扣减</strong><small>包含刚好56小时</small></div><div class="rb-branch warning ${v.absence>56?'is-active':''}"><span>缺勤合计 > 56小时</span><strong>全部时数 ÷ 8</strong><small>超过门槛后扣减全部缺勤</small></div></div>`;
  if(r.visual==='housing')return bar([{value:r.housed,label:`住宿 ${r.housed}天`,kind:'muted'},{value:r.payable,label:`外宿 ${r.payable}天`,kind:'paid'}])+`<div class="rb-date-line"><span>1日入住</span><strong>${v.housing==='staying'?'整月未退宿':`${v.checkout}日退宿`}</strong><span>${r.total}日月末</span></div>`;
  if(r.visual==='night')return `<div class="rb-window"><span>晚间窗口</span>${bar([{value:r.evening,label:`计发 ${number(r.evening)}小时`,kind:'paid'},{value:Math.max(v.evening-r.evening,0),label:`不足门槛或舍去 ${number(v.evening-r.evening)}小时`,kind:'deducted'},{value:10-v.evening,label:'窗口上限10小时',kind:'muted'}])}</div><div class="rb-window"><span>早间窗口</span>${bar([{value:r.morning,label:`计发 ${number(r.morning)}小时`,kind:'paid'},{value:Math.max(v.morning-r.morning,0),label:`不足门槛或舍去 ${number(v.morning-r.morning)}小时`,kind:'deducted'},{value:8-v.morning,label:'窗口上限8小时',kind:'muted'}])}</div>`;
  if(r.visual==='attendance')return `<div class="rb-checks">${r.checks.map(([label,ok])=>`<div class="rb-check ${ok?'passed':'failed'}"><span aria-hidden="true">${ok?'✓':'×'}</span><div><strong>${esc(label)}</strong><small>${ok?'符合':'不符合'}</small></div></div>`).join('')}</div>`;
  if(r.visual==='seniority')return `<div class="rb-steps">${Array.from({length:r.model.cap/r.model.rate+1},(_,i)=>`<div class="rb-step ${Math.min(v.years,r.model.cap/r.model.rate)===i?'selected':''}" style="--step:${i}"><strong>${i*r.model.rate}</strong><span>元 / 月</span><small>${i===0?'未满1年':i===r.model.cap/r.model.rate?`满${i}年及以上`:`满${i}年`}</small></div>`).join('')}</div><p class="rb-note">阶梯表示扣减前月标准；超过上限后不再增加。</p>`;
  if(r.visual==='temperature')return `<div class="rb-temperature"><div><span>${v.shift==='day'?'白班':'夜班'}最高温度</span><strong>${number(v.temperature)}℃</strong></div><div class="rb-temp-scale"><div class="rb-temp-track"><i style="left:${(v.temperature-28)/12*100}%"></i><b></b></div><div class="rb-temp-labels"><span>28℃</span><strong>33℃门槛</strong><span>40℃</span></div></div><span class="rb-temp-status ${v.temperature>=33?'passed':'failed'}">${v.temperature>=33?'达到温度门槛':'未达到温度门槛'}</span></div>`;
  if(r.visual==='cap')return `<div class="rb-flow"><div><span>单日金额</span><strong>${number(r.dayAmount)}元</strong></div><b aria-hidden="true">×</b><div><span>符合条件出勤</span><strong>${v.days}天</strong></div><b aria-hidden="true">→</b><div><span>月度封顶前</span><strong>${number(r.raw)}元</strong></div></div>`+bar([{value:Math.min(r.raw,r.cap),label:`上限内 ${money(Math.min(r.raw,r.cap))}元`,kind:'paid'},{value:Math.max(r.cap-r.raw,0),label:`月度上限 ${r.cap}元`,kind:'muted'}]);
  if(r.visual==='days'||r.visual==='regular'){
    const unit=r.visual==='regular'?'小时':'天';
    return bar([{value:r.payable,label:`计发 ${number(r.payable)}${unit}`,kind:'paid'},{value:Math.max(r.total-r.payable,0),label:`扣减 ${number(Math.max(r.total-r.payable,0))}${unit}`,kind:'deducted'}]);
  }
  if(r.visual==='deductions')return `<div class="rb-flow"><div><span>月标准</span><strong>150元</strong></div><b aria-hidden="true">−</b><div><span>入离职扣减</span><strong>${money(r.entry)}元</strong></div><b aria-hidden="true">−</b><div><span>请假扣减</span><strong>${money(r.leave)}元</strong></div></div>`;
  return '';
}

function controls(m, values) {
  return m.fields.map(field=>{
    const id=`rb-input-${field.key}`;
    if(field.type==='select')return `<label class="rb-select"><span>${esc(field.label)}</span><select id="${id}" data-rb-field="${field.key}">${field.options.map(([value,label])=>`<option value="${esc(value)}" ${values[field.key]===value?'selected':''}>${esc(label)}</option>`).join('')}</select></label>`;
    return `<div class="rb-control"><div class="rb-control-head"><label for="${id}">${esc(field.label)}</label><div class="rb-exact"><input type="number" aria-label="${esc(field.label)}精确值" data-rb-field="${field.key}" min="${field.min}" max="${field.max}" step="${field.step}" value="${values[field.key]}"><span>${esc(field.unit)}</span></div></div><input type="range" id="${id}" aria-label="${esc(field.label)}" data-rb-field="${field.key}" min="${field.min}" max="${field.max}" step="${field.step}" value="${values[field.key]}"><div class="rb-extents"><span>${field.min}${esc(field.unit)}</span><span data-rb-max="${field.key}">${field.max}${esc(field.unit)}</span></div></div>`;
  }).join('');
}
function resultHTML(r) {
  return `<span class="rb-result-label">示例应发（${esc(r.unit)}）</span><output class="rb-amount" aria-live="polite">${r.invalid?'—':money(r.amount)}</output><p class="rb-result-reason">${esc(r.reason)}</p>${r.metrics.length?`<dl class="rb-metrics">${r.metrics.map(([label,value])=>`<div><dt>${esc(label)}</dt><dd>${esc(value)}</dd></div>`).join('')}</dl>`:''}`;
}
function equationHTML(r) { return r.invalid ? '参数不符合排班时数范围，调整后重新计算。' : `${esc(r.equation)} = <strong>${money(r.amount)}元</strong>`; }
function calculatorHTML(r) {
  const m=r.model;
  return `<div class="rb-demo"><div class="rb-demo-head"><h3>${esc(m.title)}</h3>${m.fixed?'':'<button type="button" class="rb-reset" data-rb-reset>重置示例</button>'}</div><p class="rb-assumption">${esc(m.assumption)}</p>${m.fixed?`<div class="rb-fixed">${resultHTML(r)}</div>`:`<div class="rb-interactive"><div><div class="rb-controls">${controls(m,r.values)}</div><div class="rb-presets" aria-label="常用算例">${m.presets.map((preset,i)=>`<button type="button" data-rb-preset="${i}">${esc(preset.label)}</button>`).join('')}</div></div><div class="rb-result" data-rb-result>${resultHTML(r)}</div></div><div class="rb-illustration" data-rb-illustration>${illustration(r)}</div><div class="rb-equation"><span>本例计算</span><p data-rb-equation>${equationHTML(r)}</p></div>`}</div>`;
}
function richRuleParagraphs(text) {
  return (String(text).match(/[^；。]+[；。]?|[；。]/g)||[]).map(part=>`<p>${esc(part).replace(/\d{1,2}:\d{2}(?:至(?:次日)?\d{1,2}:\d{2})?|\bLB\d+\b|\d+(?:\.\d+)?(?:元(?:\/小时)?|小时|分钟|天|℃|%)/g,token=>`<strong>${token}</strong>`)}</p>`).join('');
}
function ruleList(items) { return `<ul class="rb-detail-list">${items.map(item=>`<li>${richRuleParagraphs(item)}</li>`).join('')}</ul>`; }
function commonRules(subject) {
  const nightTopics = [
    ['只计算22:', '计发时段', 0],
    ['上班向后', '打卡取整', 0],
    ['普通夜班计薪起点', '计薪起点', 0],
    ['可扣休息', '休息扣除', 0],
    ['普通夜班按有效', '小时标准与每日上限', 1],
    ['凌晨3点班', 'LB15正班折算', 2],
    ['非工作日', '非工作日处理', 2],
    ['普通夜班扣除休息', '起计门槛与半小时折算', 1],
    ['东莞保洁', '东莞排除范围', 2],
    ['排班与实际出勤', '早班覆盖夜班窗口', 2],
    ['同日早晨和晚间', '双窗口合计与封顶', 1],
    ['缺少有效上班', '缺卡处理', 3],
    ['打卡跨度超过', '长跨度打卡', 3],
    ['日期无效', '无效数据复核', 3],
    ['其他待确认', '暂算金额处理', 3],
    ['正式核算前', '班次休息配置检查', 3],
    ['晋江计件岗', '晋江排除名单', 2],
  ];
  const groups = subject.id==='yeban_butie'
    ? ['计发时段与出勤取整','计发标准与金额汇总','特殊班次与人员资格','数据检查与异常处理','其他通用规则'].map(title=>({title,items:[]}))
    : [{title:'',items:[]}];
  subject.common_rules.forEach((text,index)=>{
    const topic=subject.id==='yeban_butie'?nightTopics.find(([prefix])=>text.startsWith(prefix)):null;
    groups[topic?topic[2]:groups.length-1].items.push({text,index,title:topic?.[1]||''});
  });
  let ruleNumber=0;
  return `<div class="rb-rich-common">${groups.filter(group=>group.items.length).map(group=>`<section class="rb-rule-group">${group.title?`<h4>${esc(group.title)}</h4>`:''}<ol class="rb-rich-rules">${group.items.map(item=>`<li data-rb-rule-index="${item.index}"><span class="rb-rule-number" aria-hidden="true">${String(++ruleNumber).padStart(2,'0')}</span><div>${item.title?`<h5>${esc(item.title)}</h5>`:''}<div data-rb-rule-text>${richRuleParagraphs(item.text)}</div></div></li>`).join('')}</ol></section>`).join('')}</div>`;
}
function standardTable(rows) {
  return rows?.length ? `<table class="rb-standards"><thead><tr><th scope="col">适用对象 / 标准</th><th scope="col">计发金额</th></tr></thead><tbody>${rows.map(([label,value])=>`<tr><td>${esc(label)}</td><td>${esc(value)}</td></tr>`).join('')}</tbody></table>` : '';
}
function supports(packageData) { return packageData?.version==='1.4.9'; }
function dispose(root) { root.__rulebookAbort?.abort(); root.__rulebookAbort=null; root.classList.remove('dl-rb'); }

function mount(root, packageData, subject, regionOverride) {
  dispose(root); root.classList.add('dl-rb');
  const abort=new AbortController(); root.__rulebookAbort=abort;
  const region=regionOverride ?? activeRegions.get(subject.id) ?? 0;
  activeRegions.set(subject.id,region);
  const key=`${packageData.version}:${subject.id}:${region}`;
  const c=copy[subject.id], area=subject.regions[region];
  let r=calculate(subject.id,region,sessions.get(key)||{});
  sessions.set(key,r.values);
  const areaRule=subject.id==='gangwei_butie'&&region===1 ? '按安检岗位名称识别资格。已知等级标准当前用于核算，仍待线下结果验证；未明确标准的岗位不自行套档。' : area.rule;
  root.innerHTML=`
    <header class="rb-page-head">
      <p class="rb-eyebrow">规则包 / ${subject.category_id==='bonus'?'奖金类':'补贴类'}</p>
      <div class="rb-title-row"><h2>${esc(subject.name)}</h2></div>
      <p class="rb-intro">${esc(c.intro)}</p>
      <nav class="rb-sections" aria-label="本科目内容"><button type="button" data-rb-go="eligibility">适用范围</button><button type="button" data-rb-go="calculation">计算规则</button><button type="button" data-rb-go="boundaries">扣减与特殊口径</button></nav>
    </header>
    <section class="rb-section" id="rb-eligibility">
      <div class="rb-section-head"><span>01</span><h3>适用条件</h3><small>按地区或适用范围查看</small></div>
      <div class="rb-regions" aria-label="选择适用范围">${subject.regions.map((item,i)=>`<button type="button" data-rb-region="${i}" aria-pressed="${i===region}">${esc(item.name)}</button>`).join('')}</div>
      <div class="rb-eligibility"><h4>${esc(area.name)}</h4><p>${esc(areaRule)}</p>${standardTable(c.standards?.[region])}${area.details?.length?`<details class="rb-details" open><summary>地区计发细则</summary>${ruleList(area.details)}</details>`:''}</div>
    </section>
    <section class="rb-section" id="rb-calculation">
      <div class="rb-section-head"><span>02</span><h3>计发标准与计算规则</h3><small>调整参数查看计发结果</small></div>
      <div class="rb-rule-board">
        <div class="rb-board-top"><p>关键标准</p><div class="rb-stats" data-rb-stats>${r.model.stats.map(([value,unit,note])=>`<div><strong>${esc(value)}</strong><span>${esc(unit)}</span><small>${esc(note)}</small></div>`).join('')}</div></div>
        <div class="rb-formula"><span>计发公式</span><p data-rb-formula>${esc(r.model.formula)}</p><small data-rb-caption>${esc(r.model.caption)}</small></div>
        ${r.visual==='night'?nightTimeline():''}
        <div data-rb-calculator>${calculatorHTML(r)}</div>
      </div>
    </section>
    <section class="rb-section" id="rb-boundaries">
      <div class="rb-section-head"><span>03</span><h3>扣减与特殊口径</h3></div>
      <ol class="rb-rules">${c.rules.map(([title,text],i)=>`<li><span>${String(i+1).padStart(2,'0')}</span><div><h4>${esc(title)}</h4><p>${esc(text)}</p></div></li>`).join('')}</ol>
      ${subject.common_rules?.length?`<details class="rb-details rb-common" open><summary>完整通用规则</summary>${commonRules(subject)}</details>`:''}
    </section>`;

  function update(next, rebuild=false, source=null) {
    const previousFields=r.model.fields.map(field=>field.key).join(',');
    r=calculate(subject.id,region,next); sessions.set(key,r.values);
    rebuild ||= previousFields!==r.model.fields.map(field=>field.key).join(',');
    if(rebuild) {
      root.querySelector('[data-rb-calculator]').innerHTML=calculatorHTML(r);
      root.querySelector('[data-rb-formula]').textContent=r.model.formula;
      root.querySelector('[data-rb-caption]').textContent=r.model.caption;
      root.querySelector('[data-rb-stats]').innerHTML=r.model.stats.map(([value,unit,note])=>`<div><strong>${esc(value)}</strong><span>${esc(unit)}</span><small>${esc(note)}</small></div>`).join('');
      return;
    }
    for(const field of r.model.fields){
      root.querySelectorAll(`[data-rb-field="${field.key}"]`).forEach(input=>{
        if(input!==source)input.value=r.values[field.key];
        input.removeAttribute('aria-invalid');
        if(field.type==='range'){input.min=field.min;input.max=field.max;}
      });
      const max=root.querySelector(`[data-rb-max="${field.key}"]`); if(max)max.textContent=`${field.max}${field.unit}`;
    }
    root.querySelector('[data-rb-result]').innerHTML=resultHTML(r);
    root.querySelector('[data-rb-illustration]').innerHTML=illustration(r);
    root.querySelector('[data-rb-equation]').innerHTML=equationHTML(r);
  }
  root.addEventListener('input',event=>{
    const input=event.target.closest('[data-rb-field]'); if(!input)return;
    if(input.type==='number'&&(input.value===''||!Number.isFinite(Number(input.value))||!input.validity.valid)){
      input.setAttribute('aria-invalid','true');
      root.querySelector('.rb-amount').textContent='—';
      root.querySelector('.rb-result-reason').textContent='请填写范围内的有效参数，计算结果将同步更新。';
      return;
    }
    update({...r.values,[input.dataset.rbField]:input.value},input.dataset.rbField==='scenario'||input.dataset.rbField==='monthDays',input.type==='number'?input:null);
  },{signal:abort.signal});
  root.addEventListener('change',event=>{
    const input=event.target.closest('input[type="number"][data-rb-field]');
    if(input)update(input.value===''?r.values:{...r.values,[input.dataset.rbField]:input.value});
  },{signal:abort.signal});
  root.addEventListener('click',event=>{
    const button=event.target.closest('button'); if(!button)return;
    if(button.hasAttribute('data-rb-night-example'))update({evening:8,morning:0});
    if(button.dataset.rbRegion!==undefined){
      const scroll=window.scrollY; mount(root,packageData,subject,Number(button.dataset.rbRegion));window.scrollTo(0,scroll);
      root.querySelector(`[data-rb-region="${button.dataset.rbRegion}"]`)?.focus({preventScroll:true});
    }
    if(button.dataset.rbGo)root.querySelector(`#rb-${button.dataset.rbGo}`)?.scrollIntoView({block:'start'});
    if(button.hasAttribute('data-rb-reset'))update({},true);
    if(button.dataset.rbPreset!==undefined)update({...r.values,...r.model.presets[Number(button.dataset.rbPreset)].values});
  },{signal:abort.signal});
}

function navigation(packageData, selected) {
  return (packageData.categories||[]).map(category=>`<div class="rb-nav-group"><p>${esc(category.name)}</p>${ORDER.filter(id=>category.subject_ids.includes(id)).map(id=>{
    const subject=packageData.subjects.find(item=>item.id===id);
    return `<button type="button" class="rb-subject" data-rule-subject="${id}" aria-current="${selected===id}"><span>${String(ORDER.indexOf(id)+1).padStart(2,'0')}</span><strong>${esc(subject.name)}</strong><b aria-hidden="true">↗</b></button>`;
  }).join('')}</div>`).join('');
}
function search(root, packageData, query) {
  dispose(root);root.classList.add('dl-rb');
  const q=query.trim().toLowerCase();
  const matches=packageData.subjects.flatMap(subject=>{
    const entries=[subject.summary,...subject.common_rules||[],...subject.regions.flatMap(area=>[area.name,area.rule,area.formula,...area.details||[]])];
    if(supports(packageData))entries.push(copy[subject.id].intro,...copy[subject.id].rules.flat());
    const hit=entries.find(text=>String(text).toLowerCase().includes(q));
    return subject.name.toLowerCase().includes(q)||hit ? [{subject,hit:hit||subject.summary}] : [];
  });
  root.innerHTML=`<header class="rb-search-head"><p class="rb-eyebrow">规则检索</p><h2>“${esc(query)}”</h2><p>${matches.length}个相关科目</p></header>${matches.map(({subject,hit})=>`<button type="button" class="rb-search-result" data-rule-subject="${esc(subject.id)}"><strong>${esc(subject.name)} ↗</strong><p>${esc(hit)}</p></button>`).join('')||'<p class="rb-empty">未找到匹配的规则。可使用科目、岗位或规则关键词检索。</p>'}`;
}

const api={supports,mount,dispose,navigation,search,calculate};
global.DomesticLaborRulebook=api;
if(typeof module!=='undefined'&&module.exports)module.exports=api;
})(typeof window !== 'undefined' ? window : globalThis);
