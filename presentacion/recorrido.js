"use strict";
/* La presentación del MVP: el prototipo ("Prototipo MVP.html") en un iframe, el panel de negocio encima a pedido, los
   controles de la demo de la app a los lados y un recorrido automático por capítulos. build.mjs mete este archivo en
   escritorio.html y en movil.html, y los dos HTML en PROTOS (cada uno con shim.js, que guarda con prefijo propio). */
const TITLE = "MVP · Agente Mochi";
const stage = document.getElementById("stage");
const frame = { el: null, ready: null };

/* ---------- el prototipo ---------- */
function clearStorage(id) {
  for (const store of [localStorage, sessionStorage]) {
    try {
      for (let i = store.length - 1; i >= 0; i--) {
        const k = store.key(i);
        if (k && k.indexOf(id + ":") === 0) store.removeItem(k);
      }
    } catch (e) { /* sin almacenamiento: nada que limpiar */ }
  }
}

/* Cada carga parte de cero, con un iframe nuevo y sin lo guardado (carro, pedidos, persona, modo). Volver a cargar el
   mismo iframe dejaría una entrada en el historial y el "atrás" del navegador lo dejaría en blanco. Se limpia con el
   iframe viejo ya fuera, para que no alcance a volver a guardar. Cambiar de persona recarga la app dentro del mismo
   iframe: onload vuelve a vigilar los toques de la persona en el documento nuevo. */
function load() {
  const el = document.createElement("iframe");
  el.title = TITLE;
  frame.ready = new Promise((resolve) => {
    el.onload = () => { watchUser(el); resolve(); };
  });
  el.srcdoc = PROTOS.mvp;
  if (frame.el) frame.el.remove();
  clearStorage("mvp");
  personaNow = null;
  shownKey = "";
  stage.appendChild(el);
  frame.el = el;
  return frame.ready;
}

const appDoc = () => frame.el && frame.el.contentDocument;

/* ---------- panel de negocio: se carga la primera vez que se abre ---------- */
const bizOpen = document.getElementById("biz-open");
const biz = document.getElementById("biz");
const bizFrame = document.getElementById("biz-frame");

/* Abrir o cerrar el panel a mano detiene el recorrido; el recorrido también lo abre y lo cierra (sus clics no son de
   la persona y no lo detienen) */
function byUser(e) { if (e.isTrusted) { panRun++; stopTour(); } }

function openBiz() {
  if (!bizFrame.firstChild) {
    const el = document.createElement("iframe");
    el.title = "Panel de negocio";
    el.onload = () => watchUser(el);
    el.srcdoc = PROTOS.panel;
    bizFrame.appendChild(el);
  }
  biz.hidden = false;
}
function closeBiz() { biz.hidden = true; }

bizOpen.addEventListener("click", (e) => { byUser(e); openBiz(); });
document.getElementById("biz-close").addEventListener("click", (e) => { byUser(e); closeBiz(); });
biz.addEventListener("click", (e) => { if (e.target === biz) { byUser(e); closeBiz(); } });
document.addEventListener("keydown", (e) => { if (e.key === "Escape") { byUser(e); closeBiz(); } });

/* ---------- los controles de la demo de la app, en la presentación ----------
   El interruptor de modo y el "Panel de la demo" de la app quedarían encima del teléfono, así que se ocultan (ver
   build.mjs) y sus mismos botones se muestran aquí: cada botón de la presentación hace clic en el original. El panel
   de la demo se abre solo (oculto): sus botones existen solo abierto. */
const modesBox = document.getElementById("modes-box");
const modesEl = document.getElementById("modes");
const replayBtn = document.getElementById("replay");
const personasBox = document.getElementById("personas-box");
const personasEl = document.getElementById("personas");
const tastesEl = document.getElementById("tastes");
const readoutEl = document.getElementById("readout");
const simBox = document.getElementById("sim-box");
const simEl = document.getElementById("sim");
let shownKey = "";
let personaNow = null;

const appButtons = (sel) => { const doc = appDoc(); return doc ? [...doc.querySelectorAll(sel)] : []; };
const appModes = () => appButtons(".demo-toggle-modes button");
const isOn = (b) => b.getAttribute("aria-checked") === "true" || b.classList.contains("is-active");
/* El prototipo final de la app es el MVP de esta presentación */
const modeLabel = (b) => b.textContent.replace(/Prototipo final\s*✨?/, "MVP con Mochi").trim();

/* Los botones de una sección del "Panel de la demo" (la que sigue al título `title`) */
function demoButtons(title) {
  const doc = appDoc();
  const panel = doc && doc.querySelector(".offline-demo-panel");
  if (!panel) return [];
  const head = [...panel.querySelectorAll("h2")].find((h) => h.textContent.trim() === title);
  let box = head && head.nextElementSibling;
  while (box && !box.classList.contains("offline-demo-buttons")) box = box.nextElementSibling;
  return box ? [...box.querySelectorAll("button")] : [];
}
/* Los perfiles de gusto empiezan con su emoji ("🥢 Amante de lo asiático") */
const EMOJI = /^\p{Extended_Pictographic}/u;
const isTaste = (label) => EMOJI.test(label);

/* Las secciones del "Panel de la demo" que van en "Simular". "Mochi" (solo en el MVP con Mochi) es un botón que dice lo
   que hará: "Ocultar a Mochi" o "Mostrar a Mochi" */
const SIM_SECTIONS = ["Mover la Home", "Pedido en curso", "Mochi"];
const simButtons = () => SIM_SECTIONS.flatMap(demoButtons);

