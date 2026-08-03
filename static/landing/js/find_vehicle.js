/**
 * Landing: One Scan QR / plate flow.
 * Active QR → notify; inactive QR → activate; plate → notify when found.
 */
(function () {
  var card = document.getElementById('findVehicleCard');
  if (!card) return;

  var lookupUrl = card.getAttribute('data-lookup-url') || '/admin/api/public-lookup-vehicle/';
  var statusEl = document.getElementById('findVehicleStatus');
  var video = document.getElementById('findVehicleVideo');
  var canvas = document.getElementById('findVehicleCanvas');
  var snapImg = document.getElementById('findVehicleSnap');
  var previewWrap = document.getElementById('findVehiclePreviewWrap');
  var previewFrame = previewWrap
    ? previewWrap.querySelector('.find-vehicle-preview__frame')
    : null;
  var guide = document.getElementById('findVehicleGuide');
  var scanBtn = document.getElementById('findVehicleScanBtn');
  var plateScanBtn = document.getElementById('findVehiclePlateScanBtn');
  var stopBtn = document.getElementById('findVehicleStopBtn');
  var captureBtn = document.getElementById('findVehicleCaptureBtn');
  var fileInput = document.getElementById('findVehicleQrFile');
  var plateFileInput = document.getElementById('findVehiclePlateFile');
  var qrInput = document.getElementById('findVehicleQrInput');
  var qrGo = document.getElementById('findVehicleQrGo');
  var plateInput = document.getElementById('findVehiclePlateInput');
  var plateGo = document.getElementById('findVehiclePlateGo');
  var sheet = document.getElementById('findVehicleCameraSheet');
  var sheetCamera = document.getElementById('findVehicleSheetCamera');
  var sheetGallery = document.getElementById('findVehicleSheetGallery');
  var sheetTitle = document.getElementById('findVehicleSheetTitle');

  var mediaStream = null;
  var scanTimer = null;
  var busy = false;
  var detecting = false;
  var activeMode = 'qr'; // 'qr' | 'plate'
  var pendingSheetMode = 'qr';
  var jsQrLoader = null;
  var tesseractLoader = null;
  var tesseractWorker = null;
  var plateOcrBusy = false;
  var lookupLoaderAnim = null;
  var lookupLottiePromise = null;
  var RESET_KEY = 'sudoFindVehicleReset';
  var wheelUrl =
    card.getAttribute('data-wheel-url') ||
    window.__SUDO_WHEEL_URL ||
    '/admin/notify-sending-wheel.json';
  var lottieUrl =
    card.getAttribute('data-lottie-url') ||
    window.__SUDO_LOTTIE_URL ||
    '';

  var CAMERA_OPTS = {
    audio: false,
    video: {
      facingMode: { ideal: 'environment' },
      width: { ideal: 1280 },
      height: { ideal: 720 },
    },
  };

  function csrfToken() {
    var m = document.cookie.match(/(?:^|;\s*)csrftoken=([^;]+)/);
    if (m) return decodeURIComponent(m[1]);
    var el = document.querySelector('[name=csrfmiddlewaretoken]');
    return el ? el.value : '';
  }

  function setStatus(msg, kind) {
    if (!statusEl) return;
    statusEl.textContent = msg || '';
    statusEl.classList.remove('is-error', 'is-ok');
    if (kind === 'error') statusEl.classList.add('is-error');
    if (kind === 'ok') statusEl.classList.add('is-ok');
  }

  function stopCamera() {
    if (scanTimer) {
      clearInterval(scanTimer);
      scanTimer = null;
    }
    detecting = false;
    if (mediaStream) {
      mediaStream.getTracks().forEach(function (t) {
        try {
          t.stop();
        } catch (e) {}
      });
      mediaStream = null;
    }
    if (video) {
      try {
        video.pause();
      } catch (e) {}
      video.srcObject = null;
      video.hidden = true;
    }
    if (captureBtn) captureBtn.hidden = true;
    if (stopBtn) stopBtn.hidden = true;
    if (previewWrap && (!snapImg || snapImg.hidden)) {
      previewWrap.hidden = true;
    }
  }

  function clearSnap() {
    if (snapImg) {
      snapImg.removeAttribute('src');
      snapImg.hidden = true;
    }
  }

  function getCookieCsrfHeaders() {
    var token = csrfToken();
    var headers = {
      'Content-Type': 'application/json',
      'X-Requested-With': 'XMLHttpRequest',
    };
    if (token) headers['X-CSRFToken'] = token;
    return headers;
  }

  function markNeedsReset() {
    try {
      sessionStorage.setItem(RESET_KEY, '1');
    } catch (e) {}
  }

  function consumeNeedsReset() {
    try {
      if (sessionStorage.getItem(RESET_KEY) === '1') {
        sessionStorage.removeItem(RESET_KEY);
        return true;
      }
    } catch (e) {}
    return false;
  }

  function ensureLottieApi() {
    var api = window.lottie || window.bodymovin;
    if (api) return Promise.resolve(api);
    if (lookupLottiePromise) return lookupLottiePromise;
    lookupLottiePromise = new Promise(function (resolve, reject) {
      var src =
        lottieUrl ||
        'https://cdnjs.cloudflare.com/ajax/libs/lottie-web/5.12.2/lottie.min.js';
      var s = document.createElement('script');
      s.src = src;
      s.async = true;
      s.onload = function () {
        var a = window.lottie || window.bodymovin;
        if (a) resolve(a);
        else reject(new Error('lottie missing'));
      };
      s.onerror = function () {
        lookupLottiePromise = null;
        reject(new Error('lottie failed'));
      };
      document.head.appendChild(s);
    });
    return lookupLottiePromise;
  }

  function getLookupLoaderEl() {
    var el = document.getElementById('findVehicleLookupLoader');
    if (el) return el;
    el = document.createElement('div');
    el.id = 'findVehicleLookupLoader';
    el.className = 'find-vehicle-lookup-loader';
    el.setAttribute('hidden', '');
    el.setAttribute('aria-hidden', 'true');
    el.setAttribute('aria-busy', 'false');
    el.setAttribute('role', 'status');
    el.innerHTML =
      '<div class="find-vehicle-lookup-loader__inner">' +
      '<div class="find-vehicle-lookup-loader__lottie" id="findVehicleLookupLottie" aria-hidden="true"></div>' +
      '<p class="find-vehicle-lookup-loader__text" id="findVehicleLookupText">Finding vehicle…</p>' +
      '</div>';
    document.body.appendChild(el);
    return el;
  }

  function hideLookupLoader() {
    var el = document.getElementById('findVehicleLookupLoader');
    if (lookupLoaderAnim) {
      try {
        lookupLoaderAnim.destroy();
      } catch (e) {}
      lookupLoaderAnim = null;
    }
    if (el) {
      var mount = document.getElementById('findVehicleLookupLottie');
      if (mount) mount.innerHTML = '';
      el.hidden = true;
      el.setAttribute('aria-hidden', 'true');
      el.setAttribute('aria-busy', 'false');
    }
    document.body.classList.remove('find-vehicle-lookup-open');
  }

  function showLookupLoader(message) {
    var el = getLookupLoaderEl();
    var text = document.getElementById('findVehicleLookupText');
    var mount = document.getElementById('findVehicleLookupLottie');
    if (text) text.textContent = message || 'Finding vehicle…';
    el.hidden = false;
    el.setAttribute('aria-hidden', 'false');
    el.setAttribute('aria-busy', 'true');
    document.body.classList.add('find-vehicle-lookup-open');

    if (lookupLoaderAnim) return;
    ensureLottieApi()
      .then(function (api) {
        if (!mount || el.hidden) return;
        mount.innerHTML = '';
        lookupLoaderAnim = api.loadAnimation({
          container: mount,
          renderer: 'svg',
          loop: true,
          autoplay: true,
          path: wheelUrl,
        });
      })
      .catch(function () {
        /* Text-only fallback — same black overlay still shows */
      });
  }

  function selectTab(name) {
    var mode = name === 'plate' ? 'plate' : 'qr';
    setStageMode(mode);
    card.querySelectorAll('.find-vehicle-tab').forEach(function (t) {
      var on = t.getAttribute('data-tab') === mode;
      t.classList.toggle('is-active', on);
      t.setAttribute('aria-selected', on ? 'true' : 'false');
    });
    card.querySelectorAll('.find-vehicle-panel').forEach(function (panel) {
      var on = panel.getAttribute('data-panel') === mode;
      panel.hidden = !on;
      panel.classList.toggle('is-active', on);
    });
  }

  function resetFindVehicleState() {
    stopCamera();
    clearSnap();
    closeSheet();
    hideLookupLoader();
    busy = false;
    plateOcrBusy = false;
    detecting = false;
    if (previewWrap) previewWrap.hidden = true;
    if (captureBtn) captureBtn.hidden = true;
    if (stopBtn) stopBtn.hidden = true;
    if (fileInput) fileInput.value = '';
    if (plateFileInput) plateFileInput.value = '';
    if (qrInput) qrInput.value = '';
    if (plateInput) plateInput.value = '';
    setStatus('');
    selectTab('qr');
  }

  function lookup(payload) {
    if (busy) return Promise.resolve();
    busy = true;
    showLookupLoader('Finding vehicle…');
    setStatus('Looking up vehicle…');
    return fetch(lookupUrl, {
      method: 'POST',
      credentials: 'same-origin',
      headers: getCookieCsrfHeaders(),
      body: JSON.stringify(payload),
    })
      .then(function (res) {
        return res.json().then(function (data) {
          return { ok: res.ok, data: data || {} };
        });
      })
      .then(function (res) {
        var data = res.data || {};
        if (data.status === 'success') {
          var goActivate =
            data.next === 'activate' ||
            data.activated === false ||
            data.isAssigned === false;
          var target =
            (goActivate && (data.activate_url || data.redirect_url)) ||
            data.redirect_url ||
            data.notify_url ||
            data.activate_url ||
            '';
          if (target) {
            markNeedsReset();
            if (goActivate) {
              setStatus('QR not activated — opening activation…', 'ok');
              showLookupLoader('Opening activation…');
            } else {
              setStatus('Opening notify screen…', 'ok');
              showLookupLoader('Opening notify…');
            }
            stopCamera();
            window.location.assign(target);
            return;
          }
        }
        busy = false;
        hideLookupLoader();
        setStatus(
          data.message || 'Could not find that vehicle. Try again.',
          'error'
        );
      })
      .catch(function () {
        busy = false;
        hideLookupLoader();
        setStatus('Network error. Please try again.', 'error');
      });
  }

  function ensureJsQR() {
    if (typeof window.jsQR === 'function') {
      return Promise.resolve(window.jsQR);
    }
    if (jsQrLoader) return jsQrLoader;
    jsQrLoader = new Promise(function (resolve, reject) {
      var s = document.createElement('script');
      s.src = 'https://cdn.jsdelivr.net/npm/jsqr@1.4.0/dist/jsQR.min.js';
      s.async = true;
      s.onload = function () {
        if (typeof window.jsQR === 'function') resolve(window.jsQR);
        else reject(new Error('jsQR missing'));
      };
      s.onerror = function () {
        jsQrLoader = null;
        reject(new Error('jsQR load failed'));
      };
      document.head.appendChild(s);
    });
    return jsQrLoader;
  }

  function ensureTesseract() {
    if (window.Tesseract && typeof window.Tesseract.createWorker === 'function') {
      return Promise.resolve(window.Tesseract);
    }
    if (tesseractLoader) return tesseractLoader;
    function loadFrom(src) {
      return new Promise(function (resolve, reject) {
        var s = document.createElement('script');
        s.src = src;
        s.async = true;
        s.onload = function () {
          if (window.Tesseract && typeof window.Tesseract.createWorker === 'function') {
            resolve(window.Tesseract);
          } else {
            reject(new Error('Tesseract missing'));
          }
        };
        s.onerror = function () {
          reject(new Error('Tesseract load failed'));
        };
        document.head.appendChild(s);
      });
    }
    tesseractLoader = loadFrom(
      'https://cdn.jsdelivr.net/npm/tesseract.js@5.1.1/dist/tesseract.min.js'
    ).catch(function () {
      return loadFrom(
        'https://unpkg.com/tesseract.js@5.1.1/dist/tesseract.min.js'
      );
    }).catch(function (err) {
      tesseractLoader = null;
      throw err;
    });
    return tesseractLoader;
  }

  function getPlateOcrWorker() {
    return ensureTesseract().then(function (Tesseract) {
      if (tesseractWorker) return tesseractWorker;
      return Tesseract.createWorker('eng', 1, {
        logger: function () {},
      }).then(function (worker) {
        return worker
          .setParameters({
            tessedit_char_whitelist: 'ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789',
            preserve_interword_spaces: '1',
            tessedit_pageseg_mode: '7',
          })
          .then(function () {
            tesseractWorker = worker;
            return worker;
          });
      });
    });
  }

  function normalizePlateText(raw) {
    return String(raw || '')
      .toUpperCase()
      .replace(/[^A-Z0-9]/g, '');
  }

  function isLikelyIndianPlate(plate) {
    var p = normalizePlateText(plate);
    if (p.length < 7 || p.length > 12) return false;
    // Standard: KL10AY2121 / MH02AB1234
    if (/^[A-Z]{2}\d{1,2}[A-Z]{1,3}\d{1,4}$/.test(p)) return true;
    // Bharat series: 22BH1234AA
    if (/^\d{2}BH\d{4}[A-Z]{1,2}$/.test(p)) return true;
    return false;
  }

  function plateScore(plate) {
    var p = normalizePlateText(plate);
    var score = p.length;
    if (/^[A-Z]{2}\d{2}[A-Z]{1,3}\d{4}$/.test(p)) score += 20;
    else if (/^[A-Z]{2}\d{1,2}[A-Z]{1,3}\d{1,4}$/.test(p)) score += 12;
    if (/^\d{2}BH\d{4}[A-Z]{1,2}$/.test(p)) score += 18;
    return score;
  }

  function ocrConfusionVariants(plate) {
    var base = normalizePlateText(plate);
    var out = [base];
    var swaps = [
      [/O/g, '0'],
      [/0/g, 'O'],
      [/I/g, '1'],
      [/1/g, 'I'],
      [/S/g, '5'],
      [/5/g, 'S'],
      [/B/g, '8'],
      [/8/g, 'B'],
      [/Z/g, '2'],
      [/2/g, 'Z'],
      [/G/g, '6'],
      [/6/g, 'G'],
    ];
    swaps.forEach(function (pair) {
      var v = base.replace(pair[0], pair[1]);
      if (v !== base) out.push(v);
    });
    // Position-aware: letters in state code, digits in district
    if (base.length >= 8) {
      var fixed = base.split('');
      // positions 2-3 often digits (KL10…)
      if (fixed[2] === 'O') fixed[2] = '0';
      if (fixed[3] === 'O') fixed[3] = '0';
      if (fixed[2] === 'I') fixed[2] = '1';
      if (fixed[3] === 'I') fixed[3] = '1';
      out.push(fixed.join(''));
    }
    return out;
  }

  function extractPlateCandidates(ocrText) {
    var upper = String(ocrText || '').toUpperCase();
    var compact = upper.replace(/[^A-Z0-9]/g, '');
    var spaced = upper.replace(/[^A-Z0-9\s]/g, ' ');
    var found = {};
    var patterns = [
      /[A-Z]{2}\s*\d{1,2}\s*[A-Z]{1,3}\s*\d{1,4}/g,
      /\d{2}\s*BH\s*\d{4}\s*[A-Z]{1,2}/g,
      /[A-Z]{2}\d{1,2}[A-Z]{1,3}\d{1,4}/g,
      /\d{2}BH\d{4}[A-Z]{1,2}/g,
    ];

    function add(raw) {
      ocrConfusionVariants(raw).forEach(function (v) {
        if (isLikelyIndianPlate(v)) found[normalizePlateText(v)] = true;
      });
    }

    patterns.forEach(function (re) {
      var m;
      var src = re.source.indexOf('\\s') >= 0 ? spaced : compact;
      re.lastIndex = 0;
      while ((m = re.exec(src)) !== null) add(m[0]);
    });

    if (!Object.keys(found).length && compact.length >= 7 && compact.length <= 120) {
      for (var len = 12; len >= 7; len--) {
        for (var i = 0; i + len <= compact.length; i++) {
          add(compact.slice(i, i + len));
        }
      }
    }

    return Object.keys(found).sort(function (a, b) {
      return plateScore(b) - plateScore(a);
    });
  }

  function drawSourceToCanvas(source) {
    return new Promise(function (resolve, reject) {
      function fromDrawable(drawable) {
        var w =
          drawable.naturalWidth ||
          drawable.videoWidth ||
          drawable.width ||
          0;
        var h =
          drawable.naturalHeight ||
          drawable.videoHeight ||
          drawable.height ||
          0;
        if (!w || !h) {
          reject(new Error('empty-image'));
          return;
        }
        var c = document.createElement('canvas');
        c.width = w;
        c.height = h;
        var ctx = c.getContext('2d', { willReadFrequently: true });
        if (!ctx) {
          reject(new Error('no-ctx'));
          return;
        }
        ctx.drawImage(drawable, 0, 0, w, h);
        resolve(c);
      }

      if (!source) {
        reject(new Error('no-source'));
        return;
      }
      if (source instanceof HTMLCanvasElement) {
        resolve(source);
        return;
      }
      if (typeof source === 'string') {
        var img = new Image();
        img.onload = function () {
          fromDrawable(img);
        };
        img.onerror = function () {
          reject(new Error('image'));
        };
        img.crossOrigin = 'anonymous';
        img.src = source;
        return;
      }
      if (
        (typeof Blob !== 'undefined' && source instanceof Blob) ||
        (typeof File !== 'undefined' && source instanceof File)
      ) {
        if (typeof createImageBitmap === 'function') {
          createImageBitmap(source)
            .then(function (bmp) {
              fromDrawable(bmp);
              if (bmp.close) {
                try {
                  bmp.close();
                } catch (e) {}
              }
            })
            .catch(function () {
              var url = URL.createObjectURL(source);
              var im = new Image();
              im.onload = function () {
                URL.revokeObjectURL(url);
                fromDrawable(im);
              };
              im.onerror = function () {
                URL.revokeObjectURL(url);
                reject(new Error('image'));
              };
              im.src = url;
            });
          return;
        }
        var url2 = URL.createObjectURL(source);
        var im2 = new Image();
        im2.onload = function () {
          URL.revokeObjectURL(url2);
          fromDrawable(im2);
        };
        im2.onerror = function () {
          URL.revokeObjectURL(url2);
          reject(new Error('image'));
        };
        im2.src = url2;
        return;
      }
      fromDrawable(source);
    });
  }

  function preprocessPlateCanvas(srcCanvas, cropBand) {
    var w = srcCanvas.width;
    var h = srcCanvas.height;
    var sx = 0;
    var sy = 0;
    var sw = w;
    var sh = h;
    if (cropBand) {
      // Align with on-screen plate guide (inset ~32% / 8%)
      sx = Math.floor(w * 0.06);
      sy = Math.floor(h * 0.28);
      sw = Math.max(1, Math.floor(w * 0.88));
      sh = Math.max(1, Math.floor(h * 0.4));
    }
    var scale = sw < 700 ? 3 : sw < 1100 ? 2 : 1.5;
    var dw = Math.max(1, Math.round(sw * scale));
    var dh = Math.max(1, Math.round(sh * scale));
    var out = document.createElement('canvas');
    out.width = dw;
    out.height = dh;
    var ctx = out.getContext('2d', { willReadFrequently: true });
    if (!ctx) return out;
    ctx.imageSmoothingEnabled = true;
    ctx.drawImage(srcCanvas, sx, sy, sw, sh, 0, 0, dw, dh);
    var imageData = ctx.getImageData(0, 0, dw, dh);
    var d = imageData.data;
    for (var i = 0; i < d.length; i += 4) {
      var g = d[i] * 0.299 + d[i + 1] * 0.587 + d[i + 2] * 0.114;
      g = (g - 128) * 1.55 + 128;
      if (g < 0) g = 0;
      if (g > 255) g = 255;
      // Soft binarize helps plate glyphs
      if (g < 95) g = 0;
      else if (g > 175) g = 255;
      d[i] = d[i + 1] = d[i + 2] = g;
    }
    ctx.putImageData(imageData, 0, 0);
    return out;
  }

  function applyDetectedPlate(plate, autoLookup) {
    var value = normalizePlateText(plate);
    if (!value) return;
    if (plateInput) {
      plateInput.value = value;
      try {
        plateInput.dispatchEvent(new Event('input', { bubbles: true }));
      } catch (e) {}
    }
    setStatus('Detected plate: ' + value, 'ok');
    if (autoLookup) {
      lookup({ mode: 'plate', plate: value });
    } else if (plateInput) {
      plateInput.focus();
    }
  }

  function recognizePlateFromSource(source) {
    return drawSourceToCanvas(source).then(function (baseCanvas) {
      var variants = [
        preprocessPlateCanvas(baseCanvas, true),
        preprocessPlateCanvas(baseCanvas, false),
      ];
      return getPlateOcrWorker().then(function (worker) {
        var texts = [];
        var psms = ['7', '8', '6'];
        var chain = Promise.resolve();
        variants.forEach(function (canvas) {
          psms.forEach(function (psm) {
            chain = chain.then(function () {
              return worker
                .setParameters({
                  tessedit_char_whitelist: 'ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789',
                  preserve_interword_spaces: '1',
                  tessedit_pageseg_mode: psm,
                })
                .then(function () {
                  return worker.recognize(canvas).then(function (result) {
                    texts.push((result && result.data && result.data.text) || '');
                  });
                });
            });
          });
        });
        return chain.then(function () {
          var merged = texts.join('\n');
          var candidates = extractPlateCandidates(merged);
          return {
            text: merged,
            plate: candidates.length ? candidates[0] : '',
            candidates: candidates,
          };
        });
      });
    });
  }

  function showPlatePreviewFromUrl(url, revoke) {
    setPreviewMode('plate');
    if (snapImg) {
      snapImg.onload = function () {
        if (revoke) URL.revokeObjectURL(url);
      };
      snapImg.onerror = function () {
        if (revoke) URL.revokeObjectURL(url);
      };
      snapImg.src = url;
      snapImg.hidden = false;
    }
    if (previewWrap) previewWrap.hidden = false;
  }

  function runPlateOcr(source, previewUrl, revokePreview) {
    if (plateOcrBusy) return;
    plateOcrBusy = true;
    if (previewUrl) showPlatePreviewFromUrl(previewUrl, !!revokePreview);
    selectTab('plate');
    showLookupLoader('Reading plate number…');
    setStatus('Reading plate number…');

    recognizePlateFromSource(source)
      .then(function (res) {
        plateOcrBusy = false;
        if (res.plate) {
          applyDetectedPlate(res.plate, true);
          return;
        }
        hideLookupLoader();
        setStatus(
          'Could not auto-read the plate. Type the number you see, then tap Find.',
          'error'
        );
        if (plateInput) plateInput.focus();
      })
      .catch(function () {
        plateOcrBusy = false;
        hideLookupLoader();
        setStatus(
          'Plate auto-detect failed. Type the number, then tap Find.',
          'error'
        );
        if (plateInput) plateInput.focus();
      });
  }

  function detectQrFromCanvas() {
    if (!canvas) return Promise.resolve(null);
    if ('BarcodeDetector' in window) {
      var detector = new window.BarcodeDetector({ formats: ['qr_code'] });
      return detector
        .detect(canvas)
        .then(function (codes) {
          if (codes && codes.length) return codes[0].rawValue || null;
          return detectQrWithJsQRFromCanvas(canvas);
        })
        .catch(function () {
          return detectQrWithJsQRFromCanvas(canvas);
        });
    }
    return detectQrWithJsQRFromCanvas(canvas);
  }

  function detectQrWithJsQRFromCanvas(sourceCanvas) {
    return ensureJsQR().then(function (jsQR) {
      var scales = [1, 0.75, 0.5, 1.5];
      for (var s = 0; s < scales.length; s++) {
        var scale = scales[s];
        var w = Math.max(1, Math.round(sourceCanvas.width * scale));
        var h = Math.max(1, Math.round(sourceCanvas.height * scale));
        // Cap huge images for performance
        if (w > 1600 || h > 1600) {
          var cap = 1600 / Math.max(w, h);
          w = Math.max(1, Math.round(w * cap));
          h = Math.max(1, Math.round(h * cap));
        }
        var c = document.createElement('canvas');
        c.width = w;
        c.height = h;
        var ctx = c.getContext('2d', { willReadFrequently: true });
        if (!ctx) continue;
        ctx.imageSmoothingEnabled = scale < 1;
        ctx.drawImage(sourceCanvas, 0, 0, w, h);
        var imageData = ctx.getImageData(0, 0, w, h);
        var code = jsQR(imageData.data, imageData.width, imageData.height, {
          inversionAttempts: 'attemptBoth',
        });
        if (code && code.data) return code.data;

        // Grayscale boost pass
        var d = imageData.data;
        for (var i = 0; i < d.length; i += 4) {
          var g = (d[i] * 0.299 + d[i + 1] * 0.587 + d[i + 2] * 0.114) | 0;
          // Mild contrast stretch
          g = g < 110 ? 0 : g > 160 ? 255 : g;
          d[i] = d[i + 1] = d[i + 2] = g;
        }
        code = jsQR(imageData.data, imageData.width, imageData.height, {
          inversionAttempts: 'attemptBoth',
        });
        if (code && code.data) return code.data;
      }
      return null;
    });
  }

  function detectQrFromImageSource(source) {
    var w = source.naturalWidth || source.width || source.videoWidth || 0;
    var h = source.naturalHeight || source.height || source.videoHeight || 0;
    if (!w || !h) return Promise.resolve(null);

    var c = document.createElement('canvas');
    c.width = w;
    c.height = h;
    var ctx = c.getContext('2d', { willReadFrequently: true });
    if (!ctx) return Promise.resolve(null);
    ctx.drawImage(source, 0, 0, w, h);

    if ('BarcodeDetector' in window) {
      var detector = new window.BarcodeDetector({ formats: ['qr_code'] });
      return detector
        .detect(source)
        .then(function (codes) {
          if (codes && codes.length) return codes[0].rawValue || null;
          return detector.detect(c).then(function (codes2) {
            if (codes2 && codes2.length) return codes2[0].rawValue || null;
            return detectQrWithJsQRFromCanvas(c);
          });
        })
        .catch(function () {
          return detectQrWithJsQRFromCanvas(c);
        });
    }
    return detectQrWithJsQRFromCanvas(c);
  }

  function loadImageFromFile(file) {
    return new Promise(function (resolve, reject) {
      var url = URL.createObjectURL(file);
      var img = new Image();
      img.onload = function () {
        resolve({ img: img, url: url });
      };
      img.onerror = function () {
        URL.revokeObjectURL(url);
        reject(new Error('image'));
      };
      img.src = url;
    });
  }

  function showQrPreviewFromUrl(url, revoke) {
    setPreviewMode('qr');
    if (snapImg) {
      snapImg.onload = function () {
        if (revoke) URL.revokeObjectURL(url);
      };
      snapImg.onerror = function () {
        if (revoke) URL.revokeObjectURL(url);
      };
      snapImg.src = url;
      snapImg.hidden = false;
    }
    if (previewWrap) previewWrap.hidden = false;
  }

  function handleQrRaw(raw) {
    if (!raw) return;
    showLookupLoader('Finding vehicle…');
    setStatus('QR detected. Opening notify…', 'ok');
    lookup({ mode: 'qr', qr: String(raw) });
  }

  function openSheet(mode) {
    pendingSheetMode = mode || 'qr';
    if (sheetTitle) {
      sheetTitle.textContent =
        pendingSheetMode === 'plate'
          ? 'Scan number plate'
          : 'Scan QR — notify or activate';
    }
    if (sheet) {
      sheet.hidden = false;
      sheet.setAttribute('aria-hidden', 'false');
      document.body.classList.add('find-vehicle-sheet-open');
    }
  }

  function closeSheet() {
    if (sheet) {
      sheet.hidden = true;
      sheet.setAttribute('aria-hidden', 'true');
    }
    document.body.classList.remove('find-vehicle-sheet-open');
  }

  function setPreviewMode(mode) {
    activeMode = mode;
    if (previewWrap) {
      previewWrap.classList.toggle('is-qr', mode === 'qr');
      previewWrap.classList.toggle('is-plate', mode === 'plate');
    }
    if (previewFrame) {
      previewFrame.setAttribute(
        'data-mode-label',
        mode === 'plate' ? 'PLATE' : 'QR'
      );
    }
    if (guide) {
      guide.classList.toggle('is-plate', mode === 'plate');
      guide.classList.toggle('is-qr', mode === 'qr');
    }
  }

  function startCamera(mode) {
    activeMode = mode || 'qr';
    setPreviewMode(activeMode);
    clearSnap();

    if (!window.isSecureContext) {
      setStatus(
        'Camera needs HTTPS (or localhost). Use Gallery or paste the details.',
        'error'
      );
      return;
    }
    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
      setStatus(
        'Camera not available. Use Gallery or type the details.',
        'error'
      );
      return;
    }

    // Warm detectors
    if (activeMode === 'qr' && !('BarcodeDetector' in window)) {
      ensureJsQR().catch(function () {});
    }
    if (activeMode === 'plate') {
      getPlateOcrWorker().catch(function () {});
    }

    stopCamera();
    setStatus('Starting camera… Allow access if asked.');
    if (previewWrap) previewWrap.hidden = false;

    navigator.mediaDevices
      .getUserMedia(CAMERA_OPTS)
      .catch(function () {
        return navigator.mediaDevices.getUserMedia({
          audio: false,
          video: { facingMode: 'environment' },
        });
      })
      .catch(function () {
        return navigator.mediaDevices.getUserMedia({
          audio: false,
          video: true,
        });
      })
      .then(function (stream) {
        mediaStream = stream;
        if (!video) throw new Error('no-video');
        video.hidden = false;
        video.setAttribute('playsinline', 'true');
        video.setAttribute('webkit-playsinline', 'true');
        video.setAttribute('autoplay', 'true');
        video.muted = true;
        video.playsInline = true;
        video.srcObject = stream;
        var playPromise = video.play();
        if (playPromise && typeof playPromise.then === 'function') {
          return playPromise.catch(function () {
            // Autoplay quirks: stream is still attached; UI can continue.
          });
        }
      })
      .then(function () {
        if (stopBtn) stopBtn.hidden = false;
        if (captureBtn) {
          captureBtn.hidden = false;
          captureBtn.textContent =
            activeMode === 'plate' ? 'Capture' : 'Capture QR';
        }
        if (activeMode === 'qr') {
          setStatus('Point at the SudoTag QR…');
          scanTimer = setInterval(tickQrDetect, 500);
        } else {
          setStatus('Point at the number plate — auto-detecting…');
          scanTimer = setInterval(tickPlateDetect, 1200);
        }
        // Scroll preview into view on small screens
        if (previewWrap && previewWrap.scrollIntoView) {
          try {
            previewWrap.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
          } catch (e) {}
        }
      })
      .catch(function (err) {
        var denied =
          err &&
          (err.name === 'NotAllowedError' || err.name === 'PermissionDeniedError');
        var secure =
          err && (err.name === 'SecurityError' || err.name === 'NotSupportedError');
        setStatus(
          denied
            ? 'Camera permission denied. Enable it for this site, or use Gallery.'
            : secure
              ? 'Camera blocked in this browser. Use Gallery or paste the details.'
              : 'Could not open camera. Try Gallery instead.',
          'error'
        );
        if (previewWrap && (!snapImg || snapImg.hidden)) {
          previewWrap.hidden = true;
        }
      });
  }

  function tickPlateDetect() {
    if (detecting || busy || plateOcrBusy || !video || !canvas) return;
    if (activeMode !== 'plate') return;
    if (video.readyState < 2) return;
    var w = video.videoWidth;
    var h = video.videoHeight;
    if (!w || !h) return;
    detecting = true;
    canvas.width = w;
    canvas.height = h;
    var ctx = canvas.getContext('2d', { willReadFrequently: true });
    if (!ctx) {
      detecting = false;
      return;
    }
    ctx.drawImage(video, 0, 0, w, h);
    recognizePlateFromSource(canvas)
      .then(function (res) {
        detecting = false;
        if (!res.plate || busy || plateOcrBusy) return;
        var dataUrl = canvas.toDataURL('image/jpeg', 0.9);
        if (snapImg) {
          snapImg.src = dataUrl;
          snapImg.hidden = false;
        }
        if (previewWrap) previewWrap.hidden = false;
        stopCamera();
        if (previewWrap) previewWrap.hidden = false;
        if (snapImg) snapImg.hidden = false;
        applyDetectedPlate(res.plate, true);
      })
      .catch(function () {
        detecting = false;
      });
  }

  function tickQrDetect() {
    if (detecting || busy || !video || !canvas) return;
    if (video.readyState < 2) return;
    var w = video.videoWidth;
    var h = video.videoHeight;
    if (!w || !h) return;
    detecting = true;
    canvas.width = w;
    canvas.height = h;
    var ctx = canvas.getContext('2d', { willReadFrequently: true });
    if (!ctx) {
      detecting = false;
      return;
    }
    ctx.drawImage(video, 0, 0, w, h);
    detectQrFromCanvas()
      .then(function (raw) {
        detecting = false;
        if (raw) handleQrRaw(raw);
      })
      .catch(function () {
        detecting = false;
      });
  }

  function capturePlateFrame() {
    if (!video || !canvas || video.readyState < 2) {
      setStatus('Camera not ready yet. Wait a moment.', 'error');
      return;
    }
    var w = video.videoWidth;
    var h = video.videoHeight;
    canvas.width = w;
    canvas.height = h;
    var ctx = canvas.getContext('2d', { willReadFrequently: true });
    if (!ctx) return;
    ctx.drawImage(video, 0, 0, w, h);

    if (activeMode === 'qr') {
      setStatus('Reading QR from capture…');
      detectQrFromCanvas()
        .then(function (raw) {
          if (raw) {
            handleQrRaw(raw);
            return;
          }
          var dataUrl = canvas.toDataURL('image/jpeg', 0.85);
          if (snapImg) {
            snapImg.src = dataUrl;
            snapImg.hidden = false;
          }
          if (previewWrap) previewWrap.hidden = false;
          stopCamera();
          if (previewWrap) previewWrap.hidden = false;
          if (snapImg) snapImg.hidden = false;
          setStatus(
            'No QR found. Try again, use Gallery, or paste the QR link.',
            'error'
          );
        })
        .catch(function () {
          setStatus('Could not read QR. Paste the link or try Gallery.', 'error');
        });
      return;
    }

    var dataUrl = canvas.toDataURL('image/jpeg', 0.92);
    if (snapImg) {
      snapImg.src = dataUrl;
      snapImg.hidden = false;
    }
    if (previewWrap) previewWrap.hidden = false;
    stopCamera();
    if (previewWrap) previewWrap.hidden = false;
    if (snapImg) snapImg.hidden = false;
    // Re-draw to a blob/canvas for OCR (data URL works with Tesseract)
    runPlateOcr(dataUrl, dataUrl, false);
  }

  function readQrFromFile(file) {
    if (!file) return;
    showLookupLoader('Reading QR from image…');
    setStatus('Reading QR from image…');
    selectTab('qr');

    loadImageFromFile(file)
      .then(function (pack) {
        showQrPreviewFromUrl(pack.url, true);
        // Prefer createImageBitmap when available (faster decode path)
        var sourcePromise =
          typeof createImageBitmap === 'function'
            ? createImageBitmap(file).catch(function () {
                return pack.img;
              })
            : Promise.resolve(pack.img);
        return sourcePromise.then(function (source) {
          return detectQrFromImageSource(source).then(function (raw) {
            if (source && source.close) {
              try {
                source.close();
              } catch (e) {}
            }
            return raw;
          });
        });
      })
      .then(function (raw) {
        if (!raw) {
          hideLookupLoader();
          setStatus(
            'No QR code found in that image. Try a clearer photo or paste the link.',
            'error'
          );
          if (qrInput) qrInput.focus();
          return;
        }
        if (qrInput) qrInput.value = String(raw);
        handleQrRaw(raw);
      })
      .catch(function () {
        hideLookupLoader();
        setStatus('Could not read that image. Paste the QR link instead.', 'error');
        if (qrInput) qrInput.focus();
      });
  }

  function readPlateFromFile(file) {
    if (!file) return;
    var url = URL.createObjectURL(file);
    runPlateOcr(file, url, true);
  }

  function setStageMode(name) {
    activeMode = name === 'plate' ? 'plate' : 'qr';
    card.setAttribute('data-mode', activeMode);
  }
  setStageMode('qr');

  // Tabs
  card.querySelectorAll('.find-vehicle-tab').forEach(function (tab) {
    tab.addEventListener('click', function () {
      var name = tab.getAttribute('data-tab');
      setStageMode(name);
      card.querySelectorAll('.find-vehicle-tab').forEach(function (t) {
        t.classList.toggle('is-active', t === tab);
        t.setAttribute('aria-selected', t === tab ? 'true' : 'false');
      });
      card.querySelectorAll('.find-vehicle-panel').forEach(function (panel) {
        var on = panel.getAttribute('data-panel') === name;
        panel.hidden = !on;
        panel.classList.toggle('is-active', on);
      });
      stopCamera();
      clearSnap();
      if (previewWrap) previewWrap.hidden = true;
      setStatus('');
      if (name === 'plate') {
        // Warm OCR worker so gallery upload is faster
        getPlateOcrWorker().catch(function () {});
      }
    });
  });

  if (qrGo) {
    qrGo.addEventListener('click', function () {
      var v = (qrInput && qrInput.value) || '';
      if (!v.trim()) {
        setStatus('Paste a SudoTag QR link or ID.', 'error');
        return;
      }
      lookup({ mode: 'qr', qr: v.trim() });
    });
  }
  if (qrInput) {
    qrInput.addEventListener('keydown', function (e) {
      if (e.key === 'Enter') {
        e.preventDefault();
        if (qrGo) qrGo.click();
      }
    });
  }

  if (plateGo) {
    plateGo.addEventListener('click', function () {
      var v = (plateInput && plateInput.value) || '';
      if (!v.trim()) {
        setStatus('Enter the vehicle registration number.', 'error');
        return;
      }
      lookup({ mode: 'plate', plate: v.trim() });
    });
  }
  if (plateInput) {
    plateInput.addEventListener('keydown', function (e) {
      if (e.key === 'Enter') {
        e.preventDefault();
        if (plateGo) plateGo.click();
      }
    });
  }

  if (fileInput) {
    fileInput.addEventListener('change', function () {
      var file = fileInput.files && fileInput.files[0];
      readQrFromFile(file);
      fileInput.value = '';
    });
  }
  if (plateFileInput) {
    plateFileInput.addEventListener('change', function () {
      var file = plateFileInput.files && plateFileInput.files[0];
      readPlateFromFile(file);
      plateFileInput.value = '';
    });
  }

  if (scanBtn) {
    scanBtn.addEventListener('click', function () {
      openSheet('qr');
    });
  }
  if (plateScanBtn) {
    plateScanBtn.addEventListener('click', function () {
      openSheet('plate');
    });
  }

  if (sheetCamera) {
    sheetCamera.addEventListener('click', function () {
      closeSheet();
      // Keep getUserMedia in the same user-gesture turn
      startCamera(pendingSheetMode);
    });
  }
  if (sheetGallery) {
    sheetGallery.addEventListener('click', function () {
      closeSheet();
      if (pendingSheetMode === 'plate') {
        if (plateFileInput) plateFileInput.click();
      } else if (fileInput) {
        fileInput.click();
      }
    });
  }
  if (sheet) {
    sheet.querySelectorAll('[data-sheet-close]').forEach(function (el) {
      el.addEventListener('click', closeSheet);
    });
  }

  if (captureBtn) {
    captureBtn.addEventListener('click', function () {
      capturePlateFrame();
    });
  }
  if (stopBtn) {
    stopBtn.addEventListener('click', function () {
      stopCamera();
      setStatus('Camera stopped.');
    });
  }

  window.addEventListener('pagehide', function () {
    stopCamera();
  });
  window.addEventListener('pageshow', function (event) {
    // Back/forward cache or return from notify → clear capture/upload state
    if (event.persisted || consumeNeedsReset()) {
      resetFindVehicleState();
    }
  });
  document.addEventListener('visibilitychange', function () {
    if (document.visibilityState === 'visible' && consumeNeedsReset()) {
      resetFindVehicleState();
    }
  });
  // Fresh landings from Notify "Home" (#find-vehicle)
  if (consumeNeedsReset()) {
    resetFindVehicleState();
  }
  document.addEventListener('keydown', function (e) {
    if (e.key === 'Escape' && sheet && !sheet.hidden) closeSheet();
  });
})();
