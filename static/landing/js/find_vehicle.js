/**
 * Landing: Scan QR / plate → camera options → notify screen.
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

  function lookup(payload) {
    if (busy) return Promise.resolve();
    busy = true;
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
        busy = false;
        var data = res.data || {};
        if (data.status === 'success' && data.notify_url) {
          setStatus('Opening notify screen…', 'ok');
          stopCamera();
          window.location.href = data.notify_url;
          return;
        }
        setStatus(
          data.message || 'Could not find that vehicle. Try again.',
          'error'
        );
      })
      .catch(function () {
        busy = false;
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

  function detectQrFromCanvas() {
    if (!canvas) return Promise.resolve(null);
    if ('BarcodeDetector' in window) {
      var detector = new window.BarcodeDetector({ formats: ['qr_code'] });
      return detector.detect(canvas).then(function (codes) {
        if (!codes || !codes.length) return null;
        return codes[0].rawValue || null;
      });
    }
    return ensureJsQR().then(function (jsQR) {
      var ctx = canvas.getContext('2d', { willReadFrequently: true });
      if (!ctx) return null;
      var imageData = ctx.getImageData(0, 0, canvas.width, canvas.height);
      var code = jsQR(imageData.data, imageData.width, imageData.height, {
        inversionAttempts: 'dontInvert',
      });
      return code && code.data ? code.data : null;
    });
  }

  function handleQrRaw(raw) {
    if (!raw) return;
    lookup({ mode: 'qr', qr: String(raw) });
  }

  function openSheet(mode) {
    pendingSheetMode = mode || 'qr';
    if (sheetTitle) {
      sheetTitle.textContent =
        pendingSheetMode === 'plate'
          ? 'Scan number plate'
          : 'Scan SudoTag QR';
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

    // Warm up jsQR on Safari / browsers without BarcodeDetector
    if (activeMode === 'qr' && !('BarcodeDetector' in window)) {
      ensureJsQR().catch(function () {});
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
        // Plate always needs Capture; QR Capture is a manual fallback
        if (captureBtn) {
          captureBtn.hidden = false;
          captureBtn.textContent =
            activeMode === 'plate' ? 'Capture' : 'Capture QR';
        }
        if (activeMode === 'qr') {
          setStatus('Point at the SudoTag QR…');
          scanTimer = setInterval(tickQrDetect, 500);
        } else {
          setStatus('Align the number plate in the frame, then tap Capture.');
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
      'Photo captured. Type the plate you see, then tap Find.',
      'ok'
    );
    if (plateInput) {
      plateInput.focus();
    }
  }

  function readQrFromFile(file) {
    if (!file) return;
    setStatus('Reading QR image…');
    var runDetect = function (source) {
      if ('BarcodeDetector' in window) {
        var detector = new window.BarcodeDetector({ formats: ['qr_code'] });
        return detector.detect(source).then(function (codes) {
          if (!codes || !codes.length) return null;
          return codes[0].rawValue || null;
        });
      }
      return ensureJsQR().then(function (jsQR) {
        var c = document.createElement('canvas');
        var w = source.width || source.videoWidth || 0;
        var h = source.height || source.videoHeight || 0;
        if (!w || !h) return null;
        c.width = w;
        c.height = h;
        var ctx = c.getContext('2d');
        if (!ctx) return null;
        ctx.drawImage(source, 0, 0, w, h);
        var imageData = ctx.getImageData(0, 0, w, h);
        var code = jsQR(imageData.data, imageData.width, imageData.height, {
          inversionAttempts: 'attemptBoth',
        });
        return code && code.data ? code.data : null;
      });
    };

    var bitmapPromise =
      typeof createImageBitmap === 'function'
        ? createImageBitmap(file)
        : new Promise(function (resolve, reject) {
            var url = URL.createObjectURL(file);
            var img = new Image();
            img.onload = function () {
              URL.revokeObjectURL(url);
              resolve(img);
            };
            img.onerror = function () {
              URL.revokeObjectURL(url);
              reject(new Error('image'));
            };
            img.src = url;
          });

    bitmapPromise
      .then(function (bmp) {
        return runDetect(bmp).then(function (raw) {
          if (bmp.close) bmp.close();
          return raw;
        });
      })
      .then(function (raw) {
        if (!raw) {
          setStatus('No QR code found in that image.', 'error');
          return;
        }
        handleQrRaw(raw);
      })
      .catch(function () {
        setStatus('Could not read that image. Paste the QR link instead.', 'error');
      });
  }

  function readPlateFromFile(file) {
    if (!file) return;
    setPreviewMode('plate');
    var url = URL.createObjectURL(file);
    if (snapImg) {
      snapImg.onload = function () {
        URL.revokeObjectURL(url);
      };
      snapImg.src = url;
      snapImg.hidden = false;
    }
    if (previewWrap) previewWrap.hidden = false;
    setStatus(
      'Photo loaded. Type the plate from the photo, then tap Find.',
      'ok'
    );
    if (plateInput) plateInput.focus();
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

  window.addEventListener('pagehide', stopCamera);
  document.addEventListener('keydown', function (e) {
    if (e.key === 'Escape' && sheet && !sheet.hidden) closeSheet();
  });
})();