function proxy(className, text, onClick) {
  const b = document.createElement("button");
  b.className = className;
  b.textContent = text;
  b.addEventListener("click", (e) => { if (e.isTrusted) stopTour(); onClick(e); });
  return b;
}

/* "+1 visita" mueve los accesos de la Home y Mochi lo explica: para que se vea, cierra el buscador (una persona elegida
   a mano lo deja abierto) y termina la guía de la primera vez si está a la vista (si no, Mochi lo explica al terminarla) */
function showHome() {
  const doc = appDoc();
  if (!doc) return;
  const back = doc.querySelector(".agent-search button.search-back");
  if (back) back.click();
  const guide = [...doc.querySelectorAll(".live-bubble button.live-chip")].find((b) => /^(Saltar|Listo)$/.test(b.textContent.trim()));
  if (guide) guide.click();
}

/* Un perfil de gusto se muestra como ficha: su emoji grande y el nombre corto ("🥢 Amante de lo asiático" → "Asiático").
   El nombre completo queda en aria-label y title: el recorrido lo busca por ahí */
function tasteTile(b, label) {
  const emoji = label.match(EMOJI)[0];
  const name = label.slice(emoji.length).trim().replace(/^Amante\s+(de\s+l[oa]s?|del|de)\s+/i, "");
  const icon = document.createElement("span");
  icon.className = "taste-emoji";
  icon.textContent = emoji;
  const text = document.createElement("span");
  text.className = "taste-name";
  text.textContent = name.charAt(0).toUpperCase() + name.slice(1);
  b.replaceChildren(icon, text);
  b.setAttribute("aria-label", label);
  b.title = label;
}

function syncControls() {
  const doc = appDoc();
  const toggle = doc && doc.querySelector(".offline-demo-toggle");
  if (toggle && toggle.getAttribute("aria-expanded") === "false") toggle.click();
  const modes = appModes();
  const people = demoButtons("Persona").map((b) => b.textContent.trim());
  const sims = simButtons().map((b) => b.textContent.trim());
  const key = modes.map(modeLabel).join("/") + "|" + people.join("/") + "|" + sims.join("/");
  if (key !== shownKey) {
    shownKey = key;
    modesEl.replaceChildren(...modes.map((b, i) =>
      proxy("mode", modeLabel(b), () => { const m = appModes()[i]; if (m) m.click(); })));
    const personaProxy = (label) => {
      /* tocada a mano, cualquier persona termina en el buscador con Mochi; el recorrido decide paso a paso */
      const p = proxy(isTaste(label) ? "persona taste" : "persona", label, (e) => {
        personaPan = choosePersona(label, e.isTrusted);
      });
      p.dataset.label = label;
      if (isTaste(label)) tasteTile(p, label);
      else p.title = label;
      return p;
    };
    personasEl.replaceChildren(...people.filter((l) => !isTaste(l)).map(personaProxy));
    tastesEl.replaceChildren(...people.filter(isTaste).map(personaProxy));
    simEl.replaceChildren(...sims.map((label) => {
      const kind = /^Borrar/.test(label) ? " is-danger" : /^(Ocultar|Mostrar) a/.test(label) ? " is-mochi" : "";
      const b = proxy("sim" + kind, label, () => {
        const t = simButtons().find((x) => x.textContent.trim() === label);
        /* ocultar o mostrar a Mochi también se ve en la Home: sin la mascota o de vuelta */
        if (t && /^(\+1 visita|Ocultar a|Mostrar a)/.test(label)) showHome();
        if (t) t.click();
      });
      /* "+1 visita a Rappi Mall" se ve corto ("+1 Rappi Mall"); el texto completo queda para el recorrido y el title */
      const visit = /^\+1 visita a (.+)$/.exec(label);
      if (visit) {
        b.textContent = "+1 " + visit[1];
        b.setAttribute("aria-label", label);
      }
      b.title = label;
      return b;
    }));
  }
  modesBox.hidden = modes.length === 0;
  replayBtn.hidden = !appButtons(".demo-toggle-replay")[0];
  personasBox.hidden = people.length === 0;
  simBox.hidden = sims.length === 0;
  modesEl.querySelectorAll(".mode").forEach((p, i) => p.classList.toggle("is-active", !!modes[i] && isOn(modes[i])));
  document.querySelectorAll(".persona").forEach((p) => p.classList.toggle("is-active", p.dataset.label === personaNow));
  const now = document.getElementById("persona-now");
  if (now) now.textContent = personaNow || "Elige una persona";
  const readout = doc && doc.querySelector(".offline-demo-readout");
  const text = readout ? readout.textContent.trim() : "";
  if (readoutEl.textContent !== text) readoutEl.textContent = text;
  readoutEl.hidden = !text;
}

replayBtn.addEventListener("click", (e) => {
  if (e.isTrusted) stopTour();
  const r = appButtons(".demo-toggle-replay")[0];
  if (r) r.click();
});
setInterval(syncControls, 300);

/* La tecla D cambia de vista también desde la presentación (en la app ya lo hace, si tiene el foco) */
document.addEventListener("keydown", (e) => {
  if (e.key.toLowerCase() !== "d" || e.metaKey || e.ctrlKey || e.altKey || !e.isTrusted) return;
  const other = appModes().find((b) => !isOn(b));
  if (other) { stopTour(); other.click(); }
});

