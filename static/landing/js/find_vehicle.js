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
  var activeMode = 'qr'; // 'qr' | 'plate'
  var pendingSheetMode = 'qr';

  var CAMERA_OPTS = {
    audio: false,
    video: {
      facingMode: { ideal: 'environment' },
      width: { ideal: 1920 },
      height: { ideal: 1080 },
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
    if (mediaStream) {
      mediaStream.getTracks().forEach(function (t) {
        try {
          t.stop();
        } catch (e) {}
      });
      mediaStream = null;
    }
    if (video) {
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

  function detectBarcodeFromImageBitmap(bitmap) {
    if (!('BarcodeDetector' in window)) {
      return Promise.reject(new Error('unsupported'));
    }
    var detector = new window.BarcodeDetector({ formats: ['qr_code'] });
    return detector.detect(bitmap).then(function (codes) {
      if (!codes || !codes.length) return null;
      return codes[0].rawValue || null;
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
    if (sheet) sheet.hidden = false;
  }

  function closeSheet() {
    if (sheet) sheet.hidden = true;
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

    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
      setStatus(
        'Camera not available. Use Gallery or type the details.',
        'error'
      );
      return;
    }
    if (activeMode === 'qr' && !('BarcodeDetector' in window)) {
      setStatus(
        'Live QR scan needs Chrome/Edge. Use Gallery or paste the QR link.',
        'error'
      );
      return;
    }

    stopCamera();
    setStatus('Starting rear camera… Allow access if asked.');

    navigator.mediaDevices
      .getUserMedia(CAMERA_OPTS)
      .catch(function () {
        // Fallback if ideal constraints fail
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
        if (!video) return;
        if (previewWrap) previewWrap.hidden = false;
        video.hidden = false;
        video.setAttribute('playsinline', 'true');
        video.setAttribute('autoplay', 'true');
        video.muted = true;
        video.srcObject = stream;
        return video.play();
      })
      .then(function () {
        if (stopBtn) stopBtn.hidden = false;
        if (captureBtn) {
          captureBtn.hidden = activeMode !== 'plate';
        }
        if (activeMode === 'qr') {
          setStatus('Point at the SudoTag QR…');
          scanTimer = setInterval(tickQrDetect, 650);
        } else {
          setStatus('Align the number plate in the frame, then tap Capture.');
        }
      })
      .catch(function (err) {
        var denied =
          err &&
          (err.name === 'NotAllowedError' || err.name === 'PermissionDeniedError');
        setStatus(
          denied
            ? 'Camera permission denied. Enable it for this site, or use Gallery.'
            : 'Could not open camera. Try Gallery instead.',
          'error'
        );
      });
  }

  function tickQrDetect() {
    if (!video || video.readyState < 2 || !canvas) return;
    var w = video.videoWidth;
    var h = video.videoHeight;
    if (!w || !h) return;
    canvas.width = w;
    canvas.height = h;
    var ctx = canvas.getContext('2d');
    if (!ctx) return;
    ctx.drawImage(video, 0, 0, w, h);
    createImageBitmap(canvas)
      .then(function (bmp) {
        return detectBarcodeFromImageBitmap(bmp).then(function (raw) {
          bmp.close && bmp.close();
          return raw;
        });
      })
      .then(function (raw) {
        if (raw) handleQrRaw(raw);
      })
      .catch(function () {});
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
    var ctx = canvas.getContext('2d');
    if (!ctx) return;
    ctx.drawImage(video, 0, 0, w, h);
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
      'Photo captured. Type the plate you see, then tap Find vehicle.',
      'ok'
    );
    if (plateInput) {
      plateInput.focus();
    }
  }

  function readQrFromFile(file) {
    if (!file) return;
    if (!('BarcodeDetector' in window) || typeof createImageBitmap !== 'function') {
      setStatus(
        'QR image scan is not supported here. Paste the QR link instead.',
        'error'
      );
      return;
    }
    setStatus('Reading QR image…');
    createImageBitmap(file)
      .then(function (bmp) {
        return detectBarcodeFromImageBitmap(bmp).then(function (raw) {
          bmp.close && bmp.close();
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
      'Photo loaded. Type the plate from the photo, then tap Find vehicle.',
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
})();
