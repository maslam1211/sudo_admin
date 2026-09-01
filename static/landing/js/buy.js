(function () {
  'use strict';

  var cfg = window.SUDO_CHECKOUT || {};
  var form = document.getElementById('checkout-form');
  if (!form) return;

  var payBtn = document.getElementById('pay-btn');
  var stickyPayBtn = document.getElementById('sticky-pay-btn');
  var statusEl = document.getElementById('checkout-status');
  var qtyInput = document.getElementById('quantity');
  var stickyBar = document.getElementById('buy-sticky');
  var busy = false;
  var paymentSettled = false;

  /* —— Fullscreen wheel.json Lottie loader —— */
  var loaderOverlay = document.getElementById('checkout-loader');
  var loaderMount = document.getElementById('checkout-lottie-mount');
  var loaderText = document.getElementById('checkout-loader-text');
  var lottieAnim = null;
  var lottieLibPromise = null;

  function getLottieApi() {
    return window.lottie || window.bodymovin;
  }

  function loadLottieLib() {
    var existing = getLottieApi();
    if (existing) return Promise.resolve(existing);
    if (lottieLibPromise) return lottieLibPromise;
    lottieLibPromise = new Promise(function (resolve, reject) {
      var s = document.createElement('script');
      s.src = 'https://cdnjs.cloudflare.com/ajax/libs/lottie-web/5.12.2/lottie.min.js';
      s.async = true;
      s.onload = function () {
        var api = getLottieApi();
        if (api) resolve(api);
        else reject(new Error('lottie missing'));
      };
      s.onerror = function () {
        reject(new Error('lottie failed'));
      };
      document.head.appendChild(s);
    });
    return lottieLibPromise;
  }

  function showLoaderFallback() {
    if (!loaderMount) return;
    loaderMount.innerHTML = '';
    var fb = document.createElement('div');
    fb.className = 'checkout-loader__fallback';
    fb.setAttribute('aria-hidden', 'true');
    loaderMount.appendChild(fb);
  }

  function hideCheckoutLoader() {
    if (lottieAnim) {
      try { lottieAnim.destroy(); } catch (e) {}
      lottieAnim = null;
    }
    if (loaderMount) loaderMount.innerHTML = '';
    if (loaderOverlay) {
      loaderOverlay.hidden = true;
      loaderOverlay.setAttribute('aria-hidden', 'true');
      loaderOverlay.setAttribute('aria-busy', 'false');
    }
    document.body.classList.remove('checkout-loader-open');
  }

  function showCheckoutLoader(message) {
    if (!loaderOverlay || !loaderMount) return;
    if (loaderText) loaderText.textContent = message || 'Processing…';
    if (lottieAnim) {
      try { lottieAnim.destroy(); } catch (e) {}
      lottieAnim = null;
    }
    loaderMount.innerHTML = '';
    loaderOverlay.hidden = false;
    loaderOverlay.setAttribute('aria-hidden', 'false');
    loaderOverlay.setAttribute('aria-busy', 'true');
    document.body.classList.add('checkout-loader-open');

    loadLottieLib()
      .then(function (LottieApi) {
        if (!loaderOverlay || loaderOverlay.hidden) return;
        lottieAnim = LottieApi.loadAnimation({
          container: loaderMount,
          renderer: 'svg',
          loop: true,
          autoplay: true,
          path: cfg.wheelJsonUrl || '/admin/notify-sending-wheel.json',
        });
      })
      .catch(function () {
        if (!loaderOverlay || loaderOverlay.hidden) return;
        showLoaderFallback();
      });
  }

  function money(n) {
    return '₹' + Number(n).toFixed(2);
  }

  function productMeta() {
    var input = form.querySelector('input[name="selectedItem"]');
    return {
      key: (input && input.value) || cfg.productKey || 'sticker',
      price: Number(cfg.productPrice || (input && input.getAttribute('data-price')) || 199),
      name: cfg.productName || (input && input.getAttribute('data-name')) || 'SudoTag QR',
    };
  }

  function updateSummary() {
    var product = productMeta();
    var qty = Math.max(1, Math.min(20, parseInt(qtyInput.value, 10) || 1));
    qtyInput.value = String(qty);
    var subtotal = product.price * qty;
    var shipping = Number(cfg.shipping != null ? cfg.shipping : 49);
    var total = subtotal + shipping;

    var setText = function (id, value) {
      var el = document.getElementById(id);
      if (el) el.textContent = value;
    };

    setText('summary-product', product.name);
    setText('summary-unit', money(product.price));
    setText('summary-qty', String(qty));
    setText('summary-subtotal', money(subtotal));
    setText('summary-shipping', money(shipping));
    setText('summary-total', money(total));
    setText('hero-total', money(total));
    setText('sticky-total', money(total));
  }

  function setStatus(message, kind) {
    if (!statusEl) return;
    statusEl.textContent = message || '';
    statusEl.classList.toggle('is-error', kind === 'error');
    statusEl.classList.toggle('is-success', kind === 'success');
  }

  function setBusy(isBusy, loaderMessage) {
    busy = isBusy;
    [payBtn, stickyPayBtn].forEach(function (btn) {
      if (!btn) return;
      btn.disabled = isBusy;
    });
    if (payBtn) {
      var label = payBtn.querySelector('.buy-pay-btn__label');
      var spinner = payBtn.querySelector('.buy-pay-btn__spinner');
      if (label) label.textContent = isBusy ? 'Processing…' : 'Buy Now';
      if (spinner) spinner.hidden = true;
    }
    if (stickyPayBtn) {
      stickyPayBtn.textContent = isBusy ? 'Processing…' : 'Buy Now';
    }
    if (isBusy) {
      showCheckoutLoader(loaderMessage || 'Processing…');
    } else {
      hideCheckoutLoader();
    }
  }

  function fieldEl(id) {
    return document.getElementById(id);
  }

  function fieldValue(id) {
    var el = fieldEl(id);
    return el ? String(el.value || '') : '';
  }

  function clearErrors() {
    form.querySelectorAll('.field').forEach(function (field) {
      field.classList.remove('is-invalid');
    });
    form.querySelectorAll('.field-error').forEach(function (el) {
      el.hidden = true;
      el.textContent = '';
    });
  }

  function showFieldError(name, message) {
    var input = fieldEl(name) || form.querySelector('[name="' + name + '"]');
    if (input) {
      var field = input.closest('.field');
      if (field) field.classList.add('is-invalid');
    }
    var err = form.querySelector('.field-error[data-for="' + name + '"]');
    if (err) {
      err.textContent = message;
      err.hidden = false;
    }
  }

  function clientValidate() {
    clearErrors();
    var errors = {};
    var fullName = fieldValue('fullName').trim();
    var mobile = fieldValue('mobile').replace(/\D/g, '');
    if (mobile.length === 12 && mobile.indexOf('91') === 0) mobile = mobile.slice(2);
    if (mobile.length === 11 && mobile.charAt(0) === '0') mobile = mobile.slice(1);
    var email = fieldValue('email').trim();
    var houseNumber = fieldValue('houseNumber').trim();
    var street = fieldValue('street').trim();
    var city = fieldValue('city').trim();
    var state = fieldValue('state').trim();
    var pincode = fieldValue('pincode').trim();

    if (fullName.length < 2 || fullName.length > 50) {
      errors.fullName = "Please enter a valid name (2–50 characters: letters, spaces, and .'- allowed).";
    }
    if (!/^\d{10}$/.test(mobile)) {
      errors.mobile = 'Please enter a valid 10-digit mobile number';
    }
    if (email && !/^[a-zA-Z0-9._%+-]+@(?:[a-zA-Z0-9-]+\.)+[a-zA-Z]{2,}$/.test(email)) {
      errors.email = 'Please enter a valid email address.';
    }
    if (!houseNumber) errors.houseNumber = 'Please fill this required field';
    if (!street) errors.street = 'Please fill this required field';
    if (!city) errors.city = 'Please enter district/city';
    if (!state) errors.state = 'Please enter state';
    if (!/^[1-9][0-9]{5}$/.test(pincode)) {
      errors.pincode = 'Please enter a valid pincode';
    }

    Object.keys(errors).forEach(function (key) {
      showFieldError(key, errors[key]);
    });
    return Object.keys(errors).length === 0;
  }

  function collectPayload() {
    var product = productMeta();
    var mobile = fieldValue('mobile').replace(/\D/g, '');
    if (mobile.length === 12 && mobile.indexOf('91') === 0) mobile = mobile.slice(2);
    if (mobile.length === 11 && mobile.charAt(0) === '0') mobile = mobile.slice(1);
    return {
      fullName: fieldValue('fullName').trim(),
      mobile: mobile,
      email: fieldValue('email').trim(),
      houseNumber: fieldValue('houseNumber').trim(),
      street: fieldValue('street').trim(),
      postOffice: fieldValue('postOffice').trim(),
      landmark: fieldValue('landmark').trim(),
      city: fieldValue('city').trim(),
      state: fieldValue('state').trim(),
      pincode: fieldValue('pincode').trim(),
      country: fieldValue('country').trim() || 'India',
      vehicleNumber: fieldValue('vehicleNumber').trim(),
      selectedItem: product.key,
      quantity: parseInt(qtyInput.value, 10) || 1,
    };
  }

  async function postJson(url, body) {
    var res = await fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
      body: JSON.stringify(body),
      credentials: 'same-origin',
    });
    var data = {};
    try {
      data = await res.json();
    } catch (e) {
      data = {};
    }
    if (!res.ok) {
      var err = new Error(data.error || 'Request failed');
      err.payload = data;
      err.status = res.status;
      throw err;
    }
    return data;
  }

  function goFailure(message, extra) {
    extra = extra || {};
    if (!cfg.failureUrl) {
      setStatus(message, 'error');
      setBusy(false);
      return;
    }
    var params = new URLSearchParams({ reason: message || 'Payment failed' });
    if (extra.code) params.set('code', extra.code);
    if (extra.orderId) params.set('orderId', extra.orderId);
    if (extra.paymentId) params.set('paymentId', extra.paymentId);
    if (extra.amount != null) params.set('amount', String(extra.amount));
    window.location.href = cfg.failureUrl + '?' + params.toString();
  }

  function goCancelled(message, amount) {
    if (!cfg.cancelledUrl) {
      setStatus(message, 'error');
      setBusy(false);
      return;
    }
    var params = new URLSearchParams({
      reason: message || 'Payment was cancelled. No money was charged.',
    });
    if (amount != null) params.set('amount', String(amount));
    window.location.href = cfg.cancelledUrl + '?' + params.toString();
  }

  function saveReceipt(data) {
    try {
      sessionStorage.setItem('sudo_checkout_receipt', JSON.stringify(data));
    } catch (e) {}
  }

  function addressTextFromPayload(payload) {
    return [
      payload.houseNumber,
      payload.street,
      payload.landmark,
      [payload.city, payload.state].filter(Boolean).join(', '),
      payload.pincode ? 'PIN ' + payload.pincode : '',
      payload.country || 'India',
    ].filter(Boolean).join(', ');
  }

  function openRazorpay(order) {
    return new Promise(function (resolve, reject) {
      if (typeof Razorpay === 'undefined') {
        reject(new Error('Razorpay Checkout failed to load. Please refresh and try again.'));
        return;
      }

      paymentSettled = false;

      var options = {
        key: order.key || cfg.razorpayKey,
        amount: order.amountPaise,
        currency: order.currency || 'INR',
        name: 'SudoTag',
        description: 'SudoTag QR Order',
        image: cfg.logoUrl || 'https://sudotag.com/logo.png',
        order_id: order.razorpayOrderId,
        prefill: {
          name: (order.customer && order.customer.name) || '',
          contact: (order.customer && order.customer.contact) || '',
          email: (order.customer && order.customer.email) || '',
        },
        theme: {
          color: cfg.themeColor || '#E58147',
          backdrop_color: cfg.backdropColor || '#1C1C1C',
        },
        notes: {
          app_name: 'SudoTag',
          theme: 'dark',
          source: 'website',
        },
        handler: function (response) {
          paymentSettled = true;
          resolve({
            razorpay_payment_id: response.razorpay_payment_id,
            razorpay_order_id: response.razorpay_order_id || order.razorpayOrderId,
            razorpay_signature: response.razorpay_signature || '',
          });
        },
        modal: {
          ondismiss: function () {
            if (paymentSettled) return;
            paymentSettled = true;
            reject(Object.assign(
              new Error('Payment was cancelled. You can try again when ready.'),
              { cancelled: true }
            ));
          },
        },
      };

      var rzp = new Razorpay(options);
      rzp.on('payment.failed', function (resp) {
        if (paymentSettled) return;
        paymentSettled = true;
        var msg =
          (resp && resp.error && (resp.error.description || resp.error.reason)) ||
          'Payment failed. Please try again.';
        var code = resp && resp.error && (resp.error.code || resp.error.step);
        reject(Object.assign(new Error(msg), { fatalPayment: true, code: code || '' }));
      });
      rzp.open();
    });
  }

  /* Quantity controls */
  document.querySelectorAll('.qty-btn').forEach(function (btn) {
    btn.addEventListener('click', function () {
      var delta = parseInt(btn.getAttribute('data-qty'), 10) || 0;
      var next = (parseInt(qtyInput.value, 10) || 1) + delta;
      qtyInput.value = String(Math.max(1, Math.min(20, next)));
      updateSummary();
    });
  });
  qtyInput.addEventListener('change', updateSummary);
  qtyInput.addEventListener('input', updateSummary);

  /* Smooth jump to checkout */
  var jump = document.getElementById('buy-now-jump');
  if (jump) {
    jump.addEventListener('click', function (e) {
      var target = document.getElementById('checkout');
      if (!target) return;
      e.preventDefault();
      target.scrollIntoView({ behavior: 'smooth', block: 'start' });
      var first = form.querySelector('#fullName');
      if (first) setTimeout(function () { first.focus({ preventScroll: true }); }, 400);
    });
  }

  /* Sticky bar visibility on mobile */
  function updateSticky() {
    if (!stickyBar || window.matchMedia('(min-width: 960px)').matches) {
      if (stickyBar) stickyBar.hidden = true;
      return;
    }
    var summary = document.querySelector('.summary-card');
    if (!summary) {
      stickyBar.hidden = false;
      return;
    }
    var rect = summary.getBoundingClientRect();
    stickyBar.hidden = rect.top < window.innerHeight && rect.bottom > 0;
  }
  window.addEventListener('scroll', updateSticky, { passive: true });
  window.addEventListener('resize', updateSticky);

  /* Gallery thumbs */
  var mainImg = document.getElementById('product-main-img');
  var zoomTrigger = document.getElementById('product-zoom-trigger');

  /* Zoomable lightbox */
  (function initLightbox() {
    var lightbox = document.getElementById('zoom-lightbox');
    var stage = document.getElementById('zoom-stage');
    var img = document.getElementById('zoom-img');
    var resetBtn = document.getElementById('zoom-reset');
    if (!lightbox || !stage || !img || !zoomTrigger) return;

    var scale = 1;
    var tx = 0;
    var ty = 0;
    var dragging = false;
    var startX = 0;
    var startY = 0;
    var originTx = 0;
    var originTy = 0;
    var pointers = new Map();
    var pinchStartDist = 0;
    var pinchStartScale = 1;

    function applyTransform() {
      img.style.transform = 'translate(' + tx + 'px,' + ty + 'px) scale(' + scale + ')';
      if (resetBtn) resetBtn.textContent = Math.round(scale * 100) + '%';
    }

    function setScale(next, cx, cy) {
      var prev = scale;
      scale = Math.max(1, Math.min(5, next));
      if (scale === 1) {
        tx = 0;
        ty = 0;
      } else if (typeof cx === 'number' && typeof cy === 'number' && prev > 0) {
        var rect = stage.getBoundingClientRect();
        var ox = cx - rect.left - rect.width / 2;
        var oy = cy - rect.top - rect.height / 2;
        tx = ox - ((ox - tx) * scale) / prev;
        ty = oy - ((oy - ty) * scale) / prev;
      }
      applyTransform();
    }

    function openLightbox(src) {
      img.src = src;
      scale = 1;
      tx = 0;
      ty = 0;
      applyTransform();
      lightbox.hidden = false;
      lightbox.setAttribute('aria-hidden', 'false');
      document.body.style.overflow = 'hidden';
    }

    function closeLightbox() {
      lightbox.hidden = true;
      lightbox.setAttribute('aria-hidden', 'true');
      document.body.style.overflow = '';
    }

    zoomTrigger.addEventListener('click', function () {
      openLightbox(zoomTrigger.getAttribute('data-full-src') || mainImg.src);
    });

    lightbox.querySelectorAll('[data-zoom-close]').forEach(function (el) {
      el.addEventListener('click', closeLightbox);
    });

    document.getElementById('zoom-in').addEventListener('click', function () {
      setScale(scale + 0.35);
    });
    document.getElementById('zoom-out').addEventListener('click', function () {
      setScale(scale - 0.35);
    });
    resetBtn.addEventListener('click', function () {
      setScale(1);
    });

    stage.addEventListener('wheel', function (e) {
      e.preventDefault();
      var delta = e.deltaY > 0 ? -0.2 : 0.2;
      setScale(scale + delta, e.clientX, e.clientY);
    }, { passive: false });

    stage.addEventListener('pointerdown', function (e) {
      stage.setPointerCapture(e.pointerId);
      pointers.set(e.pointerId, { x: e.clientX, y: e.clientY });
      if (pointers.size === 1) {
        dragging = true;
        stage.classList.add('is-dragging');
        startX = e.clientX;
        startY = e.clientY;
        originTx = tx;
        originTy = ty;
      } else if (pointers.size === 2) {
        dragging = false;
        var pts = Array.from(pointers.values());
        var dx = pts[0].x - pts[1].x;
        var dy = pts[0].y - pts[1].y;
        pinchStartDist = Math.hypot(dx, dy) || 1;
        pinchStartScale = scale;
      }
    });

    stage.addEventListener('pointermove', function (e) {
      if (!pointers.has(e.pointerId)) return;
      pointers.set(e.pointerId, { x: e.clientX, y: e.clientY });
      if (pointers.size === 2) {
        var pts = Array.from(pointers.values());
        var dx = pts[0].x - pts[1].x;
        var dy = pts[0].y - pts[1].y;
        var dist = Math.hypot(dx, dy) || 1;
        var midX = (pts[0].x + pts[1].x) / 2;
        var midY = (pts[0].y + pts[1].y) / 2;
        setScale(pinchStartScale * (dist / pinchStartDist), midX, midY);
        return;
      }
      if (!dragging || scale <= 1) return;
      tx = originTx + (e.clientX - startX);
      ty = originTy + (e.clientY - startY);
      applyTransform();
    });

    function endPointer(e) {
      pointers.delete(e.pointerId);
      if (pointers.size < 2) {
        pinchStartDist = 0;
      }
      if (pointers.size === 0) {
        dragging = false;
        stage.classList.remove('is-dragging');
      }
    }
    stage.addEventListener('pointerup', endPointer);
    stage.addEventListener('pointercancel', endPointer);

    document.addEventListener('keydown', function (e) {
      if (e.key === 'Escape' && !lightbox.hidden) closeLightbox();
    });
  })();

  form.addEventListener('submit', async function (event) {
    event.preventDefault();
    if (busy) return;
    if (!clientValidate()) {
      setStatus('Please fill all required fields to continue.', 'error');
      var firstInvalid = form.querySelector('.field.is-invalid');
      if (firstInvalid) firstInvalid.scrollIntoView({ behavior: 'smooth', block: 'center' });
      return;
    }

    setBusy(true, 'Creating your order…');
    setStatus('Creating your order…');

    var payload = collectPayload();
    var createRes = null;

    try {
      createRes = await postJson(cfg.createOrderUrl, payload);
      if (!createRes.success || !createRes.razorpayOrderId) {
        throw new Error(createRes.error || 'Could not create payment order.');
      }

      setStatus('Opening secure payment…', 'success');
      showCheckoutLoader('Opening secure payment…');
      // Let the wheel show briefly, then hand off to Razorpay UI
      await new Promise(function (r) { setTimeout(r, 350); });
      hideCheckoutLoader();

      var payment = await openRazorpay(createRes);

      setBusy(true, 'Verifying payment…');
      setStatus('Verifying payment…');
      var verifyRes = await postJson(cfg.verifyPaymentUrl, {
        orderId: createRes.orderId,
        razorpayOrderId: payment.razorpay_order_id || createRes.razorpayOrderId,
        razorpayPaymentId: payment.razorpay_payment_id,
        razorpaySignature: payment.razorpay_signature || '',
      });

      if (!verifyRes.verified && !verifyRes.success) {
        throw Object.assign(new Error(verifyRes.error || 'Payment verification failed.'), {
          fatalPayment: true,
          orderId: createRes.orderId,
          paymentId: payment.razorpay_payment_id,
          amount: createRes.amount,
        });
      }

      showCheckoutLoader('Payment confirmed…');

      var receipt = {
        orderId: verifyRes.orderId || createRes.orderId || '',
        paymentId: verifyRes.paymentId || payment.razorpay_payment_id || '',
        razorpayOrderId: payment.razorpay_order_id || createRes.razorpayOrderId || '',
        amount: verifyRes.amount != null ? verifyRes.amount : createRes.amount,
        productName: (createRes.product && createRes.product.name) || verifyRes.productName || cfg.productName,
        quantity: (createRes.product && createRes.product.quantity) || payload.quantity || 1,
        fullName: payload.fullName,
        mobile: payload.mobile,
        email: payload.email,
        addressText: addressTextFromPayload(payload),
      };
      saveReceipt(receipt);

      var params = new URLSearchParams({
        orderId: receipt.orderId,
        paymentId: receipt.paymentId,
        razorpayOrderId: receipt.razorpayOrderId,
        amount: String(receipt.amount != null ? receipt.amount : ''),
        product: receipt.productName || '',
        quantity: String(receipt.quantity || 1),
        name: receipt.fullName || '',
        mobile: receipt.mobile || '',
        email: receipt.email || '',
        address: receipt.addressText || '',
      });
      window.location.href = cfg.successUrl + '?' + params.toString();
    } catch (err) {
      hideCheckoutLoader();
      if (err.payload && err.payload.fields) {
        clearErrors();
        Object.keys(err.payload.fields).forEach(function (key) {
          showFieldError(key, err.payload.fields[key]);
        });
        setStatus(err.message || 'Please fix the highlighted fields.', 'error');
        setBusy(false);
        return;
      }

      var msg = err.message || 'Something went wrong. Please try again.';
      var amount = createRes && createRes.amount;

      if (err.cancelled) {
        goCancelled(msg, amount);
        return;
      }

      var isFatal = err.fatalPayment || /verif/i.test(msg) || (/failed/i.test(msg) && !/cancel/i.test(msg));
      if (isFatal && cfg.failureUrl) {
        goFailure(msg, {
          code: err.code || '',
          orderId: err.orderId || (createRes && createRes.orderId) || '',
          paymentId: err.paymentId || '',
          amount: err.amount != null ? err.amount : amount,
        });
        return;
      }

      setStatus(msg, 'error');
      setBusy(false);
    }
  });

  updateSummary();
  updateSticky();
})();