/* Al elegir una persona: el "Panel de la demo" borra lo de ahora, siembra su historial y recarga la app en la Home.
   Elegida a mano (`byHand`), después abre el buscador con Mochi: lo que Mochi le muestra a esa persona. Con un perfil
   de gusto, además pasea su escalera "Para ti en otras verticales" hacia la derecha, tarjeta por tarjeta. Un clic o la
   rueda dentro de la app (o Parar) corta el paseo. */
let panRun = 0;
let personaPan = Promise.resolve();
/* El recorrido elige algunas personas sin el paseo (lo muestra él, paso a paso) */
let skipPan = false;
const pause = (ms) => new Promise((r) => setTimeout(r, ms));

async function choosePersona(label, byHand = false) {
  const run = ++panRun;
  const live = () => run === panRun;
  const pan = !skipPan && isTaste(label);
  skipPan = false;
  const t = demoButtons("Persona").find((b) => b.textContent.trim() === label);
  if (!t) return;
  personaNow = label;
  const el = frame.el;
  const reloaded = new Promise((r) => el.addEventListener("load", r, { once: true }));
  t.click();
  await Promise.race([reloaded, pause(8000)]);
  for (let i = 0; i < 60 && live(); i++) {
    const doc = appDoc();
    if (doc && doc.querySelector(".smart-bar, .home-tile")) break;
    await pause(150);
  }
  if (!live() || !(byHand || pan)) return;
  /* el aviso de privacidad de la primera visita taparía el buscador: se acepta, como en el recorrido */
  const ok = appDoc() && appDoc().querySelector(".privacy-notice-ok");
  if (ok) ok.click();
  await pause(700);
  if (live()) await showSearch(live, pan);
}

/* Abre el buscador con Mochi desde la Home; con `pan`, espera la escalera y la pasea */
async function showSearch(live, pan) {
  const doc = appDoc();
  if (!doc.querySelector(".agent-search")) {
    const bars = [...doc.querySelectorAll(".smart-bar")].filter(visible);
    let bar = bars.find(onTop);
    if (!bar && bars[0]) {
      /* la Home quedó desplazada y la barra está fuera de la vista (pasa en el iPhone): se vuelve arriba */
      const win = doc.defaultView;
      for (let box = bars[0].parentElement; box && box !== doc.body; box = box.parentElement) {
        if (/(auto|scroll)/.test(win.getComputedStyle(box).overflowY) && box.scrollTop > 0) box.scrollTo({ top: 0 });
      }
      await pause(350);
      if (!live()) return;
      bar = bars.find(onTop);
    }
    if (!bar) return;
    tap(bar);
  }
  if (!pan) return;
  let rail = null;
  for (let i = 0; i < 30 && !rail; i++) {
    await pause(150);
    if (!live()) return;
    rail = [...appDoc().querySelectorAll(".taste-rail")].find(visible) || null;
  }
  if (!rail) return;
  /* el perfil arriba unos 2 s; después la escalera */
  const body = rail.closest(".agent-search-body");
  if (body) body.scrollTo({ top: 0 });
  await pause(2000);
  if (live()) await panRail(live);
}

/* Deja la escalera a la vista y la pasea de lado, tarjeta por tarjeta, y vuelve al inicio */
async function panRail(live) {
  const rail = [...appDoc().querySelectorAll(".taste-rail")].find(visible);
  if (!rail) return false;
  rail.scrollTo({ left: 0 });
  const body = rail.closest(".agent-search-body");
  const ladder = rail.closest(".taste-ladder") || rail;
  if (body) {
    const top = ladder.getBoundingClientRect().top - body.getBoundingClientRect().top - 24;
    if (top > 0) { body.scrollBy({ top, behavior: "smooth" }); await pause(900); }
  }
  const card = rail.querySelector(".taste-step");
  const step = card ? card.getBoundingClientRect().width + 12 : 280;
  while (live() && rail.scrollLeft + rail.clientWidth < rail.scrollWidth - 4) {
    rail.scrollBy({ left: step, behavior: "smooth" });
    await pause(1300);
  }
  if (!live()) return true;
  await pause(600);
  rail.scrollTo({ left: 0, behavior: "smooth" });
  await pause(900);
  return true;
}

/* ---------- el recorrido automático ---------- */
const cursor = document.getElementById("cursor");
const playBtn = document.getElementById("play");
const playLabel = document.getElementById("play-label");
const stopBtn = document.getElementById("stop");
const statusEl = document.getElementById("status");
const STATUS_IDLE = statusEl.innerHTML;
const STOP = Symbol("stop");
let tour = null;
let chapterNow = null;
let pos = { x: innerWidth / 2, y: innerHeight / 2 };

function setStatus(title, text) {
  statusEl.innerHTML = "";
  const s = document.createElement("strong");
  s.textContent = title;
  statusEl.append(s, document.createTextNode(text || ""));
}

function sleep(ms) {
  const t = tour;
  return new Promise((resolve, reject) => {
    const end = Date.now() + ms;
    (function tick() {
      if (tour !== t || !t) return reject(STOP);
      if (Date.now() >= end) return resolve();
      setTimeout(tick, Math.min(80, end - Date.now()));
    })();
  });
}

/* La punta del "mouse" (data-dx/dy en #cursor): la flecha en el escritorio, el centro del dedo en la versión táctil */
const TIP = { x: Number(cursor.dataset.dx || 5), y: Number(cursor.dataset.dy || 3) };

function placeCursor(x, y, ms) {
  cursor.style.transition = "opacity .3s, transform " + ms + "ms cubic-bezier(.4,0,.2,1)";
  cursor.style.transform = "translate(" + (x - TIP.x) + "px," + (y - TIP.y) + "px)";
  pos = { x, y };
}

