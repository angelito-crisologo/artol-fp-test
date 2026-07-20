(function(){
  function highlight(codeEl){
    var src = codeEl.textContent;
    var out = src.replace(/("(?:\\u[a-fA-F0-9]{4}|\\.|[^"\\])*"(\s*:)?|\b(?:true|false|null)\b|-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)/g, function(m){
      if (m[0] === '"') { return '<span class="' + (/:\s*$/.test(m) ? 'jk' : 'js') + '">' + m + '</span>'; }
      if (m === 'true' || m === 'false' || m === 'null') return '<span class="jb">' + m + '</span>';
      return '<span class="jn">' + m + '</span>';
    });
    codeEl.innerHTML = out;
  }
  var lazySet = new WeakSet();
  function ensureHighlighted(codeEl){
    if (!codeEl || lazySet.has(codeEl)) return;
    lazySet.add(codeEl);
    highlight(codeEl);
  }
  document.querySelectorAll('details.code-panel').forEach(function(det){
    var code = det.querySelector('code.lang-json');
    det.addEventListener('toggle', function(){ if (det.open) ensureHighlighted(code); });
  });

  document.addEventListener('click', function(e){
    var btn = e.target.closest('.copy-btn');
    if (!btn) return;
    e.preventDefault(); e.stopPropagation();
    var target = document.getElementById(btn.getAttribute('data-copy-target'));
    if (!target) return;
    var text = target.textContent;
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(text).then(function(){
        var old = btn.textContent;
        btn.textContent = 'Copied'; btn.setAttribute('data-copied', '1');
        setTimeout(function(){ btn.textContent = old; btn.removeAttribute('data-copied'); }, 1400);
      });
    }
  });

  document.querySelectorAll('.acc-toggle').forEach(function(btn){
    btn.addEventListener('click', function(){
      var group = btn.closest('.acc-group');
      var wasOpen = group.classList.contains('is-open');
      document.querySelectorAll('.acc-group').forEach(function(g){
        g.classList.remove('is-open');
        g.querySelector('.acc-toggle').setAttribute('aria-expanded', 'false');
      });
      if (!wasOpen) {
        group.classList.add('is-open');
        btn.setAttribute('aria-expanded', 'true');
      }
    });
  });

  document.querySelectorAll('.acc-group').forEach(function(group){
    var pills = group.querySelectorAll('.filter-pill');
    var cards = group.querySelectorAll('.thumb-card');
    var countEl = group.querySelector('.acc-count');
    var totalLabel = countEl.textContent;
    pills.forEach(function(pill){
      pill.addEventListener('click', function(){
        pills.forEach(function(p){ p.classList.remove('is-active'); });
        pill.classList.add('is-active');
        var shape = pill.getAttribute('data-shape');
        var shown = 0;
        cards.forEach(function(card){
          var match = (shape === 'all' || card.getAttribute('data-shape') === shape);
          card.hidden = !match;
          if (match) shown++;
        });
        countEl.textContent = (shape === 'all') ? totalLabel : shown + ' shown';
      });
    });
  });

  var gallery = document.getElementById('route-gallery');
  function applyRoute(){
    var m = /^#\/topology\/(.+)$/.exec(location.hash);
    var id = m ? decodeURIComponent(m[1]) : null;
    document.querySelectorAll('.route-detail').forEach(function(sec){ sec.hidden = true; });
    if (id) {
      var target = document.getElementById('page-' + id);
      if (target) {
        gallery.hidden = true;
        target.hidden = false;
        window.scrollTo(0, 0);
        return;
      }
    }
    gallery.hidden = false;
    window.scrollTo(0, 0);
  }
  window.addEventListener('hashchange', applyRoute);
  applyRoute();

  var lightbox = document.createElement('div');
  lightbox.className = 'lightbox-overlay';
  lightbox.hidden = true;
  lightbox.innerHTML = '<button class="lightbox-close" type="button" aria-label="Close">✕</button>' +
    '<img class="lightbox-img" alt="">';
  document.body.appendChild(lightbox);
  var lightboxImg = lightbox.querySelector('.lightbox-img');
  var lightboxReturnFocus = null;

  function openLightbox(img){
    lightboxImg.src = img.currentSrc || img.src;
    lightboxImg.alt = img.alt || '';
    lightbox.hidden = false;
    lightboxReturnFocus = document.activeElement;
    lightbox.querySelector('.lightbox-close').focus();
  }
  function closeLightbox(){
    if (lightbox.hidden) return;
    lightbox.hidden = true;
    lightboxImg.src = '';
    if (lightboxReturnFocus && lightboxReturnFocus.focus) lightboxReturnFocus.focus();
  }

  document.addEventListener('click', function(e){
    var img = e.target.closest('.plan-sheet-body img');
    if (img) { openLightbox(img); return; }
    if (!lightbox.hidden && e.target.closest('.lightbox-overlay')) { closeLightbox(); }
  });
  document.addEventListener('keydown', function(e){
    if (e.key === 'Escape' && !lightbox.hidden) closeLightbox();
  });
})();
