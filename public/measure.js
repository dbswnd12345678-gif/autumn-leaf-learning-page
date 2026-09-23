(function () {
  const SVG_NS = "http://www.w3.org/2000/svg";
  const overlays = {
    1: document.getElementById("overlay-1"),
    2: document.getElementById("overlay-2"),
  };
  const slots = {
    1: document.getElementById("image-slot-1"),
    2: document.getElementById("image-slot-2"),
  };
  const images = {
    1: document.getElementById("main-image"),
    2: document.getElementById("compare-image"),
  };
  const statusEl = document.getElementById("measure-status");
  const listEl = document.getElementById("measure-list");
  const chatInput = document.getElementById("chat-input");
  const toolButtons = document.querySelectorAll(".tool-btn[data-tool]");
  let I18N = {};
  try {
    I18N = JSON.parse(document.getElementById("measure-i18n").textContent);
  } catch (err) {
    I18N = {};
  }

  function t(key, vars) {
    let text = I18N[key] || key;
    if (vars) {
      Object.keys(vars).forEach((k) => {
        text = text.replace("{" + k + "}", vars[k]);
      });
    }
    return text;
  }

  let tool = "select";
  let measurements = [];
  let draft = [];
  let draftSlot = null;
  let hoverPt = null;
  let idSeq = 1;
  let lastImages = { 1: "", 2: "" };

  function currentImage(slotKey) {
    const slot = slots[slotKey];
    const img = images[slotKey];
    if (!slot || slot.classList.contains("hidden") || !img || !img.src) return "";
    try {
      const name = new URL(img.src, window.location.href).pathname.split("/").pop();
      return decodeURIComponent(name || "");
    } catch (err) {
      return "";
    }
  }

  function visibleImageSet() {
    return new Set([currentImage(1), currentImage(2)].filter(Boolean));
  }

  function visibleMeasurements() {
    const shown = visibleImageSet();
    return measurements.filter((m) => shown.has(m.image));
  }

  function slotForImage(file) {
    if (file && currentImage(1) === file) return 1;
    if (file && currentImage(2) === file) return 2;
    return null;
  }

  function syncImages() {
    const next = { 1: currentImage(1), 2: currentImage(2) };
    if (draftSlot && lastImages[draftSlot] && lastImages[draftSlot] !== next[draftSlot]) {
      draft = [];
      draftSlot = null;
      hoverPt = null;
    }
    lastImages = next;
  }

  function setStatus(text) {
    if (statusEl) statusEl.textContent = text;
  }

  function setTool(next) {
    tool = next;
    draft = [];
    draftSlot = null;
    hoverPt = null;
    toolButtons.forEach((btn) => {
      btn.classList.toggle("active", btn.dataset.tool === tool);
    });
    Object.values(slots).forEach((slot) => {
      if (!slot) return;
      slot.classList.toggle("measuring", tool !== "select");
    });
    if (tool === "ruler") setStatus(t("rulerStart"));
    else if (tool === "protractor") setStatus(t("angleStart"));
    else setStatus(t("idle"));
    renderAll();
  }

  function displayedImageBox(slotKey) {
    const img = images[slotKey];
    const slot = slots[slotKey];
    if (!img || !slot || !img.naturalWidth || !img.naturalHeight) return null;
    const cw = slot.clientWidth;
    const ch = slot.clientHeight;
    if (cw < 1 || ch < 1) return null;
    const scale = Math.min(cw / img.naturalWidth, ch / img.naturalHeight);
    const width = img.naturalWidth * scale;
    const height = img.naturalHeight * scale;
    return {
      left: (cw - width) / 2,
      top: (ch - height) / 2,
      width: width,
      height: height,
    };
  }

  function eventToSlot(slot, event) {
    const rect = slot.getBoundingClientRect();
    const sx = rect.width ? slot.clientWidth / rect.width : 1;
    const sy = rect.height ? slot.clientHeight / rect.height : 1;
    return {
      x: (event.clientX - rect.left) * sx,
      y: (event.clientY - rect.top) * sy,
    };
  }

  function toNormalized(slotKey, x, y) {
    const box = displayedImageBox(slotKey);
    if (!box || box.width < 1 || box.height < 1) return null;
    const nx = (x - box.left) / box.width;
    const ny = (y - box.top) / box.height;
    if (nx < -0.02 || ny < -0.02 || nx > 1.02 || ny > 1.02) {
      return null;
    }
    return {
      nx: Math.min(1, Math.max(0, nx)),
      ny: Math.min(1, Math.max(0, ny)),
    };
  }

  function fromNormalized(slotKey, pt) {
    const box = displayedImageBox(slotKey);
    if (!box) return null;
    return {
      x: box.left + pt.nx * box.width,
      y: box.top + pt.ny * box.height,
    };
  }

  function relativeLength(slotKey, p0, p1) {
    const img = images[slotKey];
    if (!img || !img.naturalWidth) return 0;
    const aspect = img.naturalHeight / img.naturalWidth;
    const dx = (p1.nx - p0.nx) * 1000;
    const dy = (p1.ny - p0.ny) * 1000 * aspect;
    return Math.round(Math.hypot(dx, dy));
  }

  function svgEl(name, attrs) {
    const el = document.createElementNS(SVG_NS, name);
    Object.entries(attrs).forEach(([k, v]) => el.setAttribute(k, String(v)));
    return el;
  }

  function dist(a, b) {
    return Math.hypot(b.x - a.x, b.y - a.y);
  }

  function angleDeg(a, vertex, c) {
    const v1x = a.x - vertex.x;
    const v1y = a.y - vertex.y;
    const v2x = c.x - vertex.x;
    const v2y = c.y - vertex.y;
    const d1 = Math.hypot(v1x, v1y);
    const d2 = Math.hypot(v2x, v2y);
    if (d1 < 1 || d2 < 1) return 0;
    const cos = (v1x * v2x + v1y * v2y) / (d1 * d2);
    return Math.acos(Math.min(1, Math.max(-1, cos))) * (180 / Math.PI);
  }

  function polarAngle(from, to) {
    return Math.atan2(to.y - from.y, to.x - from.x);
  }

  function formatAngle(deg) {
    return Math.round(deg * 10) / 10;
  }

  function addMeasurement(item) {
    measurements.push(item);
    renderList();
    renderAll();
  }

  function listLabel(m) {
    const slot = slotForImage(m.image) || m.slot;
    if (m.type === "length") return t("labelLength", { slot: slot, value: m.value });
    return t("labelAngle", { slot: slot, value: m.value });
  }

  function renderList() {
    if (!listEl) return;
    listEl.innerHTML = "";
    visibleMeasurements().forEach((m, i) => {
      const item = document.createElement("li");
      item.textContent = (i + 1) + ". " + listLabel(m);
      listEl.appendChild(item);
    });
  }

  function clampLabel(slotKey, x, y) {
    const box = displayedImageBox(slotKey);
    if (!box) return { x: x, y: y };
    return {
      x: Math.min(box.left + box.width - 16, Math.max(box.left + 16, x)),
      y: Math.min(box.top + box.height - 10, Math.max(box.top + 10, y)),
    };
  }

  function drawLabel(svg, slotKey, x, y, text, color) {
    const pos = clampLabel(slotKey, x, y);
    const size = 11;
    const tw = Math.max(22, text.length * size * 0.62);
    const th = 16;
    svg.appendChild(svgEl("rect", {
      x: pos.x - tw / 2,
      y: pos.y - th / 2,
      width: tw,
      height: th,
      rx: 4,
      fill: "rgba(255,255,255,0.94)",
      stroke: color,
      "stroke-width": 1,
    }));
    const label = svgEl("text", {
      x: pos.x,
      y: pos.y + 1,
      fill: color,
      "font-size": size,
      "font-weight": 700,
      "text-anchor": "middle",
      "dominant-baseline": "middle",
      "font-family": "Malgun Gothic, Apple SD Gothic Neo, Segoe UI, sans-serif",
    });
    label.textContent = text;
    svg.appendChild(label);
  }

  function drawPoint(svg, p, color) {
    svg.appendChild(svgEl("circle", {
      cx: p.x, cy: p.y, r: 3.5, fill: "#fff", stroke: color, "stroke-width": 1.5,
    }));
  }

  function drawLength(svg, slotKey, a, b, color, label) {
    svg.appendChild(svgEl("line", {
      x1: a.x, y1: a.y, x2: b.x, y2: b.y,
      stroke: "#fff", "stroke-width": 3, "stroke-linecap": "round",
    }));
    svg.appendChild(svgEl("line", {
      x1: a.x, y1: a.y, x2: b.x, y2: b.y,
      stroke: color, "stroke-width": 1.75, "stroke-linecap": "round",
    }));
    drawPoint(svg, a, color);
    drawPoint(svg, b, color);
    const mx = (a.x + b.x) / 2;
    const my = (a.y + b.y) / 2;
    const dx = b.x - a.x;
    const dy = b.y - a.y;
    const len = Math.hypot(dx, dy) || 1;
    const ox = (-dy / len) * 11;
    const oy = (dx / len) * 11;
    drawLabel(svg, slotKey, mx + ox, my + oy, label, color);
  }

  function drawAngle(svg, slotKey, a, v, c, color, label) {
    svg.appendChild(svgEl("line", {
      x1: v.x, y1: v.y, x2: a.x, y2: a.y, stroke: "#fff", "stroke-width": 3,
    }));
    svg.appendChild(svgEl("line", {
      x1: v.x, y1: v.y, x2: c.x, y2: c.y, stroke: "#fff", "stroke-width": 3,
    }));
    svg.appendChild(svgEl("line", {
      x1: v.x, y1: v.y, x2: a.x, y2: a.y, stroke: color, "stroke-width": 1.75,
    }));
    svg.appendChild(svgEl("line", {
      x1: v.x, y1: v.y, x2: c.x, y2: c.y, stroke: color, "stroke-width": 1.75,
    }));
    const r = Math.min(26, dist(a, v) * 0.42, dist(c, v) * 0.42);
    const start = polarAngle(v, a);
    let delta = polarAngle(v, c) - start;
    while (delta <= -Math.PI) delta += Math.PI * 2;
    while (delta > Math.PI) delta -= Math.PI * 2;
    const large = Math.abs(delta) > Math.PI ? 1 : 0;
    const sweep = delta >= 0 ? 1 : 0;
    const x1 = v.x + r * Math.cos(start);
    const y1 = v.y + r * Math.sin(start);
    const x2 = v.x + r * Math.cos(start + delta);
    const y2 = v.y + r * Math.sin(start + delta);
    svg.appendChild(svgEl("path", {
      d: "M " + x1 + " " + y1 + " A " + r + " " + r + " 0 " + large + " " + sweep + " " + x2 + " " + y2,
      fill: "none", stroke: "#fff", "stroke-width": 3,
    }));
    svg.appendChild(svgEl("path", {
      d: "M " + x1 + " " + y1 + " A " + r + " " + r + " 0 " + large + " " + sweep + " " + x2 + " " + y2,
      fill: "none", stroke: color, "stroke-width": 1.75,
    }));
    drawPoint(svg, a, color);
    drawPoint(svg, v, color);
    drawPoint(svg, c, color);
    const bisect = start + delta / 2;
    const tx = v.x + (r + 14) * Math.cos(bisect);
    const ty = v.y + (r + 14) * Math.sin(bisect);
    drawLabel(svg, slotKey, tx, ty, label, color);
  }

  function syncViewBox(overlay, slotKey) {
    const slot = slots[slotKey];
    const w = (slot && slot.clientWidth) || overlay.clientWidth || 1;
    const h = (slot && slot.clientHeight) || overlay.clientHeight || 1;
    overlay.setAttribute("viewBox", "0 0 " + w + " " + h);
    overlay.setAttribute("preserveAspectRatio", "none");
    overlay.setAttribute("width", String(w));
    overlay.setAttribute("height", String(h));
  }

  function renderOverlay(slotKey) {
    const overlay = overlays[slotKey];
    if (!overlay) return;
    overlay.innerHTML = "";
    syncViewBox(overlay, slotKey);
    const colorLength = "#c0521b";
    const colorAngle = "#2f7dc0";

    const imageName = currentImage(slotKey);
    measurements.forEach((m) => {
      if (!imageName || m.image !== imageName) return;
      const pts = m.points.map((p) => fromNormalized(slotKey, p)).filter(Boolean);
      if (m.type === "length" && pts.length === 2) {
        const value = m.value != null ? m.value : relativeLength(slotKey, m.points[0], m.points[1]);
        drawLength(overlay, slotKey, pts[0], pts[1], colorLength, String(value));
      }
      if (m.type === "angle" && pts.length === 3) {
        const value = m.value != null
          ? m.value
          : formatAngle(angleDeg(pts[0], pts[1], pts[2]));
        drawAngle(overlay, slotKey, pts[0], pts[1], pts[2], colorAngle, value + "\u00b0");
      }
    });

    if (draftSlot === slotKey && draft.length > 0) {
      const pts = draft.map((p) => fromNormalized(slotKey, p)).filter(Boolean);
      const preview = hoverPt ? fromNormalized(slotKey, hoverPt) : null;
      if (tool === "ruler" && pts.length === 1 && preview && hoverPt) {
        drawLength(
          overlay,
          slotKey,
          pts[0],
          preview,
          colorLength,
          String(relativeLength(slotKey, draft[0], hoverPt))
        );
      } else if (tool === "ruler") {
        pts.forEach((p) => drawPoint(overlay, p, colorLength));
      } else if (tool === "protractor") {
        if (pts.length === 1) {
          drawPoint(overlay, pts[0], colorAngle);
          if (preview) {
            overlay.appendChild(svgEl("line", {
              x1: pts[0].x, y1: pts[0].y, x2: preview.x, y2: preview.y,
              stroke: colorAngle, "stroke-width": 1.5, "stroke-dasharray": "3 2",
            }));
            drawPoint(overlay, preview, colorAngle);
          }
        } else if (pts.length === 2) {
          if (preview) {
            drawAngle(
              overlay,
              slotKey,
              pts[0],
              pts[1],
              preview,
              colorAngle,
              formatAngle(angleDeg(pts[0], pts[1], preview)) + "\u00b0"
            );
          } else {
            overlay.appendChild(svgEl("line", {
              x1: pts[1].x, y1: pts[1].y, x2: pts[0].x, y2: pts[0].y,
              stroke: colorAngle, "stroke-width": 1.75,
            }));
            drawPoint(overlay, pts[0], colorAngle);
            drawPoint(overlay, pts[1], colorAngle);
          }
        }
      }
    }
  }

  function renderAll() {
    renderOverlay(1);
    renderOverlay(2);
  }

  window.redrawMeasurements = function () {
    syncImages();
    requestAnimationFrame(() => {
      renderList();
      renderAll();
    });
  };

  function finishIfReady() {
    const imageName = draftSlot ? currentImage(draftSlot) : "";
    if (!imageName) return;
    if (tool === "ruler" && draft.length === 2 && draftSlot) {
      const px = relativeLength(draftSlot, draft[0], draft[1]);
      addMeasurement({
        id: idSeq++,
        slot: draftSlot,
        image: imageName,
        type: "length",
        points: draft.slice(),
        value: px,
        label: t("labelLength", { slot: draftSlot, value: px }),
      });
      draft = [];
      draftSlot = null;
      setStatus(t("rulerDone"));
    } else if (tool === "protractor" && draft.length === 3 && draftSlot) {
      const a = fromNormalized(draftSlot, draft[0]);
      const v = fromNormalized(draftSlot, draft[1]);
      const c = fromNormalized(draftSlot, draft[2]);
      const deg = formatAngle(angleDeg(a, v, c));
      addMeasurement({
        id: idSeq++,
        slot: draftSlot,
        image: imageName,
        type: "angle",
        points: draft.slice(),
        value: deg,
        label: t("labelAngle", { slot: draftSlot, value: deg }),
      });
      draft = [];
      draftSlot = null;
      setStatus(t("angleDone"));
    }
  }

  function onOverlayClick(slotKey, event) {
    if (tool === "select") return;
    event.preventDefault();
    const slot = slots[slotKey];
    const raw = eventToSlot(slot, event);
    const pt = toNormalized(slotKey, raw.x, raw.y);
    if (!pt) {
      setStatus(t("outside"));
      return;
    }
    if (draftSlot && draftSlot !== slotKey) {
      draft = [];
    }
    draftSlot = slotKey;
    draft.push(pt);
    if (tool === "ruler" && draft.length === 1) setStatus(t("rulerNext"));
    else if (tool === "protractor" && draft.length === 1) setStatus(t("angleVertex"));
    else if (tool === "protractor" && draft.length === 2) setStatus(t("angleNext"));
    finishIfReady();
    renderAll();
  }

  function onOverlayMove(slotKey, event) {
    if (tool === "select" || draft.length === 0 || draftSlot !== slotKey) return;
    const slot = slots[slotKey];
    const raw = eventToSlot(slot, event);
    hoverPt = toNormalized(slotKey, raw.x, raw.y);
    renderOverlay(slotKey);
  }

  Object.keys(slots).forEach((key) => {
    const slotKey = Number(key);
    const slot = slots[slotKey];
    if (!slot) return;
    slot.addEventListener("click", (e) => onOverlayClick(slotKey, e));
    slot.addEventListener("pointermove", (e) => onOverlayMove(slotKey, e));
    slot.addEventListener("pointerleave", () => {
      hoverPt = null;
      renderOverlay(slotKey);
    });
  });

  document.getElementById("tool-select")?.addEventListener("click", () => setTool("select"));
  document.getElementById("tool-ruler")?.addEventListener("click", () => setTool("ruler"));
  document.getElementById("tool-protractor")?.addEventListener("click", () => setTool("protractor"));
  document.getElementById("tool-undo")?.addEventListener("click", () => {
    if (draft.length > 0) {
      draft.pop();
      if (draft.length === 0) draftSlot = null;
      renderAll();
      return;
    }
    const shown = visibleImageSet();
    for (let i = measurements.length - 1; i >= 0; i--) {
      if (shown.has(measurements[i].image)) {
        measurements.splice(i, 1);
        break;
      }
    }
    renderList();
    renderAll();
    setStatus(t("undone"));
  });
  document.getElementById("tool-clear")?.addEventListener("click", () => {
    measurements = [];
    draft = [];
    draftSlot = null;
    renderList();
    renderAll();
    setStatus(t("cleared"));
  });
  document.getElementById("tool-to-chat")?.addEventListener("click", () => {
    if (!chatInput) return;
    const visible = visibleMeasurements();
    if (visible.length === 0) {
      setStatus(t("emptyChat"));
      return;
    }
    const text = t("chatHeader") + "\n" + visible.map((m) => "- " + listLabel(m)).join("\n");
    chatInput.value = chatInput.value.trim() ? chatInput.value.trim() + "\n" + text : text;
    chatInput.focus();
    setStatus(t("chatDone"));
  });

  Object.values(images).forEach((img) => {
    img?.addEventListener("load", () => {
      syncImages();
      renderList();
      requestAnimationFrame(renderAll);
    });
  });
  window.addEventListener("resize", () => requestAnimationFrame(renderAll));
  if (window.ResizeObserver) {
    Object.values(slots).forEach((slot) => {
      if (!slot) return;
      new ResizeObserver(() => requestAnimationFrame(renderAll)).observe(slot);
    });
  }

  setTool("select");
})();