/* Centro de un elemento en la ventana: si está dentro de un iframe (el prototipo o el panel de negocio), se suma dónde
   está ese iframe */
function centerOf(el) {
  const r = el.getBoundingClientRect();
  const fr = el.ownerDocument.defaultView.frameElement;
  const o = fr ? fr.getBoundingClientRect() : { left: 0, top: 0 };
  return { x: o.left + r.left + r.width / 2, y: o.top + r.top + r.height / 2 };
}

function visible(el) {
  if (!el || !el.isConnected) return false;
  const r = el.getBoundingClientRect();
  if (r.width < 2 || r.height < 2) return false;
  const st = el.ownerDocument.defaultView.getComputedStyle(el);
  return st.visibility !== "hidden" && st.display !== "none" && st.opacity !== "0";
}

/* ¿Es lo que de verdad está arriba en ese punto? (descarta copias ocultas detrás) */
function onTop(el) {
  const r = el.getBoundingClientRect();
  const win = el.ownerDocument.defaultView;
  const x = r.left + r.width / 2, y = r.top + r.height / 2;
  if (x < 0 || y < 0 || x > win.innerWidth || y > win.innerHeight) return false;
  const hit = el.ownerDocument.elementFromPoint(x, y);
  return !!hit && (hit === el || el.contains(hit) || hit.contains(el));
}

/* Busca en la app; con `panel`, en los botones de esta página; con `biz`, dentro del panel de negocio. Por selector,
   texto o aria-label */
function find(q) {
  const doc = q.panel ? document
    : q.biz ? bizFrame.firstChild && bizFrame.firstChild.contentDocument
    : appDoc();
  if (!doc) return null;
  let all = [...doc.querySelectorAll(q.panel || q.biz || q.sel)];
  /* los controles de la página pueden estar dentro de un menú cerrado (versión táctil): valen igual */
  if (!q.panel || all.some(visible)) all = all.filter(visible);
  if (q.text) {
    const want = q.text.toLowerCase();
    all = all.filter((e) => ((e.getAttribute("aria-label") || "") + " " + e.textContent).toLowerCase().includes(want));
  }
  all = all.filter(onTop).concat(all.filter((e) => !onTop(e)));
  return all[q.nth || 0] || null;
}

/* `q` puede ser una lista de alternativas: vale la primera que esté a la vista */
async function waitFor(q, ms) {
  const end = Date.now() + (ms || 4000);
  const qs = Array.isArray(q) ? q : [q];
  for (;;) {
    let el = null;
    for (const one of qs) if ((el = find(one)) && onTop(el)) break;
    if (!el || !onTop(el)) el = qs.map(find).find(Boolean) || null;
    if (el) return el;
    if (Date.now() > end) return null;
    await sleep(120);
  }
}

/* Solo los carruseles (se desplazan de lado y no hacia abajo) se corren de lado: una lista vertical también desborda
   de lado mientras entra una pantalla animada. */
const isCarousel = (box, st) =>
  /(auto|scroll)/.test(st.overflowX) && box.scrollWidth > box.clientWidth + 4 && box.scrollHeight <= box.clientHeight + 4;

/* Espera a que el elemento deje de moverse (las pantallas entran con animación) */
async function settle(el) {
  let last = "";
  for (let i = 0; i < 20; i++) {
    const r = el.getBoundingClientRect();
    const now = Math.round(r.left) + "," + Math.round(r.top);
    if (now === last) return;
    last = now;
    await sleep(90);
  }
}

/* Acerca el elemento solo con las listas que se desplazan de verdad (overflow auto/scroll). scrollIntoView también
   corre contenedores con overflow hidden y descuadra el teléfono. */
async function bringIntoView(el) {
  await settle(el);
  const win = el.ownerDocument.defaultView;
  let moved = false;
  for (let box = el.parentElement; box && box !== el.ownerDocument.body; box = box.parentElement) {
    const st = win.getComputedStyle(box);
    const b = box.getBoundingClientRect();
    const r = el.getBoundingClientRect();
    if (/(auto|scroll)/.test(st.overflowY) && box.scrollHeight > box.clientHeight + 4 && (r.top < b.top + 60 || r.bottom > b.bottom - 90)) {
      box.scrollBy({ top: r.top + r.height / 2 - (b.top + b.height / 2), behavior: "smooth" });
      moved = true;
    }
    if (isCarousel(box, st) && (r.left < b.left || r.right > b.right)) {
      box.scrollBy({ left: r.left + r.width / 2 - (b.left + b.width / 2), behavior: "smooth" });
      moved = true;
    }
  }
  /* si sigue fuera de la vista, se desplaza la página del iframe (el panel de negocio es una página larga) */
  const r = el.getBoundingClientRect();
  if (el.ownerDocument !== document && (r.top < 0 || r.bottom > win.innerHeight)) {
    win.scrollBy({ top: r.top + r.height / 2 - win.innerHeight / 2, behavior: "smooth" });
    moved = true;
  }
  if (moved) await sleep(500);
}

async function moveTo(el) {
  if (el.ownerDocument !== document) await bringIntoView(el);
  const c = centerOf(el);
  const dist = Math.hypot(c.x - pos.x, c.y - pos.y);
  const ms = Math.max(300, Math.min(800, dist * 1.1));
  placeCursor(c.x, c.y, ms);
  await sleep(ms + 80);
}

function ripple() {
  const r = document.createElement("div");
  r.className = "ripple";
  r.style.left = pos.x + "px";
  r.style.top = pos.y + "px";
  document.body.appendChild(r);
  setTimeout(() => r.remove(), 700);
}

