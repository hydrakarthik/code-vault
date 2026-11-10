(function () {
  'use strict';

  var canvas = document.getElementById('hero-wave');
  if (!canvas) { return; }
  var ctx = canvas.getContext('2d');
  if (!ctx) { return; }

  var COLS = 90;
  var ROWS = 34;
  var reduced = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  var w = 0;
  var h = 0;
  var resizePending = false;

  function resize() {
    var dpr = Math.min(window.devicePixelRatio || 1, 2);
    w = canvas.clientWidth;
    h = canvas.clientHeight;
    canvas.width = Math.max(1, Math.round(w * dpr));
    canvas.height = Math.max(1, Math.round(h * dpr));
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  }

  function draw(t) {
    ctx.clearRect(0, 0, w, h);
    for (var j = 0; j < ROWS; j++) {
      var v = j / (ROWS - 1);
      var ys = [];
      var xs = [];
      for (var i = 0; i < COLS; i++) {
        var u = i / (COLS - 1) * 2 - 1;
        var x = w / 2 + u * w * (0.6 + 0.9 * v);
        var baseY = h * (0.18 + 0.85 * Math.pow(v, 1.6));
        var height = Math.sin(u * 3.2 + t * 0.6) * 0.5 +
          Math.sin(u * 1.3 - v * 4 + t * 0.4) * 0.7 +
          Math.cos(v * 5 + t * 0.3) * 0.3 + u * 0.6 + 0.8;
        xs.push(x);
        ys.push(baseY - height * (8 + 30 * v));
      }
      ctx.strokeStyle = 'rgba(200,210,235,' + (0.04 + 0.1 * v) + ')';
      ctx.lineWidth = 1;
      ctx.beginPath();
      for (var k = 0; k < COLS; k++) {
        if (k === 0) { ctx.moveTo(xs[k], ys[k]); } else { ctx.lineTo(xs[k], ys[k]); }
      }
      ctx.stroke();
      var size = 0.6 + 1.4 * v;
      ctx.fillStyle = 'rgba(200,210,235,' + (0.15 + 0.6 * v) + ')';
      for (var m = 0; m < COLS; m++) {
        ctx.fillRect(xs[m] - size / 2, ys[m] - size / 2, size, size);
      }
    }
  }

  resize();

  window.addEventListener('resize', function () {
    if (resizePending) { return; }
    resizePending = true;
    window.requestAnimationFrame(function () {
      resizePending = false;
      resize();
      if (reduced) { draw(0); }
    });
  });

  if (reduced) {
    draw(0);
    return;
  }

  var start = null;
  function frame(now) {
    if (start === null) { start = now; }
    if (!document.hidden) {
      draw((now - start) / 1000 * 0.6);
    }
    window.requestAnimationFrame(frame);
  }
  window.requestAnimationFrame(frame);
})();
