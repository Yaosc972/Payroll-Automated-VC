/* SVG paths adapted from Tabler Icons (MIT). See licenses/tabler-icons.txt. */
(() => {
  'use strict';
  const shapes = {
  "home": "<path d=\"M3 11l9-8 9 8M5 9v11h5v-6h4v6h5V9\"/>",
  "calendar": "<rect x=\"4\" y=\"5\" width=\"16\" height=\"16\" rx=\"2\"/><path d=\"M8 3v4M16 3v4M4 11h16\"/>",
  "plus": "<path d=\"M12 5l0 14\" />\n  <path d=\"M5 12l14 0\" />",
  "search": "<path d=\"M3 10a7 7 0 1 0 14 0a7 7 0 1 0 -14 0\" />\n  <path d=\"M21 21l-6 -6\" />",
  "down": "<path d=\"M4 17v2a2 2 0 0 0 2 2h12a2 2 0 0 0 2 -2v-2\" />\n  <path d=\"M7 11l5 5l5 -5\" />\n  <path d=\"M12 4l0 12\" />",
  "more": "<path d=\"M4 12a1 1 0 1 0 2 0a1 1 0 1 0 -2 0\" />\n  <path d=\"M11 12a1 1 0 1 0 2 0a1 1 0 1 0 -2 0\" />\n  <path d=\"M18 12a1 1 0 1 0 2 0a1 1 0 1 0 -2 0\" />",
  "file": "<path d=\"M14 3v4a1 1 0 0 0 1 1h4\" />\n  <path d=\"M17 21h-10a2 2 0 0 1 -2 -2v-14a2 2 0 0 1 2 -2h7l5 5v11a2 2 0 0 1 -2 2\" />\n  <path d=\"M9 17h6\" />\n  <path d=\"M9 13h6\" />",
  "close": "<path d=\"M18 6l-12 12\" />\n  <path d=\"M6 6l12 12\" />",
  "left": "<path d=\"M15 6l-6 6l6 6\" />",
  "right": "<path d=\"M9 6l6 6l-6 6\" />",
  "check": "<path d=\"M5 12l5 5l10 -10\" />",
  "refresh": "<path d=\"M20 11a8.1 8.1 0 0 0 -15.5 -2m-.5 -4v4h4\" />\n  <path d=\"M4 13a8.1 8.1 0 0 0 15.5 2m.5 4v-4h-4\" />",
  "grid": "<rect x=\"4\" y=\"4\" width=\"6\" height=\"6\" rx=\"1\"/><rect x=\"14\" y=\"4\" width=\"6\" height=\"6\" rx=\"1\"/><rect x=\"4\" y=\"14\" width=\"6\" height=\"6\" rx=\"1\"/><rect x=\"14\" y=\"14\" width=\"6\" height=\"6\" rx=\"1\"/>",
  "list": "<path d=\"M8 6h12M8 12h12M8 18h12M4 6h.01M4 12h.01M4 18h.01\"/>",
  "table": "<path d=\"M3 5a2 2 0 0 1 2 -2h14a2 2 0 0 1 2 2v14a2 2 0 0 1 -2 2h-14a2 2 0 0 1 -2 -2v-14\" />\n  <path d=\"M3 10h18\" />\n  <path d=\"M10 3v18\" />",
  "compare": "<path d=\"M4 7h15l-3 -3M20 17H5l3 3M20 7l-4 4M4 17l4 -4\" />",
  "checklist": "<path d=\"M3.5 5.5l1.5 1.5l2.5 -2.5\" />\n  <path d=\"M3.5 11.5l1.5 1.5l2.5 -2.5\" />\n  <path d=\"M3.5 17.5l1.5 1.5l2.5 -2.5\" />\n  <path d=\"M11 6l9 0\" />\n  <path d=\"M11 12l9 0\" />\n  <path d=\"M11 18l9 0\" />",
  "people": "<path d=\"M5 7a4 4 0 1 0 8 0a4 4 0 1 0 -8 0\" />\n  <path d=\"M3 21v-2a4 4 0 0 1 4 -4h4a4 4 0 0 1 4 4v2\" />\n  <path d=\"M16 3.13a4 4 0 0 1 0 7.75\" />\n  <path d=\"M21 21v-2a4 4 0 0 0 -3 -3.85\" />",
  "building": "<path d=\"M3 21l18 0\" />\n  <path d=\"M9 8l1 0\" />\n  <path d=\"M9 12l1 0\" />\n  <path d=\"M9 16l1 0\" />\n  <path d=\"M14 8l1 0\" />\n  <path d=\"M14 12l1 0\" />\n  <path d=\"M14 16l1 0\" />\n  <path d=\"M5 21v-16a2 2 0 0 1 2 -2h10a2 2 0 0 1 2 2v16\" />",
  "globe": "<path d=\"M3 12a9 9 0 1 0 18 0a9 9 0 0 0 -18 0\" />\n  <path d=\"M3.6 9h16.8\" />\n  <path d=\"M3.6 15h16.8\" />\n  <path d=\"M11.5 3a17 17 0 0 0 0 18\" />\n  <path d=\"M12.5 3a17 17 0 0 1 0 18\" />",
  "alert": "<path d=\"M3 12a9 9 0 1 0 18 0a9 9 0 0 0 -18 0\" />\n  <path d=\"M12 8v4\" />\n  <path d=\"M12 16h.01\" />",
  "folder": "<path d=\"M5 19l2.757 -7.351a1 1 0 0 1 .936 -.649h12.307a1 1 0 0 1 .986 1.164l-.996 5.211a2 2 0 0 1 -1.964 1.625h-14.026a2 2 0 0 1 -2 -2v-11a2 2 0 0 1 2 -2h4l3 3h7a2 2 0 0 1 2 2v2\" />",
  "upload": "<path d=\"M4 17v2a2 2 0 0 0 2 2h12a2 2 0 0 0 2 -2v-2\" />\n  <path d=\"M7 9l5 -5l5 5\" />\n  <path d=\"M12 4l0 12\" />",
  "excel": "<path d=\"M14 3v4a1 1 0 0 0 1 1h4\" />\n  <path d=\"M17 21h-10a2 2 0 0 1 -2 -2v-14a2 2 0 0 1 2 -2h7l5 5v11a2 2 0 0 1 -2 2\" />\n  <path d=\"M8 11h8v7h-8l0 -7\" />\n  <path d=\"M8 15h8\" />\n  <path d=\"M11 11v7\" />",
  "pdf": "<path d=\"M14 3v4a1 1 0 0 0 1 1h4\" />\n  <path d=\"M5 12v-7a2 2 0 0 1 2 -2h7l5 5v4\" />\n  <path d=\"M5 18h1.5a1.5 1.5 0 0 0 0 -3h-1.5v6\" />\n  <path d=\"M17 18h2\" />\n  <path d=\"M20 15h-3v6\" />\n  <path d=\"M11 15v6h1a2 2 0 0 0 2 -2v-2a2 2 0 0 0 -2 -2h-1\" />",
  "image": "<path d=\"M15 8h.01\" />\n  <path d=\"M3 6a3 3 0 0 1 3 -3h12a3 3 0 0 1 3 3v12a3 3 0 0 1 -3 3h-12a3 3 0 0 1 -3 -3v-12\" />\n  <path d=\"M3 16l5 -5c.928 -.893 2.072 -.893 3 0l5 5\" />\n  <path d=\"M14 14l1 -1c.928 -.893 2.072 -.893 3 0l3 3\" />",
  "api": "<path d=\"M5 9.897c0 -1.714 1.46 -3.104 3.26 -3.104c.275 -1.22 1.255 -2.215 2.572 -2.611c1.317 -.397 2.77 -.134 3.811 .69c1.042 .822 1.514 2.08 1.239 3.3h.693a2.42 2.42 0 0 1 2.425 2.414a2.42 2.42 0 0 1 -2.425 2.414h-8.315c-1.8 0 -3.26 -1.39 -3.26 -3.103\" />\n  <path d=\"M12 13v3\" />\n  <path d=\"M10 18a2 2 0 1 0 4 0a2 2 0 1 0 -4 0\" />\n  <path d=\"M14 18h7\" />\n  <path d=\"M3 18h7\" />",
  "archive": "<path d=\"M3 6a2 2 0 0 1 2 -2h14a2 2 0 0 1 2 2a2 2 0 0 1 -2 2h-14a2 2 0 0 1 -2 -2\" />\n  <path d=\"M5 8v10a2 2 0 0 0 2 2h10a2 2 0 0 0 2 -2v-10\" />\n  <path d=\"M10 12l4 0\" />",
  "clock": "<path d=\"M12 8l0 4l2 2\" />\n  <path d=\"M3.05 11a9 9 0 1 1 .5 4m-.5 5v-5h5\" />",
  "link": "<path d=\"M15 7l-6.5 6.5a1.5 1.5 0 0 0 3 3l6.5 -6.5a3 3 0 0 0 -6 -6l-6.5 6.5a4.5 4.5 0 0 0 9 9l6.5 -6.5\" />",
  "external": "<path d=\"M12 6h-6a2 2 0 0 0 -2 2v10a2 2 0 0 0 2 2h10a2 2 0 0 0 2 -2v-6\" />\n  <path d=\"M11 13l9 -9\" />\n  <path d=\"M15 4h5v5\" />",
  "chevron": "<path d=\"M6 9l6 6l6 -6\" />",
  "person": "<path d=\"M8 7a4 4 0 1 0 8 0a4 4 0 0 0 -8 0\" />\n  <path d=\"M16 19h6\" />\n  <path d=\"M19 16v6\" />\n  <path d=\"M6 21v-2a4 4 0 0 1 4 -4h4\" />"
};
  const sprite = document.createElementNS('http://www.w3.org/2000/svg','svg');
  sprite.id = 'recruitmentIconLibrary';
  sprite.setAttribute('aria-hidden','true');
  sprite.setAttribute('focusable','false');
  sprite.style.cssText = 'position:absolute;width:0;height:0;overflow:hidden;pointer-events:none';
  sprite.innerHTML = '<defs>'+Object.entries(shapes).map(([name,paths])=>`<symbol id="icon-${name}" viewBox="0 0 24 24">${paths}</symbol>`).join('')+'</defs>';
  document.body.prepend(sprite);
  const svg = name => `<svg class="rd-icon" viewBox="0 0 24 24" aria-hidden="true" focusable="false"><use href="#icon-${Object.hasOwn(shapes,name)?name:'file'}"/></svg>`;
  window.RecruitmentIcons = {svg};
})();
