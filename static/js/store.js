/* Чаршафчето storefront — progressive enhancement. Every form also works without JS. */
(() => {
  const $ = (s, el = document) => el.querySelector(s);
  const $$ = (s, el = document) => [...el.querySelectorAll(s)];
  const csrf = () => (document.cookie.match(/(?:^|;\s*)csrftoken=([^;]+)/) || [])[1] || $('[name=csrfmiddlewaretoken]')?.value || '';

  function toast(msg, kind = '') {
    let wrap = $('.flash-wrap');
    if (!wrap) { wrap = document.createElement('div'); wrap.className = 'flash-wrap'; wrap.setAttribute('role', 'status'); document.body.appendChild(wrap); }
    const el = document.createElement('div');
    el.className = `flash ${kind}`; el.textContent = msg; wrap.appendChild(el);
    setTimeout(() => el.remove(), 5000);
  }

  async function post(form) {
    const res = await fetch(form.action, {
      method: 'POST', body: new FormData(form), credentials: 'same-origin',
      headers: { 'X-Requested-With': 'XMLHttpRequest', 'X-CSRFToken': csrf(), Accept: 'application/json' },
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.error || 'Възникна грешка. Опитайте отново.');
    return data;
  }

  function setBadge(sel, n) { $$(sel).forEach(b => { b.textContent = n || ''; }); }

  // ---- overlays -------------------------------------------------------
  const overlay = $('.overlay'), drawer = $('#cartDrawer'), menu = $('#mobileNav');
  function closeAll() { [overlay, drawer, menu].forEach(x => x?.classList.remove('on')); document.body.style.overflow = ''; }
  function openPanel(el) { closeAll(); el.classList.add('on'); overlay.classList.add('on'); document.body.style.overflow = 'hidden'; }

  async function openCart() {
    if (!drawer) return;
    const body = $('#cartDrawerBody');
    const res = await fetch(drawer.dataset.drawerUrl, { credentials: 'same-origin' });
    body.innerHTML = await res.text();
    openPanel(drawer);
  }

  document.addEventListener('click', e => {
    if (e.target.closest('[data-close]')) { closeAll(); return; }
    if (e.target.closest('[data-menu-open]')) { openPanel(menu); return; }
    const cartLink = e.target.closest('[data-cart-open]');
    if (cartLink && !e.metaKey && !e.ctrlKey) {
      if (location.pathname.startsWith('/cart/') || location.pathname.startsWith('/checkout/')) return;
      e.preventDefault(); openCart();
    }
  });
  document.addEventListener('keydown', e => { if (e.key === 'Escape') closeAll(); });

  // ---- AJAX forms -----------------------------------------------------
  document.addEventListener('submit', async e => {
    const form = e.target;
    const kind = form.dataset.ajax;
    if (!kind) return;
    e.preventDefault();
    const btn = form.querySelector('button[type=submit],button:not([type])');
    btn && (btn.disabled = true);
    try {
      const data = await post(form);
      if ('cart_count' in data) setBadge('[data-cart-count]', data.cart_count);
      if ('wishlist_count' in data) setBadge('[data-wishlist-count]', data.wishlist_count);
      if (kind === 'cart-add') { await openCart(); }
      else if (kind === 'drawer') { $('#cartDrawerBody').innerHTML = data.html; }
      else if (kind === 'wish') {
        $$(`[data-wish-product="${data.product_id}"]`).forEach(b => {
          b.classList.toggle('on', data.active);
          b.textContent = data.active ? '♥' : '♡';
          b.setAttribute('aria-pressed', data.active);
        });
        if (form.dataset.removeCard && !data.active) form.closest('.product-card')?.remove();
      }
      if (data.message) toast(data.message, 'success');
    } catch (err) {
      toast(err.message, 'error');
    } finally {
      btn && (btn.disabled = false);
    }
  });

  // ---- quantity steppers ---------------------------------------------
  document.addEventListener('click', e => {
    const b = e.target.closest('[data-step]');
    if (!b) return;
    const input = b.parentElement.querySelector('input');
    const max = Number(input.max || 99), min = Number(input.min || 1);
    input.value = Math.min(max, Math.max(min, Number(input.value || 1) + Number(b.dataset.step)));
    input.dispatchEvent(new Event('change', { bubbles: true }));
  });
  $$('[data-autosubmit]').forEach(el => el.addEventListener('change', () => el.form.requestSubmit ? el.form.requestSubmit() : el.form.submit()));

  // ---- product page: gallery + variants -------------------------------
  $$('.thumbs button').forEach(t => t.addEventListener('click', () => {
    $('#mainImage').src = t.dataset.src;
    $$('.thumbs button').forEach(x => x.classList.toggle('active', x === t));
  }));
  const variantInputs = $$('input[name=variant]');
  function syncVariant() {
    const v = variantInputs.find(i => i.checked);
    if (!v) return;
    const priceEl = $('[data-variant-price]');
    if (priceEl) priceEl.innerHTML = v.dataset.priceHtml;
    const stockEl = $('[data-variant-stock]');
    if (stockEl) stockEl.textContent = v.dataset.stockLabel;
    const qty = $('#qtyInput');
    if (qty) { qty.max = v.dataset.max; if (Number(qty.value) > Number(v.dataset.max)) qty.value = v.dataset.max; }
  }
  variantInputs.forEach(i => i.addEventListener('change', syncVariant));
  syncVariant();

  // ---- tabs -----------------------------------------------------------
  $$('[data-tabs]').forEach(root => {
    const buttons = $$('[data-tab]', root);
    buttons.forEach(b => b.addEventListener('click', () => {
      buttons.forEach(x => x.classList.toggle('active', x === b));
      $$('[data-tab-panel]', root).forEach(p => p.classList.toggle('hidden', p.dataset.tabPanel !== b.dataset.tab));
    }));
  });

  // ---- shop filters toggle -------------------------------------------
  $('[data-filters-toggle]')?.addEventListener('click', () => $('.filters')?.classList.toggle('on'));

  // ---- checkout -------------------------------------------------------
  const checkout = $('#checkoutForm');
  if (checkout) {
    const money = n => `${n.toFixed(2).replace('.', ',')} ${checkout.dataset.currency}`;
    const sync = () => {
      const m = $('input[name=shipping_method]:checked', checkout);
      const type = m?.dataset.type || 'office';
      $$('[data-delivery]', checkout).forEach(el => el.classList.toggle('hidden', el.dataset.delivery !== type));
      const addressLabel = $('label[for=id_address]');
      if (addressLabel) addressLabel.textContent = type === 'office' ? 'Офис на куриера (адрес или име)' : 'Улица, номер, блок, вход, етаж';
      const inv = $('#id_needs_invoice', checkout);
      $('[data-invoice-fields]', checkout)?.classList.toggle('hidden', !inv?.checked);
      if (m) {
        const ship = Number(m.dataset.cost), base = Number(checkout.dataset.base);
        $('[data-sum-shipping]').textContent = ship ? money(ship) : 'Безплатна';
        $('[data-sum-total]').textContent = money(base + ship);
      }
      const pay = $('input[name=payment_method]:checked', checkout)?.value;
      const submit = $('[data-submit-label]');
      if (submit) submit.textContent = pay === 'card' ? 'Продължи към плащане →' : 'Потвърди поръчката';
    };
    checkout.addEventListener('change', sync);
    sync();
    checkout.addEventListener('submit', () => { const b = $('button[form=checkoutForm]'); setTimeout(() => b && (b.disabled = true), 0); });
  }

  // ---- cookie notice --------------------------------------------------
  const bar = $('#cookieBar');
  try { if (bar && !localStorage.getItem('cookie_ok')) bar.classList.remove('hidden'); } catch { /* storage blocked */ }
  $('[data-cookie-ok]')?.addEventListener('click', () => { try { localStorage.setItem('cookie_ok', '1'); } catch {} bar.classList.add('hidden'); });
})();
