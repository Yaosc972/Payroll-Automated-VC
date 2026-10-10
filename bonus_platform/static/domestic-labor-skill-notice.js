'use strict';
(() => {
  const link = document.getElementById('navSkillHub');
  const badge = document.getElementById('skillHubNotice');
  if (!link || !badge) return;
  const label = document.getElementById('skillHubNoticeLabel');
  const count = document.getElementById('skillHubNoticeCount');
  const prefix = 'hras:domestic-skillhub:seen:v1:';
  const priority = ['gaowen_butie', 'waisu_butie', 'yeban_butie'];
  const memory = new Map();
  let owner = '', skills = [], revision = 0, lastChecked = 0;

  const key = () => prefix + encodeURIComponent(owner);
  function seenVersions() {
    try {
      const value = JSON.parse(localStorage.getItem(key()) || '{}');
      return {...(value && typeof value === 'object' && !Array.isArray(value) ? value : {}), ...(memory.get(owner) || {})};
    } catch (_) { return memory.get(owner) || {}; }
  }
  const shortName = (skill) => String(skill.name || skill.id).replace(/^(操作线|全区域)/, '');
  function render() {
    const seen = seenVersions();
    const unread = skills.filter(skill => seen[skill.id] !== skill.fingerprint).sort((a, b) => {
      const date = String(b.released_at).localeCompare(String(a.released_at));
      const rank = (skill) => priority.includes(skill.id) ? priority.indexOf(skill.id) : priority.length;
      return date || rank(a) - rank(b);
    });
    badge.hidden = !unread.length;
    if (!unread.length) {
      link.removeAttribute('title');
      link.setAttribute('aria-label', 'SkillHub');
      return;
    }
    label.textContent = `${shortName(unread[0])} Skill 上新`;
    count.hidden = unread.length < 2;
    count.textContent = `+${unread.length - 1}`;
    const summary = unread.map(shortName).join('、');
    link.title = `${summary} Skill 上新，点击查看后提醒消失`;
    link.setAttribute('aria-label', `SkillHub，${summary} Skill 上新，共 ${unread.length} 份未读更新`);
  }
  function markRead(event) {
    if (event.defaultPrevented || (event.type === 'auxclick' && event.button !== 1) || !owner || !skills.length) return;
    const seen = seenVersions();
    // Acknowledge only the versions actually fetched; a later release stays unread.
    for (const skill of skills) seen[skill.id] = skill.fingerprint;
    memory.set(owner, seen);
    try { localStorage.setItem(key(), JSON.stringify(seen)); } catch (_) { /* Retain the read state for this page. */ }
    render();
  }
  async function refresh(ownerId = owner) {
    const nextOwner = String(ownerId || '');
    if (nextOwner !== owner) {
      owner = nextOwner;
      skills = [];
      render();
    }
    const requestRevision = ++revision;
    if (!owner) return;
    lastChecked = Date.now();
    try {
      const response = await fetch('/api/domestic-labor/skillhub', {cache:'no-store'});
      if (!response.ok) throw new Error('Skill catalog unavailable');
      const catalog = await response.json();
      if (requestRevision !== revision) return;
      skills = (catalog.skills || []).filter(skill => skill.id && skill.fingerprint);
      render();
    } catch (_) {
      // A failed refresh must never manufacture a release or interrupt payroll.
      if (requestRevision === revision) { skills = []; render(); }
    }
  }
  link.addEventListener('click', markRead);
  link.addEventListener('auxclick', markRead);
  window.addEventListener('storage', event => {
    if (event.key === key() || event.key === null) { memory.delete(owner); render(); }
  });
  window.addEventListener('pageshow', event => { if (event.persisted && owner) refresh(); });
  const checkOnReturn = () => {
    if (owner && !document.hidden && Date.now() - lastChecked > 60_000) refresh();
  };
  window.addEventListener('focus', checkOnReturn);
  document.addEventListener('visibilitychange', checkOnReturn);
  window.DomesticSkillUpdates = {refresh};
})();
