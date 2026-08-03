/**
 * Activate form: plate photo / camera → OCR → fill registrationNumber.
 */
(function () {
  var regInput = document.getElementById('registrationNumber');
  if (!regInput) return;

  var statusEl = document.getElementById('plateOcrStatus');
  var cameraBtn = document.getElementById('plateOcrCameraBtn');
  var fileInput = document.getElementById('plateOcrFile');
  var preview = document.getElementById('plateOcrPreview');
  var previewBar = document.getElementById('plateOcrPreviewBar');
  var video = document.getElementById('plateOcrVideo');
  var snap = document.getElementById('plateOcrSnap');
  var canvas = document.getElementById('plateOcrCanvas');
  var captureBtn = document.getElementById('plateOcrCaptureBtn');
  var stopBtn = document.getElementById('plateOcrStopBtn');

  var mediaStream = null;
  var tesseractLoader = null;
  var tesseractWorker = null;
  var busy = false;

  function setStatus(msg, kind) {
    if (!statusEl) return;
    statusEl.textContent = msg || '';
    statusEl.classList.remove('is-ok', 'is-error');
    if (kind === 'ok') statusEl.classList.add('is-ok');
    if (kind === 'error') statusEl.classList.add('is-error');
  }

  function setBusy(on) {
    busy = !!on;
    if (cameraBtn) cameraBtn.disabled = busy;
    if (captureBtn) captureBtn.disabled = busy;
    if (fileInput) fileInput.disabled = busy;
  }

  function stopCamera() {
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
    if (previewBar) previewBar.hidden = true;
    if (preview && (!snap || snap.hidden)) preview.hidden = true;
  }

  function ensureTesseract() {
    if (window.Tesseract && typeof window.Tesseract.createWorker === 'function') {
      return Promise.resolve(window.Tesseract);
    }
    if (tesseractLoader) return tesseractLoader;
    function load(src) {
      return new Promise(function (resolve, reject) {
        var s = document.createElement('script');
        s.src = src;
        s.async = true;
        s.onload = function () {
          if (window.Tesseract && typeof window.Tesseract.createWorker === 'function') {
            resolve(window.Tesseract);
          } else reject(new Error('missing'));
        };
        s.onerror = reject;
        document.head.appendChild(s);
      });
    }
    tesseractLoader = load(
      'https://cdn.jsdelivr.net/npm/tesseract.js@5.1.1/dist/tesseract.min.js'
    ).catch(function () {
      return load('https://unpkg.com/tesseract.js@5.1.1/dist/tesseract.min.js');
    }).catch(function (err) {
      tesseractLoader = null;
      throw err;
    });
    return tesseractLoader;
  }

  function getWorker() {
    return ensureTesseract().then(function (Tesseract) {
      if (tesseractWorker) return tesseractWorker;
      return Tesseract.createWorker('eng', 1, { logger: function () {} }).then(function (worker) {
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

  function normalizePlate(raw) {
    return String(raw || '')
      .toUpperCase()
      .replace(/[^A-Z0-9]/g, '');
  }

  function isLikelyIndianPlate(plate) {
    var p = normalizePlate(plate);
    if (p.length < 7 || p.length > 12) return false;
    if (/^[A-Z]{2}\d{1,2}[A-Z]{1,3}\d{1,4}$/.test(p)) return true;
    if (/^\d{2}BH\d{4}[A-Z]{1,2}$/.test(p)) return true;
    return false;
  }

  function plateScore(plate) {
    var p = normalizePlate(plate);
    var score = p.length;
    if (/^[A-Z]{2}\d{2}[A-Z]{1,3}\d{4}$/.test(p)) score += 20;
    else if (/^[A-Z]{2}\d{1,2}[A-Z]{1,3}\d{1,4}$/.test(p)) score += 12;
    if (/^\d{2}BH\d{4}[A-Z]{1,2}$/.test(p)) score += 18;
    return score;
  }

  function variants(plate) {
    var base = normalizePlate(plate);
    var out = [base];
    [
      [/O/g, '0'],
      [/0/g, 'O'],
      [/I/g, '1'],
      [/1/g, 'I'],
      [/S/g, '5'],
      [/5/g, 'S'],
      [/B/g, '8'],
      [/8/g, 'B'],
    ].forEach(function (pair) {
      var v = base.replace(pair[0], pair[1]);
      if (v !== base) out.push(v);
    });
    return out;
  }

  function extractCandidates(text) {
    var upper = String(text || '').toUpperCase();
    var compact = upper.replace(/[^A-Z0-9]/g, '');
    var spaced = upper.replace(/[^A-Z0-9\s]/g, ' ');
    var found = {};
    function add(raw) {
      variants(raw).forEach(function (v) {
        if (isLikelyIndianPlate(v)) found[normalizePlate(v)] = true;
      });
    }
    [
      /[A-Z]{2}\s*\d{1,2}\s*[A-Z]{1,3}\s*\d{1,4}/g,
      /\d{2}\s*BH\s*\d{4}\s*[A-Z]{1,2}/g,
      /[A-Z]{2}\d{1,2}[A-Z]{1,3}\d{1,4}/g,
      /\d{2}BH\d{4}[A-Z]{1,2}/g,
    ].forEach(function (re) {
      var src = re.source.indexOf('\\s') >= 0 ? spaced : compact;
      var m;
      re.lastIndex = 0;
      while ((m = re.exec(src)) !== null) add(m[0]);
    });
    if (!Object.keys(found).length && compact.length >= 7 && compact.length <= 120) {
      for (var len = 12; len >= 7; len--) {
        for (var i = 0; i + len <= compact.length; i++) add(compact.slice(i, i + len));
      }
    }
    return Object.keys(found).sort(function (a, b) {
      return plateScore(b) - plateScore(a);
    });
  }

  function drawToCanvas(source) {
    return new Promise(function (resolve, reject) {
      function fromDrawable(drawable) {
        var w = drawable.naturalWidth || drawable.videoWidth || drawable.width || 0;
        var h = drawable.naturalHeight || drawable.videoHeight || drawable.height || 0;
        if (!w || !h) {
          reject(new Error('empty'));
          return;
        }
        var c = document.createElement('canvas');
        c.width = w;
        c.height = h;
        var ctx = c.getContext('2d', { willReadFrequently: true });
        if (!ctx) {
          reject(new Error('ctx'));
          return;
        }
        ctx.drawImage(drawable, 0, 0, w, h);
        resolve(c);
      }
      if (source instanceof HTMLCanvasElement) {
        resolve(source);
        return;
      }
      if (typeof Blob !== 'undefined' && source instanceof Blob) {
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
            .catch(reject);
          return;
        }
        var url = URL.createObjectURL(source);
        var img = new Image();
        img.onload = function () {
          URL.revokeObjectURL(url);
          fromDrawable(img);
        };
        img.onerror = function () {
          URL.revokeObjectURL(url);
          reject(new Error('image'));
        };
        img.src = url;
        return;
      }
      fromDrawable(source);
    });
  }

  function preprocess(srcCanvas) {
    var w = srcCanvas.width;
    var h = srcCanvas.height;
    var sx = Math.floor(w * 0.06);
    var sy = Math.floor(h * 0.28);
    var sw = Math.max(1, Math.floor(w * 0.88));
    var sh = Math.max(1, Math.floor(h * 0.4));
    var scale = sw < 700 ? 3 : 2;
    var out = document.createElement('canvas');
    out.width = Math.round(sw * scale);
    out.height = Math.round(sh * scale);
    var ctx = out.getContext('2d', { willReadFrequently: true });
    if (!ctx) return out;
    ctx.drawImage(srcCanvas, sx, sy, sw, sh, 0, 0, out.width, out.height);
    var imageData = ctx.getImageData(0, 0, out.width, out.height);
    var d = imageData.data;
    for (var i = 0; i < d.length; i += 4) {
      var g = d[i] * 0.299 + d[i + 1] * 0.587 + d[i + 2] * 0.114;
      g = (g - 128) * 1.55 + 128;
      if (g < 0) g = 0;
      if (g > 255) g = 255;
      if (g < 95) g = 0;
      else if (g > 175) g = 255;
      d[i] = d[i + 1] = d[i + 2] = g;
    }
    ctx.putImageData(imageData, 0, 0);
    return out;
  }

  function fillPlate(plate) {
    var value = normalizePlate(plate);
    if (!value) return;
    regInput.value = value;
    regInput.classList.remove('is-invalid');
    try {
      regInput.dispatchEvent(new Event('input', { bubbles: true }));
      regInput.dispatchEvent(new Event('change', { bubbles: true }));
    } catch (e) {}
    setStatus('Detected plate: ' + value, 'ok');
    try {
      regInput.focus();
      regInput.scrollIntoView({ behavior: 'smooth', block: 'center' });
    } catch (e2) {}
  }

  function recognize(source) {
    setBusy(true);
    setStatus('Reading plate number…');
    return drawToCanvas(source)
      .then(function (base) {
        var cropped = preprocess(base);
        return getWorker().then(function (worker) {
          var texts = [];
          var psms = ['7', '8', '6'];
          var chain = Promise.resolve();
          [cropped, base].forEach(function (canvasVariant) {
            psms.forEach(function (psm) {
              chain = chain.then(function () {
                return worker
                  .setParameters({
                    tessedit_char_whitelist: 'ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789',
                    preserve_interword_spaces: '1',
                    tessedit_pageseg_mode: psm,
                  })
                  .then(function () {
                    return worker.recognize(canvasVariant).then(function (result) {
                      texts.push((result && result.data && result.data.text) || '');
                    });
                  });
              });
            });
          });
          return chain.then(function () {
            return extractCandidates(texts.join('\n'));
          });
        });
      })
      .then(function (candidates) {
        setBusy(false);
        if (candidates && candidates.length) {
          fillPlate(candidates[0]);
          return candidates[0];
        }
        setStatus('Could not read the plate. Type it manually.', 'error');
        return '';
      })
      .catch(function () {
        setBusy(false);
        setStatus('Plate auto-detect failed. Type the number manually.', 'error');
        return '';
      });
  }

  function startCamera() {
    if (!window.isSecureContext) {
      setStatus('Camera needs HTTPS (or localhost). Use Gallery instead.', 'error');
      return;
    }
    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
      setStatus('Camera not available. Use Gallery instead.', 'error');
      return;
    }
    stopCamera();
    setStatus('Starting camera… Allow access if asked.');
    if (preview) preview.hidden = false;
    if (snap) snap.hidden = true;
    getWorker().catch(function () {});

    navigator.mediaDevices
      .getUserMedia({
        audio: false,
        video: { facingMode: { ideal: 'environment' }, width: { ideal: 1280 }, height: { ideal: 720 } },
      })
      .catch(function () {
        return navigator.mediaDevices.getUserMedia({ audio: false, video: true });
      })
      .then(function (stream) {
        mediaStream = stream;
        if (!video) throw new Error('no-video');
        video.hidden = false;
        video.setAttribute('playsinline', 'true');
        video.setAttribute('webkit-playsinline', 'true');
        video.muted = true;
        video.playsInline = true;
        video.srcObject = stream;
        var playPromise = video.play();
        if (playPromise && typeof playPromise.then === 'function') {
          return playPromise.catch(function () {});
        }
      })
      .then(function () {
        if (previewBar) previewBar.hidden = false;
        setStatus('Align the number plate, then tap Capture.');
      })
      .catch(function (err) {
        var denied =
          err &&
          (err.name === 'NotAllowedError' || err.name === 'PermissionDeniedError');
        setStatus(
          denied
            ? 'Camera permission denied. Use Gallery instead.'
            : 'Could not open camera. Use Gallery instead.',
          'error'
        );
        if (preview) preview.hidden = true;
      });
  }

  if (cameraBtn) {
    cameraBtn.addEventListener('click', function () {
      startCamera();
    });
  }
  if (stopBtn) {
    stopBtn.addEventListener('click', function () {
      stopCamera();
      setStatus('Camera stopped.');
    });
  }
  if (captureBtn) {
    captureBtn.addEventListener('click', function () {
      if (!video || !canvas || video.readyState < 2) {
        setStatus('Camera not ready yet.', 'error');
        return;
      }
      canvas.width = video.videoWidth;
      canvas.height = video.videoHeight;
      var ctx = canvas.getContext('2d', { willReadFrequently: true });
      if (!ctx) return;
      ctx.drawImage(video, 0, 0);
      var dataUrl = canvas.toDataURL('image/jpeg', 0.92);
      if (snap) {
        snap.src = dataUrl;
        snap.hidden = false;
      }
      if (video) video.hidden = true;
      stopCamera();
      if (preview) preview.hidden = false;
      if (snap) snap.hidden = false;
      recognize(canvas);
    });
  }
  if (fileInput) {
    fileInput.addEventListener('change', function () {
      var file = fileInput.files && fileInput.files[0];
      if (!file) return;
      stopCamera();
      var url = URL.createObjectURL(file);
      if (preview) preview.hidden = false;
      if (snap) {
        snap.onload = function () {
          URL.revokeObjectURL(url);
        };
        snap.src = url;
        snap.hidden = false;
      }
      if (video) video.hidden = true;
      if (previewBar) previewBar.hidden = true;
      recognize(file);
      fileInput.value = '';
    });
  }

  window.addEventListener('pagehide', stopCamera);
})();
