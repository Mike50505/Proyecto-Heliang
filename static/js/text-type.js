/* One-shot login heading, matching Universo Ramos's 400ms delay / 48ms cadence. */
(() => {
  const motion = window.matchMedia('(prefers-reduced-motion: reduce)');
  document.querySelectorAll('[data-text-type]').forEach(element => {
    const phrase = element.dataset.textType.split('|')[0]?.trim();
    if (!phrase) return;
    const characters = Array.from(phrase);
    const text = element.querySelector('.login-title-characters') || element;
    let index = 0;
    let timer;
    const finish = () => {
      window.clearTimeout(timer);
      text.textContent = phrase;
    };
    if (motion.matches) { finish(); return; }
    text.textContent = '';
    const tick = () => {
      text.textContent = characters.slice(0, ++index).join('');
      if (index < characters.length) timer = window.setTimeout(tick, 48);
    };
    timer = window.setTimeout(tick, 400);
    motion.addEventListener('change', event => { if (event.matches) finish(); });
    window.addEventListener('pagehide', finish, { once: true });
  });
})();
