'use strict';
(() => {
  const escape = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const notes = {
    canbu:{missing:'缺少适用地区要求的出勤资料或补充字段。',follow:'按地区核对月考勤与日考勤的覆盖范围，缺字段先补齐，不用空白代替零。'},
    waisu_butie:{missing:'住宿名单缺少跨月仍在住记录，或本月自离名单尚未确认。',follow:'保留完整入住、退宿区间；仍在住时退宿日期留空，多次入住分行填写。无住宿或无自离人员须明确确认。'},
    yeban_butie:{missing:'当月生效的班次休息配置尚未确认。',follow:'提供实际打卡及生效班次休息时段；晋江额外排除名单也需确认，不自动沿用历史配置。'},
    gangwei_butie:{missing:'缺少“实际在职工作日天数”。',follow:'请补充该字段，并确认地区、岗位、排班天数和缺勤字段齐全。'},
    gaowen_butie:{missing:'缺少对应日期、网点、班次的测温登记，或不享有名单尚未确认。',follow:'上传含测温登记、不享有名单、填写说明的工作簿。网点名称不一致时确认对照；空名单也要明确确认。'},
    quanqinjiang:{missing:'三档迟到次数或整月逐日排班状态不完整。',follow:'提供三档迟到次数及覆盖整月的日考勤，包括非工作日和月初入职前的排班状态。'},
    gonglingjiang:{missing:'入职日期、部门或实际在职工作日字段不完整。',follow:'确认地区、部门、岗位和入离职信息；涉及第四纵队揽收线时，补充或确认本月工龄奖名单。'},
  };
  const name = item => item.contract.name;
  const period = month => `${Number(month.slice(0,4))} 年 ${Number(month.slice(5))} 月`;
  function prompt(kind, item, month) {
    const common = `请读取附件中的${name(item)} Skill，按包内最新规则处理 ${period(month)}${name(item)}。`;
    if (kind === 'calculate') return `${common}\n我会一起提供原始核算资料：${item.inputs.join('；')}。\n请先检查字段、人员与整月覆盖范围、补充名单和适用期间，保留字段映射及来源依据。缺资料或有待确认口径先告诉我，不要推定为空、为零或补造数据。\n资料齐全并确认后，再运行核算脚本，输出逐人明细、计算依据、规则版本和待复核事项。`;
    if (kind === 'reconcile') return `${common}\n附件包含原始核算资料和同月份、同科目的线下结果。请检查数据覆盖本次全部人员与整月。\n从原始资料重新核算，按文本工号、月份、科目匹配，姓名交叉核对；检查重复行、漏行和仅在线下出现的人员。线下金额空白不能视为零。\n请逐人列出核算金额、线下金额、差额（核算金额减线下金额）及来源依据；无法核验的行单独列明，不只比较总额。`;
    if (kind === 'followup') return `已补齐 ${period(month)}${name(item)}资料并确认覆盖本次全部人员与适用期间，请重新检查。检查通过后继续核算，输出逐人明细和计算依据，保留所有待复核事项。`;
    return `请导出 ${period(month)}${name(item)}的逐人核算明细、核验差异、字段映射、来源依据和待复核事项。优先生成 Excel；如果当前工具不支持文件导出，请提供可保存的 CSV 明细。`;
  }
  const actorIcon = role => role === 'user'
    ? '<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="8" r="3"/><path d="M5 21v-3a7 7 0 0 1 14 0v3"/></svg>'
    : '<svg viewBox="0 0 24 24" aria-hidden="true"><rect x="4" y="7" width="16" height="13" rx="4"/><path d="M12 3v4M1 12v4M23 12v4M9 16h6"/><circle cx="8" cy="12" r="1"/><circle cx="16" cy="12" r="1"/></svg>';
  const message = (role, html) => `<div class="guide-message ${role}"><div class="guide-actor"><span>${actorIcon(role)}</span><strong>${role === 'user' ? '你' : 'AI'}</strong></div><div class="guide-bubble">${html}</div></div>`;
  const file = (label, type='xlsx') => `<span class="guide-file"><span class="guide-file-icon ${type}" aria-hidden="true">${type === 'zip' ? 'ZIP' : 'X'}</span>${escape(label)}</span>`;
  const status = (label, missing=false) => `<strong class="guide-status ${missing ? 'missing' : ''}"><span aria-hidden="true">${missing ? '!' : '✓'}</span>${label}</strong>`;
  const copy = (kind, label) => `<div class="guide-copy-row"><button type="button" class="text-button" data-guide-copy="${kind}">${SkillHubUI.icon('copy')}${label}</button><span id="${kind}PromptStatus" class="copy-status" role="status"></span></div>`;
  function render(item, month, skills) {
    const subject = name(item), m = Number(month.slice(5));
    const tip = notes[item.id];
    const sampleAmount = item.id === 'gangwei_butie' ? 800 : 100;
    const amount = sampleAmount.toFixed(2), offline = (sampleAmount - 20).toFixed(2);
    const files = `<div class="guide-files">${file(`${item.name} skill.zip`,'zip')}${file(`${m}月核算原始资料.xlsx`)}</div>`;
    return `<div class="guide-toolbar"><div class="guide-toolbar-fields"><label>科目 <select id="guideSubject" data-ui-select>${skills.map(skill => `<option value="${escape(skill.id)}" data-icon="${escape(skill.icon)}" ${skill.id === item.id ? 'selected' : ''}>${escape(name(skill))}</option>`).join('')}</select></label><label>核算月份 <input id="guideMonth" data-ui-month type="month" value="${escape(month)}"></label></div><a class="button secondary" href="${escape(item.download_url)}" aria-label="下载当前指引的${escape(subject)} Skill">${SkillHubUI.icon('download')}下载${escape(subject)} Skill</a></div>
      <div class="guide-intro"><span class="guide-document" aria-hidden="true"><svg viewBox="0 0 24 24"><path d="M14 3H5v18h14V8ZM14 3v5h5M8 12h8M8 16h8"/></svg></span><p><strong>使用前：</strong>选择能读取压缩包并运行 Python 脚本的 AI 工具，将科目 Skill 与数据文件一起上传。若工具不能直接读 ZIP，先解压并提供完整文件夹。</p></div>
      <h3 class="guide-title">用 Skill 完成${escape(subject)}核算与核验</h3><p class="guide-example-note">以下是虚构对话与演示金额；点击复制后，按本次实际资料补充附件。</p>
      <div class="guide-columns">
        <section class="guide-flow" aria-labelledby="calculateGuideTitle"><header><span class="guide-step">01</span><div><h4 id="calculateGuideTitle">核算${escape(subject)}</h4><p>上传原始数据 → 检查缺项 → 完成核算</p></div></header><div class="guide-chat">
          ${message('user', `${files}<p>请读取附件中的${escape(subject)} Skill，核算 ${escape(period(month))}${escape(subject)}。<br>请先检查数据，缺资料先告诉我。</p>${copy('calculate','复制核算提问')}`)}
          ${message('ai', `${status('需补充资料',true)}<p>${escape(tip.missing)}<br>${escape(tip.follow)}<br>请确认资料覆盖本次核算全部人员与整月。</p>`)}
          ${message('user', `<div class="guide-files">${file(`${m}月补齐核算资料.xlsx`)}</div><p>已补齐并确认覆盖范围，请重新检查后继续核算，输出逐人明细和计算依据。</p>${copy('followup','复制补齐后提问')}`)}
          ${message('ai', `${status('核算完成（演示）')}<div class="guide-table-wrap"><table><thead><tr><th>工号</th><th>科目</th><th>演示金额</th></tr></thead><tbody><tr><td>TEST001</td><td>${escape(subject)}</td><td>${amount} 元</td></tr></tbody></table></div><p>实际金额按适用规则与完整资料计算，保留规则版本、逐人依据和待复核事项。</p><div class="guide-files">${file(`${subject}核算明细.xlsx`)}</div>`)}
        </div></section>
        <section class="guide-flow" aria-labelledby="reconcileGuideTitle"><header><span class="guide-step">02</span><div><h4 id="reconcileGuideTitle">核对线下结果</h4><p>上传原始数据和结果 → 逐人比对 → 查看差异</p></div></header><div class="guide-chat">
          ${message('user', `${files}<div class="guide-files">${file(`${m}月线下${subject}.xlsx`)}</div><p>请读取附件中的${escape(subject)} Skill，核验 ${escape(period(month))}线下结果。<br>资料覆盖本次全部人员与整月，请逐人比对并列出差异。</p>${copy('reconcile','复制核验提问')}`)}
          ${message('ai', '<p>数据检查通过。按工号、月份、科目匹配，姓名交叉核对，并检查重复行、漏行和仅在线下出现的人员。</p>')}
          ${message('ai', `${status('发现 1 笔金额差异（演示）')}<div class="guide-table-wrap"><table><thead><tr><th>工号</th><th>核算金额</th><th>线下金额</th><th>差额</th></tr></thead><tbody><tr><td>TEST001</td><td>${amount}</td><td>${offline}</td><td class="guide-difference">+20.00</td></tr></tbody></table></div><p>差额 = 核算金额 − 线下金额。演示中线下少计 20.00 元，需核对录入或调整依据；存在差异或无法核验时，不能称为“核验通过”。</p>`)}
          ${message('user', `<p>请导出差异明细及计算依据。</p>${copy('export','复制导出提问')}`)}
          ${message('ai', `<div class="guide-files">${file(`${subject}核验差异.xlsx`)}</div><p>已整理逐人明细、差异记录和来源依据。文件导出需当前 AI 工具支持。</p>`)}
        </div></section>
      </div>
      <div class="guide-reminders"><span>缺资料先补齐</span><span>原始数据与线下结果一起提供</span><span>逐人核验，不只比较总额</span></div>
      <details class="guide-reference"><summary>准备资料与运行方式</summary><div class="guide-reference-grid"><section><h4>当前${escape(subject)}需要</h4><ul>${item.inputs.map(input=>`<li>${escape(input)}</li>`).join('')}</ul><p>${escape(tip.follow)}</p><p>科目规则：${escape(item.rule_version)}。完整字段与适用地区要求见包内输入契约和规则说明。</p></section><section><h4>让 AI 按包内说明执行</h4><p>Python 3.10 或以上。AI 先读取 SKILL.md 和输入契约，将原始数据整理为 input.json，再运行：</p><pre class="command">python3 -m pip install -r scripts/requirements.txt
python3 scripts/run.py input.json --mode validate --output validation.json
python3 scripts/run.py input.json --mode calculate --output results.json
python3 scripts/run.py input.json --mode reconcile --output reconciliation.json</pre><p>validate 只检查资料；reconcile 还需要线下结果。未核算或存在暂算、缺失、待复核事项时，先处理后继续。</p></section></div></details>`;
  }
  window.DomesticSkillGuide = {render, prompt};
})();
