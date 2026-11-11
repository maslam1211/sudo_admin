/*
 * Vehicle photos on the activation page.
 * Camera: live preview via getUserMedia (asks for camera permission). When the
 * live camera is unavailable (no HTTPS, permission denied, old browser) it falls
 * back to the phone's native camera through <input capture>.
 * Gallery: normal multi-file picker.
 * Photos are downscaled to JPEG before upload. The form script reads them via
 * window.sudoVehiclePhotos.getFiles().
 */
(function () {
  'use strict';

  var MAX_PHOTOS = 5;
  var MAX_EDGE = 1600;
  var JPEG_QUALITY = 0.85;

  var root = document.getElementById('vehiclePhotos');
  if (!root) return;

  var row = document.getElementById('vehiclePhotoRow');
  var cameraBtn = document.getElementById('vehiclePhotoCameraBtn');
  var galleryBtn = document.getElementById('vehiclePhotoGalleryBtn');
  var cameraInput = document.getElementById('vehiclePhotoCameraInput');
  var galleryInput = document.getElementById('vehiclePhotoGalleryInput');
  var preview = document.getElementById('vehiclePhotoPreview');
  var video = document.getElementById('vehiclePhotoVideo');
  var canvas = document.getElementById('vehiclePhotoCanvas');
  var snapBtn = document.getElementById('vehiclePhotoSnapBtn');
  var doneBtn = document.getElementById('vehiclePhotoDoneBtn');
  var statusEl = document.getElementById('vehiclePhotoStatus');

  var files = [];
  var stream = null;
  var pending = 0;

  function setStatus(text, kind) {
    if (!statusEl) return;
    statusEl.textContent = text || '';
    statusEl.classList.remove('is-ok', 'is-error');
    if (kind) statusEl.classList.add('is-' + kind);
  }

  function clearFieldError() {
    root.classList.remove('is-invalid');
    var fb = root.querySelector('.invalid-feedback');
    if (fb) fb.remove();
  }

  function isFull() {
    return files.length + pending >= MAX_PHOTOS;
  }

  function render() {
    row.innerHTML = '';
    row.hidden = files.length === 0;
    files.forEach(function (file, index) {
      var card = document.createElement('div');
      card.className = 'vehicle-photo';
      var img = document.createElement('img');
      var url = URL.createObjectURL(file);
      img.onload = function () { URL.revokeObjectURL(url); };
      img.src = url;
      img.alt = 'Vehicle photo ' + (index + 1);
      card.appendChild(img);
      var remove = document.createElement('button');
      remove.type = 'button';
      remove.setAttribute('aria-label', 'Remove photo ' + (index + 1));
      remove.textContent = '×';
      remove.addEventListener('click', function () {
        files.splice(index, 1);
        render();
        setStatus('');
      });
      card.appendChild(remove);
      if (index === 0) {
        var tag = document.createElement('span');
        tag.textContent = 'Main';
        card.appendChild(tag);
      }
      row.appendChild(card);
    });
    var full = isFull();
    cameraBtn.disabled = full;
    galleryBtn.disabled = full;
    if (snapBtn) snapBtn.disabled = full;
  }

  // Downscale and re-encode as JPEG. Falls back to the original file on failure.
  function shrink(file) {
    return new Promise(function (resolve) {
      if (!file || !/^image\//.test(file.type || '')) return resolve(null);
      var url = URL.createObjectURL(file);
      var img = new Image();
      img.onload = function () {
        URL.revokeObjectURL(url);
        var w = img.naturalWidth;
        var h = img.naturalHeight;
        var scale = Math.min(1, MAX_EDGE / Math.max(w, h));
        var c = document.createElement('canvas');
        c.width = Math.round(w * scale);
        c.height = Math.round(h * scale);
        var ctx = c.getContext('2d');
        if (!ctx || !c.toBlob) return resolve(file);
        ctx.drawImage(img, 0, 0, c.width, c.height);
        c.toBlob(function (blob) {
          if (!blob) return resolve(file);
          resolve(toFile(blob));
        }, 'image/jpeg', JPEG_QUALITY);
      };
      img.onerror = function () {
        URL.revokeObjectURL(url);
        // e.g. HEIC on a browser that can't decode it: let the server try.
        resolve(file);
      };
      img.src = url;
    });
  }

  function toFile(blob) {
    var name = 'vehicle-' + Date.now() + '-' + Math.floor(Math.random() * 1e4) + '.jpg';
    try {
      return new File([blob], name, { type: 'image/jpeg' });
    } catch (e) {
      blob.name = name;
      return blob;
    }
  }

  function addFiles(list) {
    var incoming = Array.prototype.slice.call(list || []);
    var skipped = 0;
    incoming.forEach(function (file) {
      if (isFull()) { skipped++; return; }
      if (!/^image\//.test(file.type || '')) { skipped++; return; }
      pending++;
      shrink(file).then(function (out) {
        pending--;
        if (out && files.length < MAX_PHOTOS) files.push(out);
        clearFieldError();
        render();
      });
    });
    render();
    if (skipped) {
      setStatus('Only ' + MAX_PHOTOS + ' image files can be added.', 'error');
    } else if (incoming.length) {
      setStatus('');
    }
  }

  function stopCamera() {
    if (stream) {
      stream.getTracks().forEach(function (t) { try { t.stop(); } catch (e) {} });
      stream = null;
    }
    if (video) {
      try { video.pause(); } catch (e) {}
      video.srcObject = null;
    }
    if (preview) preview.hidden = true;
  }

  function nativeCameraFallback(message) {
    stopCamera();
    if (message) setStatus(message, 'error');
    // Must stay inside the click's user gesture where possible; most mobile
    // browsers still allow it right after a rejected permission prompt.
    cameraInput.click();
  }

  function startCamera() {
    if (isFull()) return;
    if (!window.isSecureContext || !navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
      // No live camera API here (plain HTTP or old browser): open the phone camera.
      nativeCameraFallback('');
      return;
    }
    stopCamera();
    setStatus('Starting camera… Allow camera access if asked.');
    navigator.mediaDevices
      .getUserMedia({
        audio: false,
        video: { facingMode: { ideal: 'environment' }, width: { ideal: 1920 }, height: { ideal: 1080 } },
      })
      .catch(function (err) {
        if (err && (err.name === 'NotAllowedError' || err.name === 'SecurityError')) throw err;
        return navigator.mediaDevices.getUserMedia({ audio: false, video: true });
      })
      .then(function (s) {
        stream = s;
        preview.hidden = false;
        video.muted = true;
        video.playsInline = true;
        video.setAttribute('playsinline', 'true');
        video.setAttribute('webkit-playsinline', 'true');
        video.srcObject = s;
        var p = video.play();
        return p && p.catch ? p.catch(function () {}) : null;
      })
      .then(function () {
        if (stream) setStatus('Frame the vehicle and tap Take photo.');
      })
      .catch(function (err) {
        var denied = err && (err.name === 'NotAllowedError' || err.name === 'PermissionDeniedError');
        stopCamera();
        setStatus(
          denied
            ? 'Camera permission was blocked. Allow camera for this site in browser settings, or use Gallery.'
            : 'Could not open the live camera. Use Gallery, or try again.',
          'error'
        );
      });
  }

  function snap() {
    if (!stream || !video || video.readyState < 2 || !video.videoWidth) {
      setStatus('Camera not ready yet.', 'error');
      return;
    }
    if (isFull()) return;
    var w = video.videoWidth;
    var h = video.videoHeight;
    var scale = Math.min(1, MAX_EDGE / Math.max(w, h));
    canvas.width = Math.round(w * scale);
    canvas.height = Math.round(h * scale);
    var ctx = canvas.getContext('2d');
    if (!ctx) return;
    ctx.drawImage(video, 0, 0, canvas.width, canvas.height);
    pending++;
    canvas.toBlob(function (blob) {
      pending--;
      if (blob && files.length < MAX_PHOTOS) files.push(toFile(blob));
      clearFieldError();
      render();
      if (isFull()) {
        stopCamera();
        setStatus(MAX_PHOTOS + ' photos added.', 'ok');
      } else {
        setStatus('Photo ' + files.length + ' added. Take another or tap Done.', 'ok');
      }
    }, 'image/jpeg', JPEG_QUALITY);
  }

  cameraBtn.addEventListener('click', startCamera);
  galleryBtn.addEventListener('click', function () {
    if (!isFull()) galleryInput.click();
  });
  if (snapBtn) snapBtn.addEventListener('click', snap);
  if (doneBtn) doneBtn.addEventListener('click', function () {
    stopCamera();
    setStatus(files.length ? files.length + ' photo(s) ready.' : '');
  });
  cameraInput.addEventListener('change', function () {
    addFiles(cameraInput.files);
    cameraInput.value = '';
  });
  galleryInput.addEventListener('change', function () {
    addFiles(galleryInput.files);
    galleryInput.value = '';
  });
  window.addEventListener('pagehide', stopCamera);
  document.addEventListener('visibilitychange', function () {
    if (document.hidden) stopCamera();
  });

  window.sudoVehiclePhotos = {
    getFiles: function () { return files.slice(); },
    isBusy: function () { return pending > 0; },
    stop: stopCamera,
  };

  render();
})();
