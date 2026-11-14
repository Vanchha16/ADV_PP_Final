/* Behaviour and motion shared by the store and the admin (same feel as the MA app).
   Everything still works without JS; with "reduce motion" nothing animates. */
(() => {
  const root = document.documentElement;
  const reduce = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  const $$ = (sel, el = document) => Array.from(el.querySelectorAll(sel));

  /* ---------- theme: light / dark / system, remembered in this browser ---------- */
  const KEY = 'aws_theme';
  const sysDark = () => window.matchMedia('(prefers-color-scheme: dark)').matches;
  const getMode = () => { try { return localStorage.getItem(KEY) || 'system'; } catch { return 'system'; } };
  const applyTheme = (mode) => {
    const dark = mode === 'dark' || (mode === 'system' && sysDark());
    root.classList.toggle('dark', dark);
    root.setAttribute('data-theme-mode', mode);
    $$('[data-theme-switch] [data-mode]').forEach(b => b.setAttribute('aria-checked', String(b.dataset.mode === mode)));
    $$('[data-theme-icon]').forEach(i => { i.textContent = dark ? 'light_mode' : 'dark_mode'; });
  };
  const setMode = (mode) => {
    root.classList.add('theme-fade');
    setTimeout(() => root.classList.remove('theme-fade'), 300);
    try { localStorage.setItem(KEY, mode); } catch { /* private mode */ }
    applyTheme(mode);
  };
  applyTheme(getMode());
  window.matchMedia('(prefers-color-scheme: dark)').addEventListener?.('change', () => getMode() === 'system' && applyTheme('system'));
  $$('[data-theme-switch] [data-mode]').forEach(b => b.addEventListener('click', () => setMode(b.dataset.mode)));
  $$('[data-theme-toggle]').forEach(b => b.addEventListener('click', () => setMode(root.classList.contains('dark') ? 'light' : 'dark')));

  /* ---------- reveal on scroll ---------- */
  const revealEls = $$('[data-reveal]');
  if (reduce || !('IntersectionObserver' in window)) {
    revealEls.forEach(el => el.classList.add('is-visible'));
  } else {
    const io = new IntersectionObserver(entries => entries.forEach(e => {
      if (!e.isIntersecting) return;
      e.target.classList.add('is-visible');
      io.unobserve(e.target);
    }), { rootMargin: '0px 0px -6% 0px', threshold: 0.06 });
    revealEls.forEach(el => {
      el.style.transitionDelay = `${Math.min(parseInt(el.dataset.revealIndex || '0', 10), 8) * 60}ms`;
      io.observe(el);
    });
  }

  /* ---------- KPI count-up ---------- */
  const fmt = (n, d, p) => p + n.toLocaleString('en-US', { minimumFractionDigits: d, maximumFractionDigits: d });
  $$('[data-count]').forEach(el => {
    const target = parseFloat(el.dataset.count) || 0;
    const d = parseInt(el.dataset.decimals || '0', 10);
    const p = el.dataset.prefix || '';
    if (reduce || !target) { el.textContent = fmt(target, d, p); return; }
    const start = performance.now();
    const step = now => {
      const t = Math.min(1, (now - start) / 900);
      el.textContent = fmt(target * (1 - Math.pow(1 - t, 3)), d, p);
      if (t < 1) requestAnimationFrame(step);
    };
    requestAnimationFrame(step);
  });

  /* ---------- sticky bars get a shadow after scrolling ---------- */
  $$('[data-elevate]').forEach(bar => {
    const update = () => bar.classList.toggle('is-scrolled', window.scrollY > 8);
    update();
    window.addEventListener('scroll', update, { passive: true });
  });

  /* ---------- promo banner slider (MA: PromoCarousel) ---------- */
  $$('[data-carousel]').forEach(box => {
    const track = box.querySelector('.promo-track');
    const slides = $$('.promo-slide', box);
    const dots = $$('.promo-dots button', box);
    let i = 0, timer = null;
    const go = (n) => {
      i = (n + slides.length) % slides.length;
      track.style.transform = `translateX(-${i * 100}%)`;
      slides.forEach((s, k) => { s.classList.toggle('is-active', k === i); s.tabIndex = k === i ? 0 : -1; s.setAttribute('aria-hidden', String(k !== i)); });
      dots.forEach((d, k) => d.setAttribute('aria-current', String(k === i)));
    };
    const play = () => { if (!reduce && slides.length > 1) { stop(); timer = setInterval(() => go(i + 1), 5000); } };
    const stop = () => clearInterval(timer);
    dots.forEach((d, k) => d.addEventListener('click', () => { go(k); play(); }));
    box.addEventListener('mouseenter', stop);
    box.addEventListener('mouseleave', play);
    box.addEventListener('focusin', stop);
    let x0 = null;
    box.addEventListener('touchstart', e => { x0 = e.touches[0].clientX; stop(); }, { passive: true });
    box.addEventListener('touchend', e => {
      if (x0 === null) return;
      const dx = e.changedTouches[0].clientX - x0;
      if (Math.abs(dx) > 40) go(i + (dx < 0 ? 1 : -1));
      x0 = null; play();
    });
    go(0); play();
  });

  /* ---------- quantity steppers ---------- */
  $$('.stepper').forEach(st => {
    const input = st.querySelector('input');
    $$('[data-step]', st).forEach(btn => btn.addEventListener('click', () => {
      if (input.disabled) return;
      const min = parseInt(input.min || '0', 10), max = parseInt(input.max || '999', 10);
      const v = Math.min(Math.max((parseInt(input.value, 10) || 0) + parseInt(btn.dataset.step, 10), min), max);
      input.value = v;
      input.dispatchEvent(new Event('change', { bubbles: true }));
    }));
  });
  // Cart quantities save themselves a moment after the last change.
  let cartTimer = null;
  $$('[data-autosubmit-delay]').forEach(input => input.addEventListener('change', () => {
    clearTimeout(cartTimer);
    cartTimer = setTimeout(() => input.form.requestSubmit(), 700);
  }));

  /* ---------- store filters ---------- */
  $$('[data-autosubmit]').forEach(el => el.addEventListener('change', () => el.form && el.form.requestSubmit()));
  const sort = document.querySelector('[data-sort]');
  const filterForm = document.getElementById('filter-form');
  if (sort && filterForm) sort.addEventListener('change', () => { filterForm.elements.sort.value = sort.value; filterForm.requestSubmit(); });

  /* ---------- add to cart: the round button turns green with a tick ---------- */
  $$('form[action$="/cart/add"]').forEach(form => form.addEventListener('submit', () => {
    const btn = form.querySelector('button:not([type="button"])');
    if (!btn) return;
    btn.classList.add('is-busy');
    const ico = btn.querySelector('.ms');
    if (ico && btn.classList.contains('add-round')) ico.textContent = 'check';
  }));

  /* ---------- copy product link ---------- */
  $$('[data-copy]').forEach(btn => btn.addEventListener('click', async () => {
    const label = btn.querySelector('span:not(.ms)') || btn;
    try { await navigator.clipboard.writeText(btn.dataset.copy); label.textContent = 'Link copied'; }
    catch { label.textContent = 'Copy failed'; }
    setTimeout(() => { label.textContent = 'Copy link'; }, 2000);
  }));

  /* ---------- toasts fade away by themselves ---------- */
  $$('[data-toast]').forEach((t, k) => setTimeout(() => {
    t.classList.add('leaving');
    t.addEventListener('animationend', () => t.remove(), { once: true });
    if (reduce) t.remove();
  }, 4200 + k * 400));

  /* ---------- "Are you sure?" dialog (MA: ConfirmDialog) ---------- */
  const confirmBox = (message, okLabel) => new Promise(resolve => {
    const back = document.createElement('div');
    back.className = 'dialog-back';
    back.innerHTML = `<div class="dialog-card" role="alertdialog" aria-modal="true" aria-labelledby="dlg-t" aria-describedby="dlg-m">
        <div class="icon"><span class="ms ms-lg" aria-hidden="true">warning</span></div>
        <h3 id="dlg-t">Are you sure?</h3><p id="dlg-m"></p>
        <div class="d-flex gap-2 mt-3"><button type="button" class="btn btn-line flex-fill" data-no>Keep it</button>
        <button type="button" class="btn btn-red flex-fill" data-yes></button></div></div>`;
    back.querySelector('#dlg-m').textContent = message;
    back.querySelector('[data-yes]').textContent = okLabel || 'Confirm';
    const done = (v) => { back.remove(); document.removeEventListener('keydown', onKey); resolve(v); };
    const onKey = (e) => { if (e.key === 'Escape') done(false); };
    back.addEventListener('click', e => { if (e.target === back) done(false); });
    back.querySelector('[data-no]').addEventListener('click', () => done(false));
    back.querySelector('[data-yes]').addEventListener('click', () => done(true));
    document.addEventListener('keydown', onKey);
    document.body.appendChild(back);
    back.querySelector('[data-no]').focus();
  });
  document.addEventListener('submit', async e => {
    const form = e.target;
    const trigger = e.submitter && e.submitter.dataset.confirm ? e.submitter : form;
    const msg = trigger.dataset.confirm;
    if (!msg || form.dataset.confirmed) return;
    e.preventDefault();
    if (await confirmBox(msg, trigger.dataset.confirmOk)) {
      form.dataset.confirmed = '1';
      form.requestSubmit(e.submitter || undefined);
    }
  });

  /* ---------- admin sidebar (slides in below 992px) ---------- */
  const closeSidebar = () => document.body.classList.remove('sidebar-open');
  $$('[data-sidebar-toggle]').forEach(b => b.addEventListener('click', () => document.body.classList.toggle('sidebar-open')));
  $$('[data-sidebar-close]').forEach(el => el.addEventListener('click', closeSidebar));
  document.addEventListener('keydown', e => { if (e.key === 'Escape') closeSidebar(); });
})();
