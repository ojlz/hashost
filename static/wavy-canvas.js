(function () {
  "use strict";

  var backgroundColor = "#000";
  var primaryColor = "0, 112, 243";
  var secondaryColor = "30, 30, 30";
  var accentColor = "0, 90, 200";
  var lineOpacity = 1;
  var animationSpeed = 0.004;

  var time = 0;
  var requestId = null;
  var mouse = { x: 0, y: 0 };

  var canvas = document.createElement("canvas");
  canvas.style.cssText = "position:fixed;top:0;left:0;width:100%;height:100%;z-index:-1;pointer-events:none";

  var wrapper = document.createElement("div");
  wrapper.style.cssText = "position:fixed;inset:0;width:100%;height:100%;overflow:hidden;background:" + backgroundColor + ";z-index:-1";
  wrapper.appendChild(canvas);

  var ctx = null;

  function initCanvas() {
    if (!document.body) {
      setTimeout(initCanvas, 50);
      return;
    }
    if (document.body.firstChild) {
      document.body.insertBefore(wrapper, document.body.firstChild);
    } else {
      document.body.appendChild(wrapper);
    }
    resizeCanvas();
    ctx = canvas.getContext("2d");
  }

  function resizeCanvas() {
    var dpr = window.devicePixelRatio || 1;
    canvas.width = window.innerWidth * dpr;
    canvas.height = window.innerHeight * dpr;
    canvas.style.width = window.innerWidth + "px";
    canvas.style.height = window.innerHeight + "px";
    if (ctx) ctx.scale(dpr, dpr);
  }

  var resizeTimer = null;
  function debouncedResize() {
    if (resizeTimer) clearTimeout(resizeTimer);
    resizeTimer = setTimeout(function () {
      resizeCanvas();
    }, 200);
  }

  window.addEventListener("resize", debouncedResize);

  function getMouseInfluence(x, y) {
    var dx = x - mouse.x;
    var dy = y - mouse.y;
    var distance = Math.sqrt(dx * dx + dy * dy);
    return Math.max(0, 1 - distance / 200);
  }

  canvas.addEventListener("mousemove", function (e) {
    mouse.x = e.clientX;
    mouse.y = e.clientY;
  });

  function animate() {
    if (!ctx) {
      requestId = requestAnimationFrame(animate);
      return;
    }

    time += animationSpeed;
    var width = window.innerWidth;
    var height = window.innerHeight;

    ctx.fillStyle = backgroundColor;
    ctx.fillRect(0, 0, width, height);

    var numPrimaryLines = 15;
    for (var i = 0; i < numPrimaryLines; i++) {
      var yPos = (i / numPrimaryLines) * height;
      var mouseInfl = getMouseInfluence(width / 2, yPos);
      var amplitude = 45 + 25 * Math.sin(time * 0.25 + i * 0.15) + mouseInfl * 25;
      var frequency = 0.006 + 0.002 * Math.sin(time * 0.12 + i * 0.08) + mouseInfl * 0.001;
      var speed = time * (0.6 + 0.3 * Math.sin(i * 0.12)) + mouseInfl * time * 0.3;
      var thickness = 0.6 + 0.4 * Math.sin(time + i * 0.25) + mouseInfl * 0.8;
      var opacity = (0.12 + 0.08 * Math.abs(Math.sin(time * 0.3 + i * 0.18)) + mouseInfl * 0.15) * lineOpacity;

      ctx.beginPath();
      ctx.lineWidth = thickness;
      ctx.strokeStyle = "rgba(" + primaryColor + "," + opacity + ")";

      for (var x = 0; x < width; x += 2) {
        var localMouseInfl = getMouseInfluence(x, yPos);
        var y = yPos + amplitude * Math.sin(x * frequency + speed) + localMouseInfl * Math.sin(time * 2 + x * 0.008) * 15;
        if (x === 0) ctx.moveTo(x, y);
        else ctx.lineTo(x, y);
      }
      ctx.stroke();
    }

    var numSecondaryLines = 10;
    for (var i = 0; i < numSecondaryLines; i++) {
      var xPos = (i / numSecondaryLines) * width;
      var mouseInfl = getMouseInfluence(xPos, height / 2);
      var amplitude = 40 + 20 * Math.sin(time * 0.18 + i * 0.14) + mouseInfl * 20;
      var frequency = 0.007 + 0.003 * Math.cos(time * 0.14 + i * 0.09) + mouseInfl * 0.002;
      var speed = time * (0.5 + 0.25 * Math.cos(i * 0.16)) + mouseInfl * time * 0.25;
      var thickness = 0.5 + 0.3 * Math.sin(time + i * 0.35) + mouseInfl * 0.7;
      var opacity = (0.1 + 0.06 * Math.abs(Math.sin(time * 0.28 + i * 0.2)) + mouseInfl * 0.12) * lineOpacity;

      ctx.beginPath();
      ctx.lineWidth = thickness;
      ctx.strokeStyle = "rgba(" + secondaryColor + "," + opacity + ")";

      for (var y = 0; y < height; y += 2) {
        var localMouseInfl = getMouseInfluence(xPos, y);
        var x = xPos + amplitude * Math.sin(y * frequency + speed) + localMouseInfl * Math.sin(time * 2 + y * 0.008) * 12;
        if (y === 0) ctx.moveTo(x, y);
        else ctx.lineTo(x, y);
      }
      ctx.stroke();
    }

    var numAccentLines = 6;
    for (var i = 0; i < numAccentLines; i++) {
      var offset = (i / numAccentLines) * width * 1.5 - width * 0.25;
      var amplitude = 30 + 15 * Math.cos(time * 0.22 + i * 0.12);
      var frequency = 0.01 + 0.004 * Math.sin(time * 0.16 + i * 0.1);
      var phase = time * (0.4 + 0.2 * Math.sin(i * 0.13));
      var thickness = 0.4 + 0.25 * Math.sin(time + i * 0.28);
      var opacity = (0.06 + 0.04 * Math.abs(Math.sin(time * 0.24 + i * 0.15))) * lineOpacity;

      ctx.beginPath();
      ctx.lineWidth = thickness;
      ctx.strokeStyle = "rgba(" + accentColor + "," + opacity + ")";

      var steps = 100;
      for (var j = 0; j <= steps; j++) {
        var progress = j / steps;
        var baseX = offset + progress * width;
        var baseY = progress * height + amplitude * Math.sin(progress * 6 + phase);
        var mouseInfl = getMouseInfluence(baseX, baseY);
        var x = baseX + mouseInfl * Math.sin(time * 1.5 + progress * 6) * 8;
        var y = baseY + mouseInfl * Math.cos(time * 1.5 + progress * 6) * 8;
        if (j === 0) ctx.moveTo(x, y);
        else ctx.lineTo(x, y);
      }
      ctx.stroke();
    }

    requestId = requestAnimationFrame(animate);
  }

  function startAnimation() {
    if (requestId) cancelAnimationFrame(requestId);
    animate();
  }

  document.addEventListener("visibilitychange", function () {
    if (document.hidden) {
      if (requestId) {
        cancelAnimationFrame(requestId);
        requestId = null;
      }
    } else {
      startAnimation();
    }
  });

  mouse.x = window.innerWidth / 2;
  mouse.y = window.innerHeight / 2;

  initCanvas();
  startAnimation();

  window.addEventListener("beforeunload", function () {
    if (requestId) cancelAnimationFrame(requestId);
  });
})();
