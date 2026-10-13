'use strict';
(() => {
const controllers = new WeakMap();
// One spring-driven background follows hover/focus and returns to the chosen subject.
function highlight(list, { selector, kind = "nav", hover = true, pull = 0, follow = false } = {}) {
  if (!list) return () => {};
  if (controllers.has(list)) return controllers.get(list);
  const reduced = matchMedia('(prefers-reduced-motion: reduce)');
  const finePointer = matchMedia('(hover: hover) and (pointer: fine)');
  const items = () => [...list.querySelectorAll(selector)].filter(node => !node.disabled);
  const selected = '[aria-pressed="true"], [aria-current="true"], .active';
  const plate = document.createElement('div');
  plate.className = 'dl-motion-plate' + (kind === 'home' ? ' dl-home-highlight' : '');
  plate.setAttribute('aria-hidden', 'true');
  list.prepend(plate);
  list.classList.add('dl-motion', `dl-motion-${kind}`);
  if (kind === 'home') list.classList.add('dl-home-motion');
  let hovered = null, target = null, frame = 0, lastTime = 0;
  const values = Object.fromEntries(['x', 'y', 'width', 'height', 'pullX', 'pullY', 'opacity']
    .map(key => [key, { value: 0, goal: 0, velocity: 0 }]));

  function paint() {
    const v = values;
    plate.style.transform = `translate3d(${v.x.value + v.pullX.value}px, ${v.y.value + v.pullY.value}px, 0)`;
    plate.style.width = `${Math.max(0, v.width.value)}px`;
    plate.style.height = `${Math.max(0, v.height.value)}px`;
    plate.style.opacity = String(Math.max(0, Math.min(1, v.opacity.value)));
    plate.hidden = v.opacity.value <= 0;
    if (follow) {
      target?.style.setProperty('--subject-pull-x', `${v.pullX.value / 4}px`);
      target?.style.setProperty('--subject-pull-y', `${v.pullY.value / 4}px`);
    }
  }
  function tick(time) {
    const dt = Math.min((time - lastTime) / 1000 || 1 / 60, 1 / 30);
    lastTime = time;
    let moving = false;
    for (const [key, s] of Object.entries(values)) {
      const stiffness = key === 'opacity' ? 700 : 240;
      const damping = key === 'opacity' ? 46 : 26;
      // Small integration steps keep the spring stable on slower displays.
      for (let i = 0; i < 3; i++) {
        s.velocity += ((s.goal - s.value) * stiffness - s.velocity * damping) * dt / 3;
        s.value += s.velocity * dt / 3;
      }
      if (Math.abs(s.goal - s.value) < .001 && Math.abs(s.velocity) < .01) {
        s.value = s.goal;
        s.velocity = 0;
      } else moving = true;
    }
    paint();
    frame = moving ? requestAnimationFrame(tick) : 0;
  }
  function schedule() {
    if (reduced.matches) {
      cancelAnimationFrame(frame);
      frame = 0;
      for (const s of Object.values(values)) { s.value = s.goal; s.velocity = 0; }
      paint();
    } else if (!frame) {
      lastTime = performance.now();
      frame = requestAnimationFrame(tick);
    }
  }
  function update() {
    if (!list.contains(plate)) list.prepend(plate);
    if (hovered && !list.contains(hovered)) hovered = null;
    const buttons = items();
    const focused = hover && buttons.find(button => button.matches(':focus-visible') || button.querySelector(':focus-visible'));
    const next = hovered || focused || buttons.find(button => button.matches(selected));
    if (target !== next) {
      target?.style.removeProperty('--subject-pull-x');
      target?.style.removeProperty('--subject-pull-y');
      values.pullX.goal = values.pullY.goal = 0;
      target = next;
    }
    const box = list.getBoundingClientRect();
    const rect = target?.getBoundingClientRect();
    if (!rect?.width || !box.width) {
      values.opacity.goal = 0;
    } else {
      const goals = { x: rect.left - box.left + list.scrollLeft - list.clientLeft, y: rect.top - box.top + list.scrollTop - list.clientTop, width: rect.width, height: rect.height };
      for (const [key, goal] of Object.entries(goals)) {
        values[key].goal = goal;
        // First entry appears under the pointer, never flies in from the corner.
        if (values.opacity.value < .05) { values[key].value = goal; values[key].velocity = 0; }
      }
      values.opacity.goal = 1;
    }
    schedule();
  }
  list.addEventListener('pointermove', event => {
    if (!hover || event.pointerType === 'touch' || !finePointer.matches) return;
    const button = event.target.closest(selector);
    const next = button && !button.disabled ? button : null;
    if (next !== hovered) { hovered = next; update(); }
    if (!hovered || !pull || reduced.matches) return;
    const rect = hovered.getBoundingClientRect();
    const clamp = n => Math.max(-1, Math.min(1, n));
    values.pullX.goal = clamp((event.clientX - rect.left) / rect.width * 2 - 1) * 2.8 * pull;
    values.pullY.goal = clamp((event.clientY - rect.top) / rect.height * 2 - 1) * 1.8 * pull;
    schedule();
  });
  list.addEventListener('pointerleave', () => {
    hovered = null;
    values.pullX.goal = values.pullY.goal = 0;
    update();
  });
  list.addEventListener('focusin', event => {
    if (event.target.matches(':focus-visible')) hovered = null;
    update();
  });
  list.addEventListener('focusout', () => queueMicrotask(update));
  const resetMotion = () => {
    hovered = null;
    values.pullX.goal = values.pullY.goal = 0;
    update();
  };
  reduced.addEventListener('change', resetMotion);
  finePointer.addEventListener('change', resetMotion);
  const observer = new ResizeObserver(update);
  observer.observe(list);
  // Observe replacement rows/navigation and selection, never our own style writes.
  new MutationObserver(update).observe(list, { childList:true, subtree:true, attributes:true, attributeFilter:['aria-pressed', 'aria-current'] });
  list.addEventListener('click', () => queueMicrotask(update));
  list.addEventListener('scroll', update, { passive:true });
  document.fonts?.ready.then(update);
  controllers.set(list, update);
  update();
  return update;
}

const reveals = new WeakMap();
function reveal(node) {
  if (!node) return;
  reveals.get(node)?.cancel();
  if (matchMedia('(prefers-reduced-motion: reduce)').matches || !node.animate) return;
  reveals.set(node, node.animate([{opacity:.7,transform:'translateY(3px)'},{opacity:1,transform:'translateY(0)'}], {duration:180,easing:'cubic-bezier(.23,1,.32,1)'}));
}
window.DomesticMotion = { highlight, reveal };
})();
