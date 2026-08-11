(function () {
  "use strict";

  const data = window.GADE_SITE_DATA;
  if (!data) {
    throw new Error("GADE_SITE_DATA was not loaded");
  }

  const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  const formatScore = (value, precision = 1) => Number(value).toFixed(precision);

  function isTypingTarget(target) {
    if (!(target instanceof Element)) return false;
    return Boolean(target.closest("input, textarea, select, button, [contenteditable='true']"));
  }

  function scrollToTrajectory(focusPlay = true) {
    const target = document.querySelector("#trajectory");
    if (!target) return;
    const nav = document.querySelector(".site-nav");
    const offset = (nav ? nav.getBoundingClientRect().bottom : 76) + 22;
    const top = Math.max(0, target.getBoundingClientRect().top + window.scrollY - offset);
    window.scrollTo({ top, behavior: reducedMotion ? "auto" : "smooth" });
    if (focusPlay) {
      window.setTimeout(() => document.querySelector("#playTrajectory")?.focus(), reducedMotion ? 0 : 520);
    }
  }

  document.querySelector("#exampleLink")?.addEventListener("click", (event) => {
    event.preventDefault();
    scrollToTrajectory(true);
  });

  document.addEventListener("keydown", (event) => {
    if (event.defaultPrevented || event.metaKey || event.ctrlKey || event.altKey) return;
    if (event.key.toLowerCase() === "e" && !isTypingTarget(event.target)) {
      event.preventDefault();
      scrollToTrajectory(true);
    }
  });

  document.querySelectorAll(".site-nav a[href^='#'], .brand[href^='#']").forEach((link) => {
    link.addEventListener("click", (event) => {
      const selector = link.getAttribute("href");
      const target = selector ? document.querySelector(selector) : null;
      if (!target) return;
      event.preventDefault();
      const nav = document.querySelector(".site-nav");
      const offset = (nav ? nav.getBoundingClientRect().bottom : 76) + 22;
      const top = Math.max(0, target.getBoundingClientRect().top + window.scrollY - offset);
      window.scrollTo({ top, behavior: reducedMotion ? "auto" : "smooth" });
      history.replaceState(null, "", selector);
    });
  });

  const progress = document.querySelector("#readProgress");
  function updateProgress() {
    if (!progress) return;
    const root = document.documentElement;
    const available = root.scrollHeight - root.clientHeight;
    progress.style.width = `${available > 0 ? (root.scrollTop / available) * 100 : 0}%`;
  }
  document.addEventListener("scroll", updateProgress, { passive: true });
  updateProgress();

  const revealItems = [...document.querySelectorAll(".reveal")];
  if (reducedMotion || !("IntersectionObserver" in window)) {
    revealItems.forEach((item) => item.classList.add("is-visible"));
  } else {
    const observer = new IntersectionObserver((entries) => {
      entries.forEach((entry) => {
        if (entry.isIntersecting) {
          entry.target.classList.add("is-visible");
          observer.unobserve(entry.target);
        }
      });
    }, { threshold: 0.05, rootMargin: "0px 0px -30px" });
    revealItems.forEach((item) => observer.observe(item));
    window.setTimeout(() => revealItems.forEach((item) => item.classList.add("is-visible")), 2500);
  }

  function renderHeroScores() {
    const root = document.querySelector("#heroScores");
    if (!root) return;
    root.innerHTML = data.heroScores.map((score) => `
      <div class="score-row">
        <div><strong>${score.label}</strong><small>${score.detail}</small></div>
        <div class="score-value">${formatScore(score.value, score.precision)}<span>%</span></div>
      </div>`).join("");
  }

  function barsMarkup(models) {
    return models.map((model) => {
      const precision = model.baseline % 1 === 0 && model.evolve % 1 === 0 ? 1 : 2;
      const lift = model.evolve - model.baseline;
      return `
        <div class="bar-group">
          <span class="bar-name">${model.name}</span>
          <div class="bar-track"><div class="bar-fill" style="--value:${model.baseline}"></div><span class="bar-type">base</span></div>
          <span class="bar-value">${formatScore(model.baseline, precision)}</span>
          <div class="bar-track"><div class="bar-fill evolve" style="--value:${model.evolve}"></div><span class="bar-type">ARM</span></div>
          <span class="bar-value evolve">${formatScore(model.evolve, precision)}</span>
          <span class="lift-label">+${lift.toFixed(2).replace(/0$/, "")} percentage points</span>
        </div>`;
    }).join("");
  }

  function pairedTable(title, models, includeGt) {
    const rows = models.map((model) => `<tr><td>${model.name}</td><td>${model.baseline}%</td><td>${model.evolve}%</td></tr>`).join("");
    const gt = includeGt ? `<tr><td>GT Judge · reference upper bound</td><td>—</td><td>${includeGt}%</td></tr>` : "";
    return `<table><caption>${title}</caption><thead><tr><th>Model</th><th>Baseline</th><th>Self-Evolve</th></tr></thead><tbody>${rows}${gt}</tbody></table>`;
  }

  function renderResults() {
    const osworld = data.benchmarks.osworld;
    const windows = data.benchmarks.windows;
    document.querySelector("#osworldBars").innerHTML = barsMarkup(osworld.models);
    document.querySelector("#windowsBars").innerHTML = barsMarkup(windows.models);
    document.querySelector("#osworldTable").innerHTML = pairedTable(osworld.title, osworld.models);
    document.querySelector("#windowsTable").innerHTML = pairedTable(windows.title, windows.models, windows.gtJudge);
    document.querySelector("#gtJudge").innerHTML = `<span>GT Judge · reference upper bound</span><strong>${windows.gtJudge}%</strong>`;

    const gui = data.benchmarks.guiCoding;
    document.querySelector("#guiCoding").innerHTML = `
      <div class="slope-point"><strong>${gui[0].value}%</strong><span>${gui[0].label}</span></div>
      <div class="slope-arrow" aria-hidden="true">→</div>
      <div class="slope-point"><strong>${gui[1].value}%</strong><span>${gui[1].label}</span></div>`;

    const scaling = data.benchmarks.scaling;
    document.querySelector("#scalingTable").innerHTML = `<table><caption>Wide scaling comparison</caption><thead><tr><th>Method</th><th>Rollouts</th><th>Success rate</th></tr></thead><tbody>${scaling.map((point) => `<tr><td>${point.method}</td><td>${point.rollouts}</td><td>${point.score}%</td></tr>`).join("")}</tbody></table>`;
  }

  function drawScalingChart() {
    const canvas = document.querySelector("#scalingChart");
    if (!canvas) return;
    const rect = canvas.getBoundingClientRect();
    if (!rect.width) return;
    const ratio = Math.min(window.devicePixelRatio || 1, 2);
    canvas.width = Math.round(rect.width * ratio);
    canvas.height = Math.round(rect.height * ratio);
    const context = canvas.getContext("2d");
    context.scale(ratio, ratio);

    const width = rect.width;
    const height = rect.height;
    const pad = { left: 44, right: 24, top: 26, bottom: 38 };
    const plotWidth = width - pad.left - pad.right;
    const plotHeight = height - pad.top - pad.bottom;
    const xMin = 300, xMax = 1600, yMin = 65, yMax = 76;
    const x = (value) => pad.left + ((value - xMin) / (xMax - xMin)) * plotWidth;
    const y = (value) => pad.top + plotHeight - ((value - yMin) / (yMax - yMin)) * plotHeight;
    const css = getComputedStyle(document.documentElement);
    const colors = {
      line: css.getPropertyValue("--line").trim(),
      ink: css.getPropertyValue("--ink").trim(),
      muted: css.getPropertyValue("--muted").trim(),
      arm: css.getPropertyValue("--violet").trim(),
      wide: css.getPropertyValue("--blue").trim()
    };

    context.clearRect(0, 0, width, height);
    context.font = "9px 'Google Sans Code', monospace";
    context.textBaseline = "middle";
    [66, 69, 72, 75].forEach((tick) => {
      const py = y(tick);
      context.strokeStyle = colors.line;
      context.lineWidth = 1;
      context.beginPath();
      context.moveTo(pad.left, py);
      context.lineTo(width - pad.right, py);
      context.stroke();
      context.fillStyle = colors.muted;
      context.textAlign = "right";
      context.fillText(`${tick}%`, pad.left - 8, py);
    });
    [316, 470, 1000, 1580].forEach((tick) => {
      const px = x(tick);
      context.fillStyle = colors.muted;
      context.textAlign = "center";
      context.fillText(String(tick), px, height - 16);
    });

    const [baseline, arm, wide] = data.benchmarks.scaling;
    const drawPath = (target, color, lineWidth) => {
      context.strokeStyle = color;
      context.lineWidth = lineWidth;
      context.beginPath();
      context.moveTo(x(baseline.rollouts), y(baseline.score));
      context.lineTo(x(target.rollouts), y(target.score));
      context.stroke();
    };
    drawPath(wide, colors.wide, 2.5);
    drawPath(arm, colors.arm, 4);

    [baseline, arm, wide].forEach((point) => {
      const color = point.series === "arm" ? colors.arm : point.series === "wide" ? colors.wide : colors.ink;
      context.fillStyle = color;
      context.beginPath();
      context.arc(x(point.rollouts), y(point.score), point.series === "arm" ? 6 : 5, 0, Math.PI * 2);
      context.fill();
      context.textAlign = point.series === "wide" ? "right" : "left";
      context.textBaseline = "bottom";
      context.font = "600 9px 'Google Sans Code', monospace";
      const labelX = point.series === "wide" ? x(point.rollouts) - 8 : x(point.rollouts) + 8;
      context.fillText(`${point.method} · ${point.score}%`, labelX, y(point.score) - 6);
    });
  }

  function matrixMarkup(matrix) {
    return `<div class="matrix" aria-label="Confusion matrix">
      <span></span><span>ARM=1</span><span>ARM=0</span>
      <span>GT=1</span><span class="matrix-good">TP ${matrix.tp}</span><span class="matrix-bad">FN ${matrix.fn}</span>
      <span>GT=0</span><span class="matrix-bad">FP ${matrix.fp}</span><span class="matrix-good">TN ${matrix.tn}</span>
    </div>`;
  }

  function renderDiagnostics() {
    const root = document.querySelector("#diagnosticCards");
    root.innerHTML = Object.values(data.diagnostics).map((item) => `
      <details class="diagnostic-card">
        <summary>${item.title}</summary>
        <div class="diagnostic-body">
          <div class="metric-grid">${item.metrics.map(([label, value]) => `<div class="metric"><span>${label}</span><strong>${value}</strong></div>`).join("")}</div>
          ${matrixMarkup(item.matrix)}
        </div>
      </details>`).join("");
  }

  const assetUrl = (path) => new URL(path, document.baseURI).href;

  function buildLoopDemo() {
    const demo = document.querySelector("#loopDemo");
    if (!demo || !data.loopDemo?.phases?.length) return;
    const phases = data.loopDemo.phases;
    const image = document.querySelector("#loopImage");
    const event = document.querySelector("#loopEvent");
    const phaseLabel = document.querySelector("#loopPhase");
    const title = document.querySelector("#loopTitle");
    const detail = document.querySelector("#loopDetail");
    const episode = document.querySelector("#loopEpisode");
    const rail = document.querySelector("#loopRail");
    const toggle = document.querySelector("#loopToggle");
    let index = 0;
    let timer = null;
    let playing = false;

    phases.forEach((phase, phaseIndex) => {
      const button = document.createElement("button");
      button.type = "button";
      button.setAttribute("aria-label", `Show ${phase.phase}: ${phase.title}`);
      button.addEventListener("click", () => {
        pause();
        index = phaseIndex;
        render();
      });
      rail.appendChild(button);
    });

    function render() {
      const current = phases[index];
      demo.classList.add("is-changing");
      window.setTimeout(() => {
        const nextUrl = assetUrl(current.image);
        if (image.src !== nextUrl) image.src = nextUrl;
        image.alt = `${current.phase}: ${current.title}`;
        event.dataset.tone = current.tone;
        phaseLabel.textContent = current.phase;
        title.textContent = current.title;
        detail.textContent = current.detail;
        episode.textContent = current.episode;
        [...rail.children].forEach((button, buttonIndex) => {
          button.classList.toggle("active", buttonIndex === index && playing);
          button.classList.toggle("complete", buttonIndex < index || (buttonIndex === index && !playing));
        });
        demo.classList.remove("is-changing");
      }, reducedMotion ? 0 : 120);
    }

    function play() {
      if (playing) return;
      playing = true;
      toggle.textContent = "Pause";
      toggle.setAttribute("aria-label", "Pause self-evolve example");
      render();
      timer = window.setInterval(() => {
        index = (index + 1) % phases.length;
        render();
      }, data.loopDemo.interval);
    }

    function pause() {
      window.clearInterval(timer);
      timer = null;
      playing = false;
      toggle.textContent = "Play";
      toggle.setAttribute("aria-label", "Play self-evolve example");
      render();
    }

    toggle.addEventListener("click", () => playing ? pause() : play());
    phases.forEach((phase) => {
      const candidate = new Image();
      candidate.src = assetUrl(phase.image);
    });
    render();

    if (reducedMotion) return;
    if ("IntersectionObserver" in window) {
      const observer = new IntersectionObserver((entries) => {
        const visible = entries.some((entry) => entry.isIntersecting);
        if (visible && !playing) play();
        if (!visible && playing) pause();
      }, { threshold: 0.2 });
      observer.observe(demo);
    } else {
      play();
    }
  }

  function buildTrajectory() {
    const trajectories = data.trajectories;
    if (!Array.isArray(trajectories) || trajectories.length === 0) return;
    const player = document.querySelector("#trajectoryPlayer");
    const image = document.querySelector("#trajectoryImage");
    const imageError = document.querySelector("#trajectoryImageError");
    const marker = document.querySelector("#clickMarker");
    const stepText = document.querySelector("#screenStep");
    const environment = document.querySelector("#trajectoryEnvironment");
    const title = document.querySelector("#trajectoryTitle");
    const instruction = document.querySelector("#trajectoryInstruction");
    const actionType = document.querySelector("#actionType");
    const actionLabel = document.querySelector("#actionLabel");
    const armVerdict = document.querySelector("#armVerdict");
    const range = document.querySelector("#trajectoryRange");
    const play = document.querySelector("#playTrajectory");
    const previous = document.querySelector("#previousStep");
    const next = document.querySelector("#nextStep");
    const speed = document.querySelector("#trajectorySpeed");
    const timeline = document.querySelector("#trajectoryTimeline");
    const tabs = document.querySelector("#caseTabs");
    let trajectory = trajectories[0];
    let frames = trajectory.frames;
    let index = 0;
    let timer = null;
    let preloaded = new Set();

    image.addEventListener("load", () => {
      image.hidden = false;
      imageError.hidden = true;
      image.dataset.failed = "";
    });
    image.addEventListener("error", () => {
      image.hidden = true;
      imageError.hidden = false;
      image.dataset.failed = image.src;
    });

    function preload(frameIndex) {
      const frame = frames[frameIndex];
      if (!frame || preloaded.has(frame.image)) return;
      const candidate = new Image();
      candidate.src = assetUrl(frame.image);
      preloaded.add(frame.image);
    }

    function stop() {
      window.clearInterval(timer);
      timer = null;
      play.textContent = "Play";
      play.setAttribute("aria-label", "Play trajectory");
    }

    function render({ preloadAdjacent = true } = {}) {
      const frame = frames[index];
      const nextUrl = assetUrl(frame.image);
      if (image.src !== nextUrl || image.dataset.failed === nextUrl) {
        image.hidden = false;
        imageError.hidden = true;
        image.src = nextUrl;
      }
      image.alt = `${trajectory.environment} step ${index + 1}: ${frame.actionLabel}`;
      stepText.textContent = `STEP ${String(index + 1).padStart(2, "0")} / ${String(frames.length).padStart(2, "0")} · EPISODE ${String(frame.episode).padStart(2, "0")}`;
      actionType.textContent = frame.actionType === "task" ? "INITIAL STATE" : `${frame.actionType.toUpperCase()} ACTION`;
      actionLabel.textContent = frame.actionLabel;
      range.value = String(index);
      previous.disabled = index === 0;
      next.disabled = index === frames.length - 1;
      [...timeline.children].forEach((button, buttonIndex) => button.classList.toggle("active", buttonIndex === index));
      if (frame.point) {
        marker.hidden = false;
        marker.style.left = `${frame.point.x * 100}%`;
        marker.style.top = `${frame.point.y * 100}%`;
      } else {
        marker.hidden = true;
      }
      if (frame.arm) {
        armVerdict.hidden = false;
        armVerdict.className = `arm-verdict ${frame.arm.tone === "retry" ? "retry" : ""}`.trim();
        armVerdict.innerHTML = `
          <div class="verdict-top"><span>ARM CHECKPOINT · EPISODE ${String(frame.episode).padStart(2, "0")}</span><b>${frame.arm.verdict}</b></div>
          <ul>${frame.arm.checklist.map((item) => `<li>${item}</li>`).join("")}</ul>
          <p>${frame.arm.rationale}</p>
          <small>NEXT · ${frame.arm.next}</small>`;
      } else {
        armVerdict.hidden = true;
        armVerdict.innerHTML = "";
      }
      if (preloadAdjacent) preload(index + 1);
    }

    function rebuildTimeline() {
      timeline.innerHTML = "";
      timeline.style.setProperty("--timeline-count", frames.length);
      frames.forEach((frame, frameIndex) => {
        const button = document.createElement("button");
        button.type = "button";
        button.className = frame.arm ? "checkpoint" : "";
        button.setAttribute("aria-label", `Show trajectory step ${frameIndex + 1}: ${frame.actionLabel}`);
        button.innerHTML = `<span>${String(frameIndex + 1).padStart(2, "0")} · E${frame.episode}</span><small>${frame.actionLabel}</small>`;
        button.addEventListener("click", () => {
          stop();
          index = frameIndex;
          render();
        });
        timeline.appendChild(button);
      });
    }

    function loadTrajectory(caseIndex) {
      stop();
      trajectory = trajectories[caseIndex];
      frames = trajectory.frames;
      index = 0;
      preloaded = new Set();
      environment.textContent = trajectory.environment.toUpperCase();
      title.textContent = trajectory.title;
      instruction.textContent = `“${trajectory.instruction}”`;
      range.max = String(frames.length - 1);
      [...tabs.children].forEach((button, buttonIndex) => {
        const selected = buttonIndex === caseIndex;
        button.setAttribute("aria-selected", String(selected));
        button.tabIndex = selected ? 0 : -1;
      });
      rebuildTimeline();
      render();
      preload(1);
    }

    trajectories.forEach((item, caseIndex) => {
      const button = document.createElement("button");
      button.type = "button";
      button.setAttribute("role", "tab");
      button.innerHTML = `<span>${item.tabLabel}</span><small>${item.environment}</small>`;
      button.addEventListener("click", () => loadTrajectory(caseIndex));
      tabs.appendChild(button);
    });

    function move(delta) {
      stop();
      index = Math.max(0, Math.min(frames.length - 1, index + delta));
      render();
    }
    previous.addEventListener("click", () => move(-1));
    next.addEventListener("click", () => move(1));
    range.addEventListener("input", () => {
      stop();
      index = Number(range.value);
      render();
    });
    play.addEventListener("click", () => {
      if (timer) {
        stop();
        return;
      }
      if (index === frames.length - 1) index = 0;
      render();
      play.textContent = "Pause";
      play.setAttribute("aria-label", "Pause trajectory");
      const interval = 1650 / Number(speed.value);
      timer = window.setInterval(() => {
        if (index >= frames.length - 1) {
          stop();
          return;
        }
        index += 1;
        render();
      }, interval);
    });
    speed.addEventListener("change", () => {
      if (timer) {
        stop();
        play.click();
      }
    });
    player.addEventListener("keydown", (event) => {
      if (event.key === "ArrowLeft" && !isTypingTarget(event.target)) {
        event.preventDefault();
        move(-1);
      } else if (event.key === "ArrowRight" && !isTypingTarget(event.target)) {
        event.preventDefault();
        move(1);
      } else if (event.code === "Space" && event.target === player) {
        event.preventDefault();
        play.click();
      }
    });

    if ("IntersectionObserver" in window) {
      const trajectoryObserver = new IntersectionObserver((entries) => {
        if (entries.some((entry) => entry.isIntersecting)) {
          preload(1);
          trajectoryObserver.disconnect();
        }
      }, { rootMargin: "120px" });
      trajectoryObserver.observe(player);
    }
    loadTrajectory(0);
  }

  renderHeroScores();
  renderResults();
  renderDiagnostics();
  buildLoopDemo();
  buildTrajectory();
  drawScalingChart();
  let resizeTimer;
  window.addEventListener("resize", () => {
    window.clearTimeout(resizeTimer);
    resizeTimer = window.setTimeout(drawScalingChart, 100);
  });
  window.__siteReady = true;
})();