function tap(el) {
  const win = el.ownerDocument.defaultView;
  const r = el.getBoundingClientRect();
  const o = { bubbles: true, cancelable: true, composed: true, view: win, clientX: r.left + r.width / 2, clientY: r.top + r.height / 2, button: 0, pointerId: 1, pointerType: "mouse", isPrimary: true };
  el.dispatchEvent(new win.PointerEvent("pointerdown", o));
  el.dispatchEvent(new win.MouseEvent("mousedown", o));
  /* solo los campos de texto reciben el foco: en un botón dejaría el marco de foco a la vista */
  if (/^(INPUT|TEXTAREA)$/.test(el.tagName)) el.focus({ preventScroll: true });
  el.dispatchEvent(new win.PointerEvent("pointerup", o));
  el.dispatchEvent(new win.MouseEvent("mouseup", o));
  if (typeof el.click === "function") el.click();
  else el.dispatchEvent(new win.MouseEvent("click", o));
}

async function typeInto(el, text) {
  const win = el.ownerDocument.defaultView;
  const proto = el.tagName === "TEXTAREA" ? win.HTMLTextAreaElement.prototype : win.HTMLInputElement.prototype;
  const setter = Object.getOwnPropertyDescriptor(proto, "value").set;
  el.focus({ preventScroll: true });
  for (let i = 1; i <= text.length; i++) {
    setter.call(el, text.slice(0, i));
    el.dispatchEvent(new win.Event("input", { bubbles: true }));
    await sleep(70);
  }
}

function pressEnter(el) {
  const win = el.ownerDocument.defaultView;
  const o = { key: "Enter", code: "Enter", keyCode: 13, which: 13, bubbles: true, cancelable: true };
  el.dispatchEvent(new win.KeyboardEvent("keydown", o));
  el.dispatchEvent(new win.KeyboardEvent("keyup", o));
  if (el.form && el.form.requestSubmit) el.form.requestSubmit();
}

/* Desplaza el contenedor con scroll más cercano al elemento (vertical, u horizontal con x) */
async function scrollIn(q, by, x, to) {
  const el = find(q);
  if (!el) return false;
  let box = el;
  const win = el.ownerDocument.defaultView;
  while (box && box !== el.ownerDocument.body) {
    const st = win.getComputedStyle(box);
    const fits = x
      ? isCarousel(box, st)
      : /(auto|scroll)/.test(st.overflowY) && box.scrollHeight > box.clientHeight + 4;
    if (fits) break;
    box = box.parentElement;
  }
  /* sin lista que se desplace, se desplaza la página entera del iframe */
  const page = !box || box === el.ownerDocument.body;
  if (page && (x || el.ownerDocument === document)) return false;
  const c = x ? centerOf(el) : page ? centerOf(el) : centerOf(box);
  placeCursor(c.x, c.y, 500);
  await sleep(450);
  /* con `to`, baja lo justo para dejar ese elemento cerca de arriba */
  if (to) by = to.getBoundingClientRect().top - (page ? 0 : box.getBoundingClientRect().top) - 150;
  (page ? win : box).scrollBy(x ? { left: by, behavior: "smooth" } : { top: by, behavior: "smooth" });
  await sleep(800);
  return true;
}

/* Ritmo del recorrido: espera tras cada clic si el paso no dice otra cosa */
const STEP_PAUSE = 1300;
/* Los pasos que no encontraron lo suyo (en la consola, para revisar el guion) */
const skipped = [];
function skip(step) {
  if (step.optional) return;
  const where = chapterNow ? chapterNow.title : TITLE;
  skipped.push(where + ": " + step.say);
  console.info("Paso saltado:", where, "·", step.say);
}

/* Un paso: { say, click | type | point | scroll | wait | run }; con `until`, repite el clic (hasta `max` veces) mientras
   no aparezca lo que dice `until`. `point` lleva el mouse a algo sin tocarlo. */
async function runStep(step) {
  if (step.until) {
    const { until, max, ...one } = step;
    for (let i = 0; i < (max || 12) && !find(until); i++) await runStep(one);
    return;
  }
  if (step.say) setStatus(chapterNow ? chapterNow.title : TITLE, step.say);
  if (step.wait) await sleep(step.wait);
  if (step.click) {
    const el = await waitFor(step.click, step.timeout);
    if (!el) return skip(step);
    /* un control del menú cerrado se activa sin mover el dedo hasta él */
    if (visible(el)) { await moveTo(el); ripple(); }
    tap(el);
    await sleep(step.after == null ? STEP_PAUSE : step.after);
  }
  if (step.point) {
    const el = await waitFor(step.point, step.timeout);
    if (!el) return skip(step);
    await moveTo(el);
    await sleep(step.after == null ? STEP_PAUSE : step.after);
  }
  if (step.type) {
    const el = await waitFor(step.type.into, step.timeout);
    if (!el) return skip(step);
    await moveTo(el);
    ripple();
    tap(el);
    await sleep(300);
    await typeInto(el, step.type.text);
    if (step.type.enter) { await sleep(300); pressEnter(el); }
    await sleep(step.after == null ? STEP_PAUSE : step.after);
  }
  if (step.scroll) {
    const s = step.scroll;
    const done = await scrollIn(s.to || s.in, s.by, s.x, s.to && find(s.to));
    if (!done) skip(step);
  }
  if (step.run) { await step.run(); await sleep(step.after == null ? 900 : step.after); }
}

