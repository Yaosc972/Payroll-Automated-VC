(() => {
  "use strict";
  const panel = document.getElementById("mealProcessing"), result = document.getElementById("mealResult");
  const scenes = [...panel.querySelectorAll("[data-meal-scene]")], reduce = matchMedia("(prefers-reduced-motion: reduce)");
  let stage = -1, running = false, loop = null, transition = null, reveal = null;
  const canAnimate = () => window.gsap && !reduce.matches && !document.hidden && ["#meal-allowance", "#wx-meal-allowance"].includes(location.hash);
  function stop() {
    loop?.kill(); transition?.kill(); loop = null; transition = null;
    if (window.gsap) gsap.set([...scenes, ...panel.querySelectorAll("svg *, .meal-status-dots i")], { clearProps: "all" });
  }
  function sceneAnimation(index) {
    stop(); scenes.forEach((scene, i) => { scene.hidden = i !== index; });
    if (!running || !canAnimate()) return;
    const scene = scenes[index], q = selector => scene.querySelectorAll(selector);
    transition = gsap.fromTo(scene, { opacity: 0, y: 12 }, { opacity: 1, y: 0, duration: .42, ease: "power3.out", clearProps: "all" });
    loop = gsap.timeline({ repeat: -1, repeatDelay: .35 });
    if (index === 0) {
      loop.fromTo(q(".person-card"), { x: -16, opacity: .3 }, { x: 0, opacity: 1, stagger: .23, duration: .55, ease: "power2.out" }, 0)
        .fromTo(q(".record-card"), { x: 16, opacity: .3 }, { x: 0, opacity: 1, stagger: .23, duration: .55 }, .15)
        .fromTo(q(".match-check"), { strokeDasharray: 28, strokeDashoffset: 28 }, { strokeDashoffset: 0, stagger: .32, duration: .4 }, .65)
        .to(q(".match-link"), { strokeDashoffset: -36, duration: 2, ease: "none" }, 0)
        .fromTo(q(".match-orb"), { scale: .85, transformOrigin: "center" }, { scale: 1, duration: .6, ease: "back.out(1.5)" }, .45);
    } else if (index === 1) {
      loop.fromTo(q(".scan-light, .scan-beam"), { y: 0 }, { y: 146, duration: 2.3, ease: "none" }, 0)
        .fromTo(q(".scan-row"), { opacity: .3 }, { opacity: 1, duration: .35, stagger: .38 }, .1)
        .fromTo(q(".scan-packet"), { x: -22, opacity: 0 }, { x: 10, opacity: 1, duration: .8, ease: "power2.out" }, .1)
        .to(q(".scan-packet"), { x: 55, opacity: 0, duration: .5 }, 1.2);
    } else {
      loop.fromTo(q(".ledger-row"), { x: -12, opacity: .15 }, { x: 0, opacity: 1, duration: .42, stagger: .28, ease: "power2.out" }, 0)
        .fromTo(q(".ledger-seal"), { scale: .75, opacity: 0, transformOrigin: "center" }, { scale: 1, opacity: 1, duration: .55, ease: "back.out(1.5)" }, 1.15)
        .fromTo(q(".seal-check"), { strokeDasharray: 60, strokeDashoffset: 60 }, { strokeDashoffset: 0, duration: .5 }, 1.65);
    }
    loop.fromTo(panel.querySelectorAll(".meal-status-dots i"), { opacity: .25, y: 0 }, { opacity: 1, y: -3, duration: .35, repeat: 3, yoyo: true, stagger: .14 }, 0);
  }
  function update(index, fraction, active) {
    const changed = stage !== index || running !== active;
    stage = index; running = active;
    if (changed || (active && canAnimate() && !loop)) sceneAnimation(index);
    const fills = [document.getElementById("mealMeterFill"), ...panel.querySelectorAll(".meal-step-track i")];
    fills.forEach((fill, i) => {
      const value = i === 0 ? fraction ?? 0 : i - 1 < index ? 1 : i - 1 === index ? fraction ?? 0 : 0;
      if (window.gsap) gsap.to(fill, { scaleX: value, duration: canAnimate() ? .5 : 0, overwrite: true, ease: "power2.out" }); else fill.style.transform = `scaleX(${value})`;
    });
  }
  function revealResult() {
    running = false; stop(); reveal?.kill();
    const blocks = result.querySelectorAll(".meal-summary > div, :scope > .workspace-panel");
    if (!canAnimate()) { if (window.gsap) gsap.set(blocks, { clearProps: "all" }); return; }
    reveal = gsap.fromTo(blocks, { opacity: 0, y: 18 }, { opacity: 1, y: 0, duration: .45, stagger: .055, ease: "power3.out", clearProps: "all" });
  }
  function sync() {
    if (!canAnimate()) { stop(); if (reduce.matches) reveal?.progress(1); }
    else if (running && stage >= 0 && !panel.hidden && panel.dataset.state === "running") sceneAnimation(stage);
    else stop();
  }
  document.addEventListener("visibilitychange", sync); window.addEventListener("hashchange", sync); reduce.addEventListener("change", sync);
  window.MealAllowanceMotion = { update, stop: () => { running = false; stop(); reveal?.progress(1); }, reveal: revealResult };
})();
