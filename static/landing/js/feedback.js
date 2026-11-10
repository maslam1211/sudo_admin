/**
 * Landing feedback: load approved reviews + submit pending feedback.
 */
(function () {
  const section = document.getElementById('testimonials');
  if (!section) return;

  const apiUrl = section.dataset.feedbackApi || '';
  const submitUrl = section.dataset.submitUrl || '';
  const defaultAvatar = section.dataset.defaultAvatar || '';
  const slidesEl = document.getElementById('feedback-slides');
  const swiperEl = document.getElementById('feedback-swiper');
  const loadingEl = document.getElementById('feedback-loading');
  const emptyEl = document.getElementById('feedback-empty');
  const errorEl = document.getElementById('feedback-error');
  const form = document.getElementById('landing-feedback-form');
  const ratingInput = document.getElementById('fb-rating');
  const alertEl = document.getElementById('fb-form-alert');
  const submitBtn = document.getElementById('fb-submit-btn');
  const starButtons = section.querySelectorAll('.feedback-star');

  let swiperInstance = null;
  let submitting = false;

  function csrfToken() {
    const input = form && form.querySelector('[name=csrfmiddlewaretoken]');
    if (input && input.value) return input.value;
    const match = document.cookie.match(/(?:^|;\s*)csrftoken=([^;]+)/);
    return match ? decodeURIComponent(match[1]) : '';
  }

  function escapeHtml(str) {
    return String(str || '')
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  }

  function starsHtml(rating) {
    const r = Math.max(0, Math.min(5, Number(rating) || 0));
    let html = '';
    for (let i = 1; i <= 5; i += 1) {
      html += i <= r
        ? '<i class="bi bi-star-fill"></i>'
        : '<i class="bi bi-star"></i>';
    }
    return html;
  }

  /* Rating shown as phone signal bars (1–5) */
  function barsHtml(rating) {
    let html = '<span class="st-bars" aria-label="' + rating + ' out of 5">';
    for (let i = 1; i <= 5; i += 1) html += i <= rating ? '<i class="is-on"></i>' : '<i></i>';
    return html + '<b class="st-mono">' + rating + '/5</b></span>';
  }

  function setVisible(el, show) {
    if (!el) return;
    el.hidden = !show;
  }

  function destroySwiper() {
    if (swiperInstance && typeof swiperInstance.destroy === 'function') {
      try { swiperInstance.destroy(true, true); } catch (_) { /* ignore */ }
    }
    swiperInstance = null;
  }

  function initSwiper() {
    if (!swiperEl || typeof Swiper === 'undefined') return;
    destroySwiper();
    let config = {};
    const cfgNode = swiperEl.querySelector('.swiper-config');
    if (cfgNode) {
      try { config = JSON.parse(cfgNode.textContent); } catch (_) { config = {}; }
    }
    config.loop = (slidesEl && slidesEl.children.length > 1);
    swiperInstance = new Swiper(swiperEl, config);
  }

  function renderFeedbacks(list) {
    if (!slidesEl) return;
    if (!list || !list.length) {
      slidesEl.innerHTML = '';
      document.dispatchEvent(new CustomEvent('st:feedback', { detail: [] }));
      setVisible(swiperEl, false);
      setVisible(emptyEl, true);
      setVisible(errorEl, false);
      setVisible(loadingEl, false);
      destroySwiper();
      return;
    }

    slidesEl.innerHTML = list.map((fb) => {
      const name = escapeHtml(fb.name || 'Customer');
      const message = escapeHtml(fb.feedback || '');
      const date = escapeHtml(fb.createdAt || '');
      const img = escapeHtml(fb.profileImage || defaultAvatar);
      const rating = Math.max(0, Math.min(5, Number(fb.rating) || 0));
      return `
        <div class="swiper-slide">
          <article class="st-msg" data-rating="${rating}">
            <header class="st-msg__top st-mono"><span class="st-msg__rx"><i></i>Signal received</span>${date ? `<time>${date}</time>` : ''}</header>
            ${barsHtml(rating)}
            <p class="st-msg__text">${message}</p>
            <footer class="st-msg__from">
              <img src="${img}" alt="" loading="lazy" width="38" height="38">
              <span><b>${name}</b><small><i class="bi bi-shield-check" aria-hidden="true"></i>Checked by SudoTag</small></span>
            </footer>
          </article>
        </div>`;
    }).join('');
    document.dispatchEvent(new CustomEvent('st:feedback', { detail: list }));

    setVisible(emptyEl, false);
    setVisible(errorEl, false);
    setVisible(loadingEl, false);
    setVisible(swiperEl, true);
    initSwiper();
  }

  async function refreshApproved() {
    if (!apiUrl) return;
    setVisible(loadingEl, true);
    setVisible(errorEl, false);
    try {
      const res = await fetch(apiUrl, { headers: { Accept: 'application/json' } });
      const data = await res.json();
      if (!res.ok || data.status === 'error') {
        throw new Error(data.message || 'Load failed');
      }
      renderFeedbacks(data.feedbacks || []);
    } catch (_) {
      // Keep server-rendered slides if present; only show error when empty.
      const hasSlides = slidesEl && slidesEl.children.length > 0;
      setVisible(loadingEl, false);
      if (!hasSlides) {
        setVisible(errorEl, true);
        setVisible(emptyEl, false);
        setVisible(swiperEl, false);
      }
    }
  }

  function paintStars(value) {
    starButtons.forEach((btn) => {
      const v = Number(btn.dataset.value);
      const icon = btn.querySelector('i');
      const on = v <= value;
      btn.classList.toggle('is-active', on);
      if (icon) {
        icon.className = on ? 'bi bi-star-fill' : 'bi bi-star';
      }
    });
  }

  starButtons.forEach((btn) => {
    btn.addEventListener('click', () => {
      const value = Number(btn.dataset.value) || 0;
      if (ratingInput) ratingInput.value = String(value);
      paintStars(value);
    });
  });

  function showAlert(message, type) {
    if (!alertEl) return;
    alertEl.hidden = false;
    alertEl.className = 'feedback-alert feedback-alert--' + type;
    alertEl.textContent = message;
  }

  if (form) {
    form.addEventListener('submit', async (e) => {
      e.preventDefault();
      if (submitting) return;

      const name = (form.name.value || '').trim();
      const email = (form.email.value || '').trim();
      const feedback = (form.feedback.value || '').trim();
      const rating = Number(ratingInput && ratingInput.value);

      if (!name) return showAlert('Name is required.', 'error');
      if (!rating || rating < 1 || rating > 5) return showAlert('Please select a rating.', 'error');
      if (!feedback) return showAlert('Feedback message is required.', 'error');

      submitting = true;
      if (submitBtn) {
        submitBtn.disabled = true;
        submitBtn.classList.add('is-loading');
      }

      try {
        const res = await fetch(submitUrl, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            'X-CSRFToken': csrfToken(),
            'X-Requested-With': 'XMLHttpRequest',
          },
          body: JSON.stringify({ name, email, rating, feedback }),
        });
        const data = await res.json();
        if (!res.ok || data.status !== 'success') {
          throw new Error(data.message || 'Submission failed');
        }
        form.reset();
        if (ratingInput) ratingInput.value = '';
        paintStars(0);
        showAlert(
          data.message ||
            'Thank you! Your feedback has been submitted successfully and will be reviewed.',
          'success'
        );
      } catch (err) {
        showAlert(err.message || 'Could not submit feedback. Please try again.', 'error');
      } finally {
        submitting = false;
        if (submitBtn) {
          submitBtn.disabled = false;
          submitBtn.classList.remove('is-loading');
        }
      }
    });
  }

  // Soft realtime: refresh approved list periodically (and once after load).
  // If server already rendered slides, keep them visible until refresh completes.
  const boot = () => {
    if (slidesEl && slidesEl.children.length > 0) {
      setVisible(emptyEl, false);
      setVisible(swiperEl, true);
      initSwiper();
    } else {
      setVisible(loadingEl, true);
    }
    refreshApproved();
    setInterval(refreshApproved, 45000);
  };

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', boot);
  } else {
    boot();
  }
})();