/* Recorre los capítulos `ids`; con `loop`, una y otra vez. Parte con la app limpia; cada capítulo elige su persona
   (que borra lo de antes) o sigue con lo que dejó el anterior. Al terminar vuelve a cargar la app limpia, para que
   quien la use después no vea el carro del recorrido. */
async function runTour(ids, loop) {
  const t = tour;
  cursor.classList.add("is-on");
  try {
    do {
      setStatus(TITLE, "Abriendo el prototipo…");
      closeBiz();
      await load();
      await sleep(1500);
      await runStep(INTRO);
      for (const id of ids) {
        if (tour !== t) return;
        chapterNow = CHAPTERS.find((c) => c.id === id);
        markChapter(id);
        for (const step of chapterNow.steps) {
          if (tour !== t) return;
          await runStep(step);
        }
        await sleep(900);
      }
    } while (loop);
    stopTour();
    load();
  } catch (e) {
    if (e !== STOP) { console.error("Recorrido:", e); stopTour(); }
  }
}

function markChapter(id) {
  document.querySelectorAll(".tour-one").forEach((b) => b.classList.toggle("is-now", b.dataset.id === id));
}

function startTour(ids, loop, btn) {
  stopTour();
  tour = {};
  skipped.length = 0;
  btn.setAttribute("aria-pressed", "true");
  if (btn === playBtn) playLabel.textContent = "Recorriendo…";
  stopBtn.disabled = false;
  document.dispatchEvent(new Event("recorrido:inicio"));
  runTour(ids, loop);
}

function stopTour() {
  if (!tour) return;
  tour = null;
  chapterNow = null;
  markChapter(null);
  cursor.classList.remove("is-on");
  document.querySelectorAll(".play, .tour-one").forEach((b) => b.setAttribute("aria-pressed", "false"));
  playLabel.textContent = "Recorrido automático";
  stopBtn.disabled = true;
  statusEl.innerHTML = STATUS_IDLE;
  document.dispatchEvent(new Event("recorrido:fin"));
}

/* Cualquier clic, tecla o rueda de verdad dentro de la app o del panel detiene el recorrido */
function watchUser(iframe) {
  const doc = iframe.contentDocument;
  if (!doc) return;
  for (const type of ["pointerdown", "keydown", "wheel", "touchstart"]) {
    doc.addEventListener(type, (e) => { if (e.isTrusted) { panRun++; stopTour(); } }, { capture: true, passive: true });
  }
}

/* ---------- el guion, por capítulos ----------
   Cada paso: say (lo que se lee en la presentación) y una acción: click, type, point, scroll, wait, run. `click` puede
   ser una lista de alternativas; `until` repite el clic hasta que aparezca algo. `panel` apunta a los botones de la
   presentación (vista, personas, simular); `biz`, al panel de negocio; el resto, a la app. Si algo no aparece, el
   paso se salta (queda en la consola) y el recorrido sigue. */
const persona = (text, say, pan = true) => [
  { say, run: () => { skipPan = !pan; }, after: 0 },
  { say, click: { panel: ".persona", text }, timeout: 8000, after: 300 },
  { say, run: () => personaPan, after: 600 },
];
const simulate = (text, say) => [
  { say, run: () => { simBox.open = true; }, after: 200 },
  { say, click: { panel: ".sim", text }, after: 1100 },
];
const backHome = (say) => ({ say: say || "Vuelve a la Home.", click: [{ sel: "button.search-back" }, { sel: "button.back-button" }], timeout: 2500 });

/* Al abrir la app: el aviso de privacidad de la primera visita (si está) */
const INTRO = { click: { sel: ".privacy-notice-ok" }, timeout: 2500, after: 500, optional: true };

