(function () {
  "use strict";

  /* ============================================================
     SCROLL REVEAL - IntersectionObserver
     ============================================================ */
  function initScrollReveal() {
    var elements = document.querySelectorAll('.reveal, .reveal-left, .reveal-right, .reveal-scale');
    if (!elements.length) return;

    var observer = new IntersectionObserver(function (entries) {
      entries.forEach(function (entry) {
        if (entry.isIntersecting) {
          entry.target.classList.add('active');
          observer.unobserve(entry.target);
        }
      });
    }, { threshold: 0.1, rootMargin: '0px 0px -40px 0px' });

    elements.forEach(function (el) { observer.observe(el); });

    var staggers = document.querySelectorAll('.stagger-children');
    staggers.forEach(function (container) {
      var children = container.children;
      Array.prototype.forEach.call(children, function (child, i) {
        child.style.transitionDelay = (i * 0.08) + 's';
      });
      var sObserver = new IntersectionObserver(function (entries) {
        entries.forEach(function (entry) {
          if (entry.isIntersecting) {
            Array.prototype.forEach.call(entry.target.children, function (child) {
              child.classList.add('stagger-active');
            });
            sObserver.unobserve(entry.target);
          }
        });
      }, { threshold: 0.1, rootMargin: '0px 0px -40px 0px' });
      sObserver.observe(container);
    });
  }

  /* ============================================================
     COUNTER ANIMATION
     ============================================================ */
  function animateCounter(el, target) {
    var start = 0;
    var duration = 1200;
    var startTime = null;

    function step(timestamp) {
      if (!startTime) startTime = timestamp;
      var progress = Math.min((timestamp - startTime) / duration, 1);
      var eased = 1 - Math.pow(1 - progress, 3);
      el.textContent = Math.floor(eased * target);
      if (progress < 1) requestAnimationFrame(step);
    }
    requestAnimationFrame(step);
  }

  function initCounters() {
    var stats = document.querySelectorAll('.stat');
    if (!stats.length) return;

    var observer = new IntersectionObserver(function (entries) {
      entries.forEach(function (entry) {
        if (entry.isIntersecting && !entry.target.dataset.counted) {
          entry.target.dataset.counted = 'true';
          observer.unobserve(entry.target);
          var text = entry.target.textContent.trim();
          var num = parseInt(text, 10);
          if (!isNaN(num) && num > 0) {
            animateCounter(entry.target, num);
          }
        }
      });
    }, { threshold: 0.5 });

    stats.forEach(function (el) { observer.observe(el); });
  }

  /* ============================================================
     NAVBAR SCROLL EFFECT
     ============================================================ */
  function initNavbarScroll() {
    var header = document.querySelector('.header');
    if (!header) return;

    window.addEventListener('scroll', function () {
      if (window.scrollY > 50) {
        header.classList.add('scrolled');
      } else {
        header.classList.remove('scrolled');
      }
    }, { passive: true });
  }

  /* ============================================================
     MAGNETIC BUTTONS
     ============================================================ */
  function initMagneticButtons() {
    var btns = document.querySelectorAll('.btn-primary, .btn-danger');
    btns.forEach(function (btn) {
      btn.addEventListener('mousemove', function (e) {
        var rect = btn.getBoundingClientRect();
        var x = e.clientX - rect.left - rect.width / 2;
        var y = e.clientY - rect.top - rect.height / 2;
        btn.style.transform = 'translate(' + (x * 0.15) + 'px, ' + (y * 0.15) + 'px)';
      });
      btn.addEventListener('mouseleave', function () {
        btn.style.transform = '';
      });
    });
  }

  /* ============================================================
     TILT EFFECT ON CARDS
     ============================================================ */
  function initTiltEffect() {
    var cards = document.querySelectorAll('.card, .tool-card, .stat-card');
    cards.forEach(function (card) {
      card.addEventListener('mousemove', function (e) {
        var rect = card.getBoundingClientRect();
        var x = (e.clientX - rect.left) / rect.width;
        var y = (e.clientY - rect.top) / rect.height;
        var tiltX = (y - 0.5) * 8;
        var tiltY = (x - 0.5) * -8;
        var glareX = x * 100;
        var glareY = y * 100;
        card.style.transform = 'perspective(600px) rotateX(' + tiltX + 'deg) rotateY(' + tiltY + 'deg) translateY(-4px) scale(1.02)';
        card.style.background = 'radial-gradient(circle at ' + glareX + '% ' + glareY + '%, rgba(0,112,243,0.06) 0%, transparent 60%), var(--surface2)';
      });
      card.addEventListener('mouseleave', function () {
        card.style.transform = '';
        card.style.background = '';
      });
    });
  }

  /* ============================================================
     SMOOTH SCROLL FOR ANCHOR LINKS
     ============================================================ */
  function initSmoothScroll() {
    document.querySelectorAll('a[href^="#"]').forEach(function (anchor) {
      anchor.addEventListener('click', function (e) {
        var target = this.getAttribute('href');
        if (!target || target === '#') return;
        var el = document.querySelector(target);
        if (!el) return;
        e.preventDefault();
        el.scrollIntoView({ behavior: 'smooth', block: 'start' });
      });
    });
  }

  /* ============================================================
     UPLOAD FORM LOADING STATE
     ============================================================ */
  function initUploadLoading() {
    var form = document.getElementById('uploadForm');
    if (!form) return;

    form.addEventListener('submit', function (e) {
      e.preventDefault();
      var btn = form.querySelector('button[type="submit"]');
      var originalText = '';
      if (btn) {
        originalText = btn.innerHTML;
        btn.innerHTML = '<span class="spinner" style="width:16px;height:16px;border-width:2px;display:inline-block;vertical-align:middle;margin-right:8px"></span> Enviando...';
        btn.disabled = true;
      }

      var timeout = setTimeout(function () {
        if (btn) {
          btn.innerHTML = originalText;
          btn.disabled = false;
        }
      }, 30000);

      try {
        var formData = new FormData(form);
        fetch(form.action || window.location.href, {
          method: form.method || 'POST',
          body: formData
        }).then(function (response) {
          clearTimeout(timeout);
          if (!response.ok) {
            if (btn) {
              btn.innerHTML = originalText;
              btn.disabled = false;
            }
          } else {
            window.location.reload();
          }
        }).catch(function () {
          clearTimeout(timeout);
          if (btn) {
            btn.innerHTML = originalText;
            btn.disabled = false;
          }
        });
      } catch (err) {
        clearTimeout(timeout);
        if (btn) {
          btn.innerHTML = originalText;
          btn.disabled = false;
        }
      }
    });
  }

  /* ============================================================
     COPY BUTTON FEEDBACK
     ============================================================ */
  function initCopyFeedback() {
    document.querySelectorAll('[onclick*="clipboard"], [data-copy]').forEach(function (btn) {
      btn.addEventListener('click', function () {
        var original = this.innerHTML;
        this.innerHTML = 'Copiado!';
        this.style.background = 'var(--success)';
        var self = this;
        setTimeout(function () {
          self.innerHTML = original;
          self.style.background = '';
        }, 1500);
      });
    });
  }

  /* ============================================================
     KEYBOARD SHORTCUTS
     ============================================================ */
  function initKeyboardShortcuts() {
    document.addEventListener('keydown', function (e) {
      if (e.key === 'Escape') {
        var modals = document.querySelectorAll('.modal.active');
        modals.forEach(function (m) { m.classList.remove('active'); });
      }
    });
  }

  /* ============================================================
     INITIALIZE
     ============================================================ */
  function init() {
    initScrollReveal();
    initCounters();
    initNavbarScroll();
    initMagneticButtons();
    initTiltEffect();
    initSmoothScroll();
    initUploadLoading();
    initCopyFeedback();
    initKeyboardShortcuts();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
