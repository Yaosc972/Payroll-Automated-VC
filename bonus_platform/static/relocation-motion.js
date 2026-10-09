(() => {
  "use strict";
  const panel = document.getElementById("relocationProcessing"), result = document.getElementById("relocationResult");
  const reduce = matchMedia("(prefers-reduced-motion: reduce)");
  const scenes = [...panel.querySelectorAll("[data-scene]")];
  let loop = null, reveal = null, transition = null, stage = -1;
  const canAnimate = () => window.gsap && !reduce.matches && !document.hidden && location.hash === "#relocation-allowance";
  function stop() { loop?.kill(); loop = null; transition?.kill(); transition = null; }
  function sceneAnimation(index) {
    stop(); scenes.forEach((scene, i) => { scene.hidden = i !== index; });
    const scene = scenes[index];
    if (window.gsap) gsap.set([scene, ...scene.querySelectorAll("svg *")], { clearProps: "all" });
    if (!canAnimate()) return;
    transition = gsap.fromTo(scene, { opacity: 0, y: 12, scale: .98 }, { opacity: 1, y: 0, scale: 1, duration: .45, ease: "power3.out", clearProps: "all" });
    const q = (selector) => scene.querySelectorAll(selector);
    loop = gsap.timeline({ repeat: -1, repeatDelay: .4 });
    if (index === 0) {
      loop.fromTo(q('.scan-light, .scan-beam'), { y: 0 }, { y: 146, duration: 2.3, ease: 'none' }, 0)
        .fromTo(q('.scan-row'), { opacity: .35 }, { opacity: 1, duration: .35, stagger: .38 }, .1)
        .fromTo(q('.scan-packet'), { x: -22, opacity: 0 }, { x: 10, opacity: 1, duration: .8, ease: 'power2.out' }, .1)
        .to(q('.scan-packet'), { x: 55, opacity: 0, duration: .5 }, 1.2);
    } else if (index === 1) {
      loop.fromTo(q('.person-card'), { x: -18, opacity: .25 }, { x: 0, opacity: 1, stagger: .25, duration: .6, ease: 'power2.out' }, 0)
        .fromTo(q('.record-card'), { x: 18, opacity: .25 }, { x: 0, opacity: 1, stagger: .25, duration: .6 }, .15)
        .fromTo(q('.match-check'), { strokeDasharray: 28, strokeDashoffset: 28 }, { strokeDashoffset: 0, stagger: .35, duration: .4 }, .7)
        .to(q('.match-link'), { strokeDashoffset: -36, duration: 2, ease: 'none' }, 0)
        .fromTo(q('.match-orb'), { scale: .85, transformOrigin: 'center' }, { scale: 1, duration: .6, ease: 'back.out(1.5)' }, .5);
    } else if (index === 2) {
      q('.org-path').forEach(path => { const length = path.getTotalLength(); gsap.set(path, { strokeDasharray: length, strokeDashoffset: length }); });
      loop.to(q('.org-path'), { strokeDashoffset: 0, duration: 1.2, stagger: .6, ease: 'power1.inOut' }, .2)
        .fromTo(q('.org-node'), { opacity: .25, y: -6 }, { opacity: 1, y: 0, duration: .45, stagger: .2 }, 0)
        .fromTo(q('.org-pulse'), { scale: .6, opacity: .8, transformOrigin: 'center' }, { scale: 1.4, opacity: 0, duration: 1.5 }, .3);
    } else {
      loop.fromTo(q('.ledger-row'), { x: -12, opacity: 0 }, { x: 0, opacity: 1, duration: .45, stagger: .3, ease: 'power2.out' }, 0)
        .fromTo(q('.ledger-seal'), { scale: .7, opacity: 0, transformOrigin: 'center' }, { scale: 1, opacity: 1, duration: .6, ease: 'back.out(1.8)' }, 1.2)
        .fromTo(q('.seal-check'), { strokeDasharray: 60, strokeDashoffset: 60 }, { strokeDashoffset: 0, duration: .5 }, 1.7);
    }
  }
  function update(index, fraction) {
    if (index !== stage) { stage = index; sceneAnimation(index); }
    const displayIndex = Math.min(index, 2);
    const tracks = [...panel.querySelectorAll('.step-track i')];
    const fills = [document.getElementById('relocationMeterFill'), ...tracks];
    fills.forEach((fill, i) => {
      const value = i === 0 ? fraction ?? 0 : i - 1 < displayIndex ? 1 : i - 1 === displayIndex ? fraction ?? 0 : 0;
      if (window.gsap) gsap.to(fill, { scaleX: value, duration: canAnimate() ? .55 : 0, ease: 'power2.out', overwrite: true });
      else fill.style.transform = `scaleX(${value})`;
    });
  }
  function start() {
    stop(); reveal?.kill(); stage = -1; panel.hidden = false;
    if (window.gsap) gsap.set([panel, ...result.querySelectorAll('.relocation-summary > div, :scope > .workspace-panel')], { clearProps: 'all' });
    update(0, null);
  }
  function complete() {
    update(3, 1); stop(); reveal?.kill();
    const blocks = [...result.querySelectorAll('.relocation-summary > div, :scope > .workspace-panel')];
    if (!canAnimate()) { panel.hidden = true; if (window.gsap) gsap.set(blocks, { clearProps: 'all' }); return; }
    reveal = gsap.timeline().to(panel, { opacity: 0, y: -10, duration: .22, onComplete: () => { panel.hidden = true; gsap.set(panel, { clearProps: 'all' }); } })
      .fromTo(blocks, { opacity: 0, y: 18 }, { opacity: 1, y: 0, duration: .45, stagger: .055, ease: 'power3.out', clearProps: 'all' });
  }
  function error() { stop(); reveal?.kill(); if (window.gsap) gsap.set(panel, { clearProps: 'all' }); panel.hidden = false; }
  function sync() { if (!canAnimate()) { stop(); if (reduce.matches) { reveal?.progress(1); if (stage >= 0) sceneAnimation(stage); } } else if (panel.dataset.state === 'running' && stage >= 0) sceneAnimation(stage); }
  document.addEventListener('visibilitychange', sync); window.addEventListener('hashchange', sync); reduce.addEventListener('change', sync);
  window.RelocationMotion = { start, update, complete, error };
})();