const CHAPTERS = [
  {
    id: "home",
    title: "1 · La Home que aprende",
    steps: [
      ...persona("Restaurantes + Turbo + Súper", "Una persona que pide en Restaurantes, Turbo y Súper."),
      { say: "Mochi vive en la Home y se presenta.", click: { sel: "button.live-chip", text: "Siguiente" }, timeout: 14000, after: 1800 },
      { say: "Mochi vive en la Home y se presenta.", click: { sel: "button.live-chip", text: "Listo" }, timeout: 8000, after: 1200 },
      { say: "Los accesos se ordenan por lo que más usa: Súper va primero.", point: { sel: ".home-shortcut" }, after: 1800 },
      ...simulate("Rappi Mall", "Simula visitas a Rappi Mall desde el panel de la demo."),
      ...simulate("Rappi Mall", "Simula visitas a Rappi Mall desde el panel de la demo."),
      { say: "Mochi mueve los accesos en vivo y dice por qué.", point: { sel: ".live-bubble" }, timeout: 5000, after: 3000 },
      { say: "La Home se reordena en vivo: Rappi Mall sube.", point: { sel: ".home-shortcut", text: "Rappi Mall" }, after: 1800 },
      { say: '"Entendido".', click: { sel: "button.live-chip", text: "Entendido" }, timeout: 3000, after: 600 },
      { say: "Le pide a Mochi algo nuevo para probar.", click: { sel: ".live-agent-body" }, after: 2600 },
      { say: "Mochi propone la vertical que sigue en su escalera. ¿Por qué?", click: { sel: ".live-bubble .offer-why-toggle" }, timeout: 6000, after: 2600 },
      { say: 'Por ahora, "Después".', click: { sel: "button.live-chip", text: "Después" } },
    ],
  },
  {
    id: "buscador",
    title: "2 · El buscador con Mochi",
    steps: [
      ...persona("asiático", "Ahora, alguien que pide sushi seguido.", false),
      { say: '"¿Repetimos sushi?": lo que pide con ritmo, a un toque.', point: { sel: ".live-card--repeat" }, timeout: 6000, after: 1600 },
      { say: "Cada oferta dice por qué.", click: { sel: ".live-card--repeat .offer-why-toggle" }, after: 2400 },
      { say: "El buscador con Mochi: su perfil de gusto y un saludo.", click: { sel: ".smart-bar" }, after: 2400 },
      { say: "¿Por qué este perfil? Lo que pidió.", click: { sel: "button.taste-why-toggle" }, timeout: 2500, after: 2600 },
      { say: "Su escalera: ideas en otras verticales, de la más cercana a RappiTravel.", run: async () => { if (!(await panRail(() => !!tour))) skip({ say: "Su escalera (no apareció)" }); }, after: 600 },
      { say: "Abre una idea y la agrega al carro.", click: { sel: ".taste-product-main" }, after: 1500 },
      { say: "Abre una idea y la agrega al carro.", click: { sel: ".product-sheet-confirm" }, timeout: 3000 },
      backHome(),
    ],
  },
  {
    id: "necesidad",
    title: "3 · Por necesidad o por plan",
    steps: [
      { say: "Le pide algo por necesidad, no por producto.", click: { sel: ".smart-bar" }, after: 1600 },
      { say: '"¿Qué llevo para un asado de 6?"', type: { into: { sel: ".agent-search input" }, text: "¿Qué llevo para un asado de 6?", enter: true }, after: 2800 },
      { say: "Carne para 6 y lo que falta de otra tienda: carbón.", scroll: { in: { sel: ".agent-search-body .agent-msg-product-main" }, by: 260 } },
      { say: 'Lo refina con un toque: "Más barato".', click: { sel: ".agent-follow-chip", text: "Más barato" }, after: 2800 },
      backHome(),
      { say: 'En la Home: "¿Qué plan tienes hoy?"', scroll: { to: { sel: ".live-plan-title" } } },
      { say: 'Elige "Carrete": un kit de las tiendas que hagan falta.', click: { sel: ".live-plan-chip", text: "Carrete" }, after: 2800 },
      { say: "El kit, con lo que suma cada tienda.", point: { sel: ".live-kit-add" }, after: 2200 },
    ],
  },
  {
    id: "volver",
    title: '4 · "¿Volvemos a…?" y Ofertas',
    steps: [
      ...persona("Dejó de pedir su plato", "Alguien que dejó de pedir su plato de siempre."),
      { say: '"¿Volvemos a…?": lo que pedía con ritmo y dejó de pedir.', point: { sel: ".live-card--repeat" }, timeout: 6000, after: 1800 },
      { say: "Con su porqué.", click: { sel: ".live-card--repeat .offer-why-toggle" }, after: 2600 },
      { say: 'Si dice "Después", Mochi no insiste (con dos, lo deja).', click: { sel: ".live-repeat-later", text: "Después" } },
      { say: "Ofertas: lo que bajó de precio, por vertical.", click: { sel: ".bottom-nav-item", text: "Ofertas" }, after: 2000 },
      { say: "Ofertas: lo que bajó de precio, por vertical.", scroll: { in: { sel: ".deals-vertical-title" }, by: 600 } },
      { say: "Vuelve a la Home.", click: { sel: ".bottom-nav-item", text: "Inicio" } },
    ],
  },
  {
    id: "pedido",
    title: "5 · Carro, pago y seguimiento",
    steps: [
      ...persona("Restaurantes + Turbo", "Una compra de punta a punta."),
      { say: 'Busca "sushi".', click: { sel: ".smart-bar" }, after: 1400 },
      { say: 'Busca "sushi".', type: { into: { sel: ".agent-search input" }, text: "sushi" }, after: 1800 },
      { say: "Abre un sushi de un restaurante.", click: [{ sel: ".product-row-main", text: "Sushi" }, { sel: ".product-row-main" }], after: 1500 },
      { say: "Lo agrega al carro.", click: { sel: ".product-sheet-confirm" }, timeout: 3000 },
      backHome(),
      { say: "Abre el carro.", click: { sel: ".cart-bar" }, timeout: 3000 },
      { say: "Ir a pagar.", click: { sel: ".cart-checkout" }, after: 2000 },
      { say: 'El checkout: envío, entrega, propina y "¿Me falta algo?".', scroll: { to: { sel: ".checkout-ask" } } },
      { say: "Hace el pedido.", click: { sel: ".checkout-place" }, after: 2500 },
      { say: "El seguimiento: cuánto falta y en qué va.", point: { sel: ".tracking-eta" }, timeout: 9000, after: 2400 },
      { say: "Y lo que Turbo suma antes de que llegue, con su porqué.", point: { sel: ".tracking-ontop" }, timeout: 2500, after: 2200 },
      ...simulate("Atrasar", "Simula un atraso desde el panel de la demo."),
      { say: "Llega un aviso y sube el tiempo estimado.", point: { sel: ".tracking-delay" }, timeout: 6000, after: 3000 },
    ],
  },
  {
    id: "autonomia",
    title: '6 · Preferencias y "Pedir por mí"',
    steps: [
      ...persona("asiático", "Lo que Mochi puede hacer por la persona.", false),
      { say: "Abre el buscador con Mochi.", click: { sel: ".smart-bar" }, after: 1600 },
      { say: '"Mis preferencias": dieta, alergias y favoritos.', click: { sel: ".agent-search-body button", text: "Mis preferencias" }, after: 1600 },
      { say: 'Marca "Sin lactosa": solo saca lo que Mochi muestra.', click: { sel: ".agent-prefs-chip", text: "Sin lactosa" }, after: 900 },
      { say: "Y su cocina favorita: sushi.", click: { sel: ".agent-prefs-chip", text: "🍣 Sushi" }, after: 900 },
      { say: "Guarda.", click: { sel: ".sheet-confirm-primary", text: "Guardar" }, after: 1600 },
      { say: '"Pedir por mí": por defecto, Mochi revisa antes de pedir.', click: { sel: ".agent-search-body button", text: "Pedir por mí" }, after: 1600 },
      { say: "Le da permiso en una tienda donde ya pidió.", click: { sel: ".agent-autonomy-mode", text: "Pedir por mí" }, after: 900 },
      { say: "Le da permiso en una tienda donde ya pidió.", click: { sel: ".agent-prefs-chip", text: "Akira" }, after: 900 },
      { say: "Guarda.", click: { sel: ".sheet-confirm-primary", text: "Guardar" }, after: 1600 },
      { say: '"Repite lo de siempre".', click: { sel: ".agent-capability", text: "Repite lo de siempre" }, after: 2400 },
      { say: "Mochi lo pide solo, con unos segundos para deshacer.", click: { sel: ".agent-msg-action", text: "Pide lo de siempre por mí" }, after: 3600 },
      backHome(),
    ],
  },
  {
    id: "personas",
    title: "7 · Cambiar de persona",
    steps: [
      ...persona("asiático", "Perfil asiático: el buscador muestra su escalera."),
      backHome(),
      ...persona("café", "Cambia a amante del café: el buscador se adapta."),
      backHome(),
      ...persona("Mascotero", "Y a mascotero: otras ideas, otras verticales."),
      backHome(),
    ],
  },
  {
    id: "rappihoy",
    title: "8 · Rappi hoy frente al MVP",
    steps: [
      { say: "Compara con Rappi hoy: la Home de siempre, sin Mochi.", click: { panel: ".mode", text: "Rappi hoy" }, after: 2400 },
      { say: "Compara con Rappi hoy: la Home de siempre, sin Mochi.", scroll: { in: { sel: ".home-shortcut" }, by: 500 } },
      { say: "Y de vuelta al MVP.", click: { panel: ".mode", text: "MVP" }, after: 2400 },
    ],
  },
  {
    id: "panel",
    title: "9 · El panel de negocio",
    steps: [
      { say: "Lo que ve Rappi: el panel de negocio.", click: { panel: "#biz-open" }, after: 2600 },
      { say: "Resumen: cómo va el negocio y qué decidir.", click: { biz: "[role=tab]", text: "Resumen" }, after: 1800 },
      { say: "Resumen: cómo va el negocio y qué decidir.", scroll: { to: { biz: "h2, h3", text: "Qué decidir" } } },
      { say: "Resumen: cómo va el negocio y qué decidir.", wait: 1800 },
      { say: "Retención y venta cruzada: dónde está y a quién estamos perdiendo.", click: { biz: "[role=tab]", text: "Retención" }, after: 2400 },
      { say: "Retención y venta cruzada: dónde está y a quién estamos perdiendo.", click: { biz: ".subnav button", text: "En riesgo" }, after: 1800 },
      { say: "Retención y venta cruzada: dónde está y a quién estamos perdiendo.", scroll: { to: { biz: "h2, h3", text: "A quién estamos perdiendo" } } },
      { say: "Retención y venta cruzada: dónde está y a quién estamos perdiendo.", wait: 1800 },
      { say: "Mochi y búsquedas: lo que ofrece Mochi y lo que no se encuentra.", click: { biz: "[role=tab]", text: "Mochi y búsquedas" }, after: 2400 },
      { say: "¿Mochi molesta? Cuántas personas lo ocultaron y cuántas lo trajeron de vuelta.", scroll: { to: { biz: "h2, h3", text: "molesta" } } },
      { say: "¿Mochi molesta? Cuántas personas lo ocultaron y cuántas lo trajeron de vuelta.", wait: 1800 },
      { say: "Mochi y búsquedas: lo que ofrece Mochi y lo que no se encuentra.", click: { biz: ".subnav button", text: "Búsquedas" }, after: 1800 },
      { say: "Mochi y búsquedas: lo que ofrece Mochi y lo que no se encuentra.", scroll: { to: { biz: "h2, h3", text: "Qué buscan y no encuentran" } } },
      { say: "Mochi y búsquedas: lo que ofrece Mochi y lo que no se encuentra.", wait: 1800 },
      { say: "Cierra el panel.", click: { panel: "#biz-close" } },
    ],
  },
];

/* Un botón por capítulo en "O recorre una parte" */
document.getElementById("chapters").replaceChildren(...CHAPTERS.map((c) => {
  const b = document.createElement("button");
  b.className = "tour-one";
  b.dataset.id = c.id;
  b.setAttribute("aria-pressed", "false");
  b.innerHTML = '<span class="icon icon-play"></span><span class="label"></span>';
  b.querySelector(".label").textContent = c.title;
  return b;
}));
playBtn.addEventListener("click", () => { if (!tour) startTour(CHAPTERS.map((c) => c.id), true, playBtn); });
document.querySelectorAll(".tour-one").forEach((b) =>
  b.addEventListener("click", () => { panRun++; startTour([b.dataset.id], false, b); }));
stopBtn.addEventListener("click", () => { panRun++; stopTour(); });

load().then(syncControls);
