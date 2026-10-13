'use strict';
(() => {
  const reduced = matchMedia('(prefers-reduced-motion: reduce)');
  let view = '', scroller = null;
  const reset = () => scroller?.reset();

  function configure() {
    scroller?.destroy();
    scroller = null;
    document.documentElement.classList.remove('dl-smooth-scroll');
    if (!['rulePackage', 'canbuBatches'].includes(view) || reduced.matches || !window.Lenis) return;
    scroller = new window.Lenis({
      duration: .85,
      smoothWheel: true,
      syncTouch: false,
      autoRaf: true,
      allowNestedScroll: true,
      naiveDimensions: true,
      // Dialogs, form controls and horizontal gestures retain native scrolling.
      prevent: node => node.matches('dialog, [role="dialog"], .dl-modal, input, textarea, select'),
      virtualScroll: ({event, deltaX, deltaY}) => {
        if (event.ctrlKey || event.shiftKey || Math.abs(deltaX) > Math.abs(deltaY) ||
            getComputedStyle(document.body).overflowY === 'hidden') {
          reset();
          return false;
        }
      },
    });
    document.documentElement.classList.add('dl-smooth-scroll');
  }

  function setScrollView(next) {
    if (next === view) return;
    view = next;
    configure();
  }

  function scrollTo(target, {immediate = false} = {}) {
    if (target == null) return;
    const distance = typeof target === 'number' ? target - window.scrollY : target.getBoundingClientRect().top;
    if (scroller) {
      scroller.reset();
      scroller.resize();
      scroller.scrollTo(target, {
        immediate,
        duration: Math.min(1.2, Math.max(.45, .4 + Math.abs(distance) / 2400)),
        easing: t => 1 - (1 - t) ** 4,
      });
    } else {
      const behavior = immediate || reduced.matches ? 'instant' : 'smooth';
      if (typeof target === 'number') window.scrollTo({top: target, behavior});
      else target.scrollIntoView({block: 'start', behavior});
    }
  }

  // Cancel residual wheel motion before dragging the native scrollbar, clicking
  // another view, using the keyboard, or starting a touch gesture.
  window.addEventListener('pointerdown', reset, {capture: true, passive: true});
  window.addEventListener('keydown', event => {
    if (['ArrowUp', 'ArrowDown', 'PageUp', 'PageDown', 'Home', 'End', ' ', 'Tab', 'Enter', 'Escape'].includes(event.key)) reset();
  }, {capture: true});
  reduced.addEventListener('change', configure);
  Object.assign(window.DomesticMotion, {setScrollView, scrollTo});
})();
