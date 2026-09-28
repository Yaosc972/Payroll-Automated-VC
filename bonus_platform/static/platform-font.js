(() => {
  'use strict';
  const platform = navigator.userAgentData?.platform || navigator.platform || '';
  if (!/^Win/i.test(platform)) return;

  const base = new URL('.', document.currentScript.src);
  document.documentElement.dataset.platformFont = 'harmonyos';
  const stylesheet = document.createElement('link');
  stylesheet.rel = 'stylesheet';
  stylesheet.href = new URL('platform-font.css?v=1', base).href;
  document.head.append(stylesheet);

  const addNotice = () => {
    if (document.getElementById('platformFontNotice')) return;
    const notice = document.createElement('footer');
    notice.id = 'platformFontNotice';
    const link = document.createElement('a');
    link.href = new URL('font-license.html', base).href;
    link.target = '_blank';
    link.rel = 'noopener';
    link.textContent = '界面字体：HarmonyOS Sans · 字体许可';
    notice.append(link);
    document.body.append(notice);
  };
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', addNotice, { once: true });
  else addNotice();
})();
