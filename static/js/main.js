// Brightpath Crisis Relief Foundation — front-end interactions

document.addEventListener('DOMContentLoaded', function () {
  // Mobile navigation toggle
  var toggle = document.getElementById('navToggle');
  var nav = document.getElementById('mainNav');
  if (toggle && nav) {
    toggle.addEventListener('click', function () {
      nav.classList.toggle('open');
    });
  }

  // Header shadow on scroll
  var header = document.getElementById('siteHeader');
  if (header) {
    window.addEventListener('scroll', function () {
      if (window.scrollY > 12) {
        header.style.boxShadow = '0 6px 24px rgba(7,26,51,.25)';
      } else {
        header.style.boxShadow = 'none';
      }
    });
  }

  // Animated counters
  var counters = document.querySelectorAll('[data-count]');
  if (counters.length && 'IntersectionObserver' in window) {
    var io = new IntersectionObserver(function (entries) {
      entries.forEach(function (entry) {
        if (entry.isIntersecting) {
          animateCounter(entry.target);
          io.unobserve(entry.target);
        }
      });
    }, { threshold: 0.4 });
    counters.forEach(function (c) { io.observe(c); });
  }

  function animateCounter(el) {
    var target = parseFloat(el.getAttribute('data-count')) || 0;
    var prefix = el.getAttribute('data-prefix') || '';
    var suffix = el.getAttribute('data-suffix') || '';
    var duration = 1400;
    var start = performance.now();
    function tick(now) {
      var p = Math.min((now - start) / duration, 1);
      var eased = 1 - Math.pow(1 - p, 3);
      var val = Math.floor(eased * target);
      el.textContent = prefix + val.toLocaleString() + suffix;
      if (p < 1) requestAnimationFrame(tick);
      else el.textContent = prefix + target.toLocaleString() + suffix;
    }
    requestAnimationFrame(tick);
  }

  // Copy-to-clipboard buttons (account & routing numbers)
  document.querySelectorAll('.copy-btn').forEach(function (btn) {
    btn.addEventListener('click', function () {
      var value = btn.getAttribute('data-copy-target') || '';
      var done = function () {
        var original = btn.textContent;
        btn.textContent = 'Copied!';
        btn.classList.add('copied');
        setTimeout(function () { btn.textContent = original; btn.classList.remove('copied'); }, 1600);
      };
      if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(value).then(done).catch(function () { fallbackCopy(value); done(); });
      } else {
        fallbackCopy(value); done();
      }
    });
  });

  function fallbackCopy(text) {
    var ta = document.createElement('textarea');
    ta.value = text; ta.style.position = 'fixed'; ta.style.opacity = '0';
    document.body.appendChild(ta); ta.select();
    try { document.execCommand('copy'); } catch (e) {}
    document.body.removeChild(ta);
  }

  // Support chat: auto-scroll to the latest message
  var chatStream = document.getElementById('chatStream');
  if (chatStream) { chatStream.scrollTop = chatStream.scrollHeight; }

  // Support chat: auto-grow textarea + attachment preview
  var chatInput = document.getElementById('chatInput');
  if (chatInput) {
    chatInput.addEventListener('input', function () {
      chatInput.style.height = 'auto';
      chatInput.style.height = Math.min(chatInput.scrollHeight, 140) + 'px';
    });
  }
  var attachInput = document.getElementById('chatAttachment');
  var attachPreview = document.getElementById('attachPreview');
  if (attachInput && attachPreview) {
    attachInput.addEventListener('change', function () {
      if (attachInput.files && attachInput.files.length) {
        attachPreview.hidden = false;
        attachPreview.textContent = '📎 ' + attachInput.files[0].name;
      } else {
        attachPreview.hidden = true;
        attachPreview.textContent = '';
      }
    });
  }

  // Simple reveal on scroll
  var reveals = document.querySelectorAll('.reveal');
  if (reveals.length && 'IntersectionObserver' in window) {
    var ro = new IntersectionObserver(function (entries) {
      entries.forEach(function (e) {
        if (e.isIntersecting) {
          e.target.style.opacity = '1';
          e.target.style.transform = 'translateY(0)';
          ro.unobserve(e.target);
        }
      });
    }, { threshold: 0.12 });
    reveals.forEach(function (el) {
      el.style.opacity = '0';
      el.style.transform = 'translateY(18px)';
      el.style.transition = 'opacity .6s ease, transform .6s ease';
      ro.observe(el);
    });
  }
});
