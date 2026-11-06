/**
 * Homepage motion helpers. Visual only — does not scan a real QR.
 */
(function () {
  "use strict";

  if (!document.body.classList.contains("index-page")) return;

  var reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  var fine = window.matchMedia("(hover: hover) and (pointer: fine)").matches;
  var wide = window.matchMedia("(min-width: 992px)").matches;

  var chip = document.querySelector(".hero-scan-phone__chip span");
  if (chip && !reduce) {
    var lines = ["Scanning SudoTag QR…", "Owner alerted · number hidden"];
    var step = 0;
    window.setInterval(function () {
      step = (step + 1) % lines.length;
      chip.textContent = lines[step];
      var box = chip.closest(".hero-scan-phone__chip");
      if (box) box.classList.toggle("is-done", step === 1);
    }, 2800);
  }

  var cards = document.querySelectorAll(".hiw-step-card");
  if (cards.length && "IntersectionObserver" in window) {
    var seen = new IntersectionObserver(function (entries) {
      entries.forEach(function (entry) {
        if (!entry.isIntersecting) return;
        cards.forEach(function (card, index) {
          window.setTimeout(function () {
            card.classList.add("is-on");
          }, reduce ? 0 : index * 180);
        });
        seen.disconnect();
      });
    }, { threshold: 0.4 });
    seen.observe(cards[0]);
  }

  if (fine && wide && !reduce) {
    document.querySelectorAll(".btn-getstarted, .btn-buy-now").forEach(function (el) {
      el.addEventListener("pointermove", function (event) {
        var box = el.getBoundingClientRect();
        var x = Math.max(-8, Math.min(8, (event.clientX - (box.left + box.width / 2)) * 0.18));
        var y = Math.max(-6, Math.min(6, (event.clientY - (box.top + box.height / 2)) * 0.22));
        el.style.transform = "translate(" + x + "px, " + y + "px)";
      });
      el.addEventListener("pointerleave", function () {
        el.style.transform = "";
      });
    });
  }
})();
