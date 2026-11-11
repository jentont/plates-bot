/* Мини-апа «Номера». Vanilla JS, без сборки. */
(() => {
  "use strict";

  const tg = window.Telegram && window.Telegram.WebApp;
  const I = window.I18N;
  const t = s => I.t(s);
  const $ = (s, r = document) => r.querySelector(s);
  const $$ = (s, r = document) => Array.from(r.querySelectorAll(s));
  const sleep = ms => new Promise(r => setTimeout(r, ms));
  const esc = s => String(s).replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

  const RU_LETTERS = "АВЕКМНОРСТУХ";
  const LAT = "ABEKMHOPCTYX";            // те же начертания латиницей: шрифт номера без кириллицы
  const LATIN = "ABCDEFGHJKLMNPRSTUVWXYZ";
  const DIGITS = "0123456789";

  const state = {
    user: null, ai: false, energy: { current: 0, max: 30, next_in: 0 }, packs: [],
    settings: { mode: "ru", countries: [] }, countries: [], garage: [], stats: {},
    current: null, rolling: false, tab: "spin",
    feed: { count: 0, rare: 0, best: null, es: null },
  };

  /* ------------------------------------------------------------ Telegram */
  if (tg) {
    tg.ready(); tg.expand();
    try { tg.setHeaderColor("#0A0A0C"); tg.setBackgroundColor("#0A0A0C"); tg.setBottomBarColor("#0A0A0C"); } catch (e) { /* старый клиент */ }
    try { tg.disableVerticalSwipes(); } catch (e) { /* старый клиент */ }
  }
  const hf = (kind, arg) => { try { tg.HapticFeedback[kind](arg); } catch (e) { /* нет вибро */ } };
  const haptic = { tap: () => hf("impactOccurred", "light"), hit: () => hf("impactOccurred", "medium"), heavy: () => hf("impactOccurred", "heavy"), ok: () => hf("notificationOccurred", "success"), warn: () => hf("notificationOccurred", "warning"), tick: () => hf("selectionChanged") };

  /* ------------------------------------------------------------ API */
  async function api(path, body) {
    const headers = { "X-Init-Data": (tg && tg.initData) || "" };
    const opt = body ? { method: "POST", headers: { ...headers, "Content-Type": "application/json" }, body: JSON.stringify(body) } : { headers };
    const r = await fetch("api/" + path, opt);
    const data = await r.json().catch(() => ({}));
    if (!r.ok) throw Object.assign(new Error(data.error || t("Нет связи с сервером")), { code: data.error, data });
    return data;
  }

  /* ------------------------------------------------------------ TGS-иконки */
  const iconCache = new Map();
  const loadIcon = name => {
    if (!iconCache.has(name)) iconCache.set(name, fetch("static/icons/" + name + ".tgs?v=5").then(r => r.arrayBuffer()).then(b => JSON.parse(window.pako.ungzip(new Uint8Array(b), { to: "string" }))));
    return iconCache.get(name);
  };
  function mountIcons(root = document) {
    if (!window.lottie || !window.pako) return;
    $$(".ico[data-icon]", root).forEach(async el => {
      if (el.dataset.mounted) return;
      el.dataset.mounted = "1";
      try {
        const anim = window.lottie.loadAnimation({ container: el, renderer: "svg", loop: false, autoplay: false, animationData: await loadIcon(el.dataset.icon) });
        el._anim = anim;
        anim.addEventListener("DOMLoaded", () => anim.goToAndStop(anim.totalFrames - 1, true));
      } catch (e) { /* иконка необязательна */ }
    });
  }
  const playIcon = el => { if (el && el._anim) el._anim.goToAndPlay(0, true); };

  /* ------------------------------------------------------------ Формат */
  const group = n => Math.round(n).toString().replace(/\B(?=(\d{3})+(?!\d))/g, " ");
  const fmtMoney = (n, cur) => cur === "RUB" ? group(n || 0) + " ₽" : "$" + group(n || 0);
  const priceOf = (plate, ev) => plate.country === "RU" ? [ev.price_rub, "RUB"] : [ev.price_usd, "USD"];
  const priceText = (plate, ev) => fmtMoney(...priceOf(plate, ev));
  const pad = n => (n < 10 ? "0" : "") + n;
  const clock = () => { const d = new Date(); return pad(d.getHours()) + ":" + pad(d.getMinutes()) + ":" + pad(d.getSeconds()); };
  const fmtTimer = sec => { sec = Math.max(0, Math.round(sec)); return Math.floor(sec / 60) + ":" + pad(sec % 60); };
  const countryName = code => I.country(code, (state.countries.find(c => c.code === code) || { name: code }).name);
  const tierName = ev => I.tier(ev.tier, ev.tier_name);
  const flagSrc = code => `static/img/flags/${code.toLowerCase()}.svg`;
  const ball = (code, cls = "") => `<i class="ball ${cls}"><img src="${flagSrc(code)}" alt=""></i>`;
  const place = plate => countryName(plate.country) + (plate.region_name && plate.region_name !== countryName(plate.country) && I.lang === "ru" ? " · " + plate.region_name : "");

  /* ------------------------------------------------------------ Номер */
  const glyph = ch => { const i = RU_LETTERS.indexOf(ch); return i >= 0 ? LAT[i] : ch; };
  const kind = ch => DIGITS.includes(ch) ? "d" : (RU_LETTERS.includes(ch) || /[A-Z]/.test(ch)) ? "l" : "x";
  const alphabet = ch => DIGITS.includes(ch) ? DIGITS : RU_LETTERS.includes(ch) ? LAT : /[A-Z]/.test(ch) ? LATIN : "";
  const slot = (ch, cls = "") => `<span class="slot ${kind(ch)} ${cls}" data-final="${esc(glyph(ch))}" data-alpha="${alphabet(ch)}">${esc(glyph(ch))}</span>`;
  const slots = (str, cls) => Array.from(str).map(c => c === " " ? '<span class="gap"></span>' : slot(c, cls)).join("");
  const unitsOf = str => Array.from(str).reduce((a, c) => a + (c === " " ? .16 : DIGITS.includes(c) ? .56 : /[A-ZА-Я]/.test(c) ? .64 : c.charCodeAt(0) > 0x2E80 ? 1.02 : .5), 0);
  const fit = (str, room, max = 18.6) => Math.min(max, room / unitsOf(str)).toFixed(2);

  function plateHTML(p) {
    const st = p.style, x = p.parts, cc = p.country;
    if (st === "ru") {
      return `<div class="plate plate-ru"><div class="plate-main"><div class="chars">${slot(x.l1, "sm")}<span class="gap"></span>${slots(x.digits)}<span class="gap"></span>${slot(x.l2, "sm")}${slot(x.l3, "sm")}</div></div>
        <div class="plate-region"><div class="chars">${slots(x.region)}</div><div class="region-foot"><span>RUS</span><i class="tricolor"></i></div></div></div>`;
    }
    if (st === "us") return `<div class="plate plate-us"><div class="plate-state">${esc((p.region_name || "").toUpperCase())}</div><div class="plate-main"><div class="chars" style="font-size:${fit(p.text, 88, 14)}cqw">${slots(p.text)}</div></div></div>`;
    if (st === "ae") { const s = x.code + " " + x.num; return `<div class="plate plate-ae"><div class="plate-strip">${esc(x.emirate.toUpperCase())}</div><div class="plate-main"><div class="chars" style="font-size:${fit(s, 66)}cqw">${slots(s)}</div></div></div>`; }
    if (st === "jp" || st === "kr" || st === "cn" || st === "gb") return `<div class="plate plate-${st}"><div class="plate-main"><div class="chars" style="font-size:${fit(p.text, 88, 16)}cqw">${slots(p.text)}</div></div></div>`;
    return `<div class="plate plate-${st}"><div class="plate-strip"><img src="${flagSrc(cc)}" alt=""><span>${cc}</span></div><div class="plate-main"><div class="chars" style="font-size:${fit(p.text, 78, 16.5)}cqw">${slots(p.text)}</div></div></div>`;
  }
  const framed = (p, lip = "НОМЕРА", color = "") => `<div class="pf" ${color ? `style="--tier:${color}"` : ""}>${plateHTML(p)}<div class="pf-lip"><span>${esc(lip)}</span></div><div class="pf-glare"></div></div>`;
  const mini = (p, cls = "mini") => `<span class="pw ${cls}">${plateHTML(p)}</span>`;
  const ruPlate = (l1, digits, l2, l3, region) => ({ style: "ru", country: "RU", region_name: "", parts: { l1, digits, l2, l3, region }, text: `${l1}${digits}${l2}${l3} ${region}` });

  function startRolling(root) {
    const list = $$(".slot", root).filter(s => s.dataset.alpha);
    list.forEach(s => s.classList.add("is-rolling"));
    const tick = () => list.forEach(s => { const a = s.dataset.alpha; s.textContent = a[Math.floor(Math.random() * a.length)]; });
    tick();
    const timer = setInterval(tick, 55);
    return () => clearInterval(timer);
  }
  function settle(root, step = 85) {
    const list = $$(".slot", root);
    return new Promise(resolve => {
      if (!list.length) return resolve();
      list.forEach((s, i) => setTimeout(() => {
        s.textContent = s.dataset.final; s.classList.remove("is-rolling"); s.classList.add("is-stamp");
        haptic.tick();
        if (i === list.length - 1) setTimeout(resolve, 260);
      }, i * step));
    });
  }
  function countUp(el, to, cur, ms = 900) {
    if (!to) { el.textContent = fmtMoney(0, cur); return; }
    const t0 = performance.now();
    const step = now => { const k = Math.min(1, (now - t0) / ms), e = 1 - Math.pow(1 - k, 4); el.textContent = fmtMoney(to * e, cur); if (k < 1) requestAnimationFrame(step); };
    requestAnimationFrame(step);
  }

  /* ------------------------------------------------------------ Параллакс */
  const plx = { tx: 0, ty: 0, x: 0, y: 0, last: 0 };
  const clamp = (v, a = -1, b = 1) => Math.max(a, Math.min(b, v));
  function onTilt(beta, gamma) { plx.tx = clamp(gamma / 28); plx.ty = clamp((beta - 42) / 28); plx.last = performance.now(); }
  window.addEventListener("deviceorientation", e => { if (e.gamma != null && e.beta != null) onTilt(e.beta, e.gamma); });
  try {
    if (tg && tg.DeviceOrientation && tg.DeviceOrientation.start) {
      tg.DeviceOrientation.start({ refresh_rate: 60 });
      tg.onEvent("deviceOrientationChanged", () => onTilt(tg.DeviceOrientation.beta * 57.3, tg.DeviceOrientation.gamma * 57.3));
    }
  } catch (e) { /* датчик недоступен */ }
  window.addEventListener("pointermove", e => { plx.tx = clamp((e.clientX / innerWidth - .5) * 2); plx.ty = clamp((e.clientY / innerHeight - .5) * 2); plx.last = performance.now(); });
  $$(".plx").forEach(el => el.style.setProperty("--d", el.dataset.depth));
  const reduced = matchMedia("(prefers-reduced-motion: reduce)").matches;
  requestAnimationFrame(function loop(now) {
    if (!document.hidden) {
      if (now - plx.last > 1800 && !reduced) { plx.tx = Math.sin(now / 1900) * .42; plx.ty = Math.cos(now / 2600) * .3; }   // без наклона сцена слегка дышит
      plx.x += (plx.tx - plx.x) * .08; plx.y += (plx.ty - plx.y) * .08;
      document.documentElement.style.setProperty("--px", plx.x.toFixed(3));
      document.documentElement.style.setProperty("--py", plx.y.toFixed(3));
      fxStep();
    }
    requestAnimationFrame(loop);
  });

  /* ------------------------------------------------------------ Искры при приземлении */
  const fx = $("#fx"), fxc = fx.getContext("2d");
  let sparks = [];
  function fxResize() { const r = fx.getBoundingClientRect(), d = Math.min(2, devicePixelRatio || 1); fx.width = r.width * d; fx.height = r.height * d; fxc.setTransform(d, 0, 0, d, 0, 0); }
  function burst(color, power) {
    if (reduced) return;
    fxResize();
    const r = fx.getBoundingClientRect(), cx = r.width / 2, cy = r.height * .5, n = Math.round(10 + power * 70);
    for (let i = 0; i < n; i++) {
      const a = Math.random() * Math.PI * 2, v = 2 + Math.random() * (4 + power * 9);
      sparks.push({ x: cx + Math.cos(a) * r.width * .3, y: cy + Math.sin(a) * 18, vx: Math.cos(a) * v, vy: Math.sin(a) * v * .7 - 2.5, life: 1, s: 1 + Math.random() * 2.4, c: Math.random() < .45 ? "#FFFFFF" : color });
    }
  }
  function fxStep() {
    if (!sparks.length) return;
    const r = fx.getBoundingClientRect();
    fxc.clearRect(0, 0, r.width, r.height);
    sparks = sparks.filter(p => p.life > 0);
    for (const p of sparks) {
      p.x += p.vx; p.y += p.vy; p.vy += .22; p.vx *= .985; p.life -= .018;
      fxc.globalAlpha = Math.max(0, p.life); fxc.strokeStyle = p.c; fxc.lineWidth = p.s; fxc.lineCap = "round";
      fxc.beginPath(); fxc.moveTo(p.x, p.y); fxc.lineTo(p.x - p.vx * 2.2, p.y - p.vy * 2.2); fxc.stroke();
    }
    fxc.globalAlpha = 1;
  }

  /* ------------------------------------------------------------ Экран: крутить */
  const scene = $("#scene"), rig = $("#rig"), result = $("#result"), btnSpin = $("#btn-spin");
  const demoPlate = () => Object.assign(ruPlate("А", "777", "А", "А", "777"), { region_name: "Москва" });
  const setSpinLabel = key => { $("#btn-spin-label").textContent = t(key); };

  const tilt = (plate, lip, color) => `<div class="rig-tilt">${framed(plate, lip, color)}</div>`;
  function mountPlate(plate, lip, color, cls = "") {
    const el = document.createElement("div");
    el.className = "rig-item " + cls;
    el.innerHTML = tilt(plate, lip, color);
    rig.appendChild(el);
    return el;
  }
  function dropOld() {
    $$(".rig-item", rig).forEach(el => { el.className = "rig-item rig-out"; setTimeout(() => el.remove(), 380); });
  }
  function setTier(color) { $("#app").style.setProperty("--tier", color); }

  function renderResult(plate, ev, box = result, animate = true) {
    box.style.setProperty("--tier", ev.tier_color);
    $(".tier span", box).textContent = tierName(ev);
    $(".rank", box).textContent = ev.percentile <= 50 ? `${t("топ")} ${ev.percentile || "0.01"}%` : "";
    const [val, cur] = priceOf(plate, ev), priceEl = $(".price", box);
    if (animate) countUp(priceEl, val, cur); else priceEl.textContent = fmtMoney(val, cur);
    $(".reasons", box).innerHTML = ev.reasons.map(r => `<li class="${r.points ? "" : "zero"}"><span>${esc(r.title)}</span><b>${r.points ? "+" + r.points : ""}</b></li>`).join("");
    box.hidden = false;
  }
  function syncActions() {
    const roll = state.current, save = $("#btn-save");
    save.classList.toggle("is-done", !!(roll && roll.saved));
    $("span:last-child", save).textContent = t(roll && roll.saved ? "В гараже" : "В гараж");
    $("#btn-share").classList.remove("is-done");
    $("#btn-ai").hidden = !state.ai; $("#ai-box").hidden = true;
  }
  function showCurrent(animate) {
    const roll = state.current;
    rig.innerHTML = "";
    if (!roll) { mountPlate(demoPlate(), "НОМЕРА"); setTier("#8E97A8"); result.hidden = true; $("#spin-hint").hidden = false; $("#scene-caption").textContent = ""; return; }
    mountPlate(roll.plate, tierName(roll.eval), roll.eval.tier_color);
    setTier(roll.eval.tier_color);
    $("#scene-caption").textContent = place(roll.plate);
    renderResult(roll.plate, roll.eval, result, animate);
    $("#spin-hint").hidden = true;
    setSpinLabel("Крутить ещё");
    syncActions();
  }

  const LADDER = [["common", "#8E97A8", 0, "0 ₽"], ["uncommon", "#5FB2FF", 12, "10 000 ₽"], ["rare", "#7C6CFF", 28, "50 000 ₽"], ["epic", "#E85CFF", 45, "270 000 ₽"], ["legendary", "#FFB020", 62, "1 500 000 ₽"], ["mythic", "#FF3B3B", 80, "9 000 000 ₽"]];
  const history = [];
  function renderExtras() {
    const ev = state.current && state.current.eval, pos = ev ? LADDER.findIndex(l => l[0] === ev.tier) : -1, next = LADDER[pos + 1];
    $("#ladder").innerHTML = ev ? `<div class="scale-bar">${LADDER.map((l, i) => `<i class="${i <= pos ? "is-on" : ""}" style="--c:${l[1]}"></i>`).join("")}</div>
      <div class="scale-foot"><span>${ev.score} ${t("очков")}</span>${next ? `<span><b style="color:${next[1]}">${esc(I.tier(next[0]))}</b> ${t("от")} ${next[2]}</span>` : ""}</div>` : "";
    $("#recent-head").hidden = !history.length;
    $("#recent").innerHTML = history.map(r => `<div class="recent-item" style="--tier:${r.eval.tier_color}">${mini(r.plate, "")}<b>${priceText(r.plate, r.eval)}</b><small>${esc(tierName(r.eval))}</small></div>`).join("");
  }

  async function spin(recheck) {
    if (state.rolling) return;
    if (state.energy.current <= 0) { haptic.warn(); openEnergy(true); return; }
    state.rolling = true;
    btnSpin.classList.add("is-rolling"); setSpinLabel("Крутим…");
    result.hidden = true; $("#spin-hint").hidden = true; $("#scene-caption").textContent = "";
    window.scrollTo({ top: 0, behavior: "smooth" });
    haptic.hit();

    // старый номер падает вниз, пустая заготовка влетает сверху и крутит символы
    const prev = state.current ? state.current.plate : demoPlate();
    if (state.current) { history.unshift(state.current); history.length = Math.min(history.length, 10); }
    dropOld();
    scene.classList.add("is-fast");
    const blank = mountPlate(prev.style === "ru" ? prev : demoPlate(), "· · ·", "#8E97A8", "rig-drop");
    let stop = startRolling(blank);
    const t0 = performance.now();
    let roll, err;
    try { roll = (await api("spin", recheck === true ? { recheck: true } : {})).roll; } catch (e) { err = e; }
    await sleep(Math.max(0, 900 - (performance.now() - t0)));
    stop();

    if (err) {
      scene.classList.remove("is-fast"); state.rolling = false; btnSpin.classList.remove("is-rolling");
      showCurrent(false); if (!state.current) setSpinLabel("Крутить");
      if (err.code === "no_energy") { if (err.data.energy) setEnergy(err.data.energy); openEnergy(true); }
      else if (err.code === "subscribe") openSponsors(err.data.sponsors || []);
      else toast(err.message);
      haptic.warn();
      return;
    }

    state.current = roll;
    if (roll.energy) setEnergy(roll.energy);
    // настоящий номер: если формат тот же, символы встают на место в той же заготовке
    let item = blank;
    if (roll.plate.style !== "ru" || (prev.style !== "ru")) {
      blank.remove();
      item = mountPlate(roll.plate, "· · ·", "#8E97A8", "rig-hold");
    } else {
      blank.className = "rig-item rig-hold";
      blank.innerHTML = tilt(roll.plate, "· · ·", "#8E97A8");
    }
    stop = startRolling(item);
    await sleep(160);
    stop();
    await settle(item);

    // удар: рамка получает цвет редкости, сцена вздрагивает, летят искры
    const ev = roll.eval, power = Math.min(1, ev.score / 80);
    scene.classList.remove("is-fast");
    item.className = "rig-item rig-slam";
    $(".pf", item).style.setProperty("--tier", ev.tier_color);
    $(".pf-lip span", item).textContent = tierName(ev);
    setTier(ev.tier_color);
    scene.classList.remove("is-shake"); void scene.offsetWidth; scene.classList.add("is-shake");
    burst(ev.tier_color, power);
    if (ev.score >= 45) { haptic.heavy(); setTimeout(haptic.heavy, 140); } else if (ev.score >= 12) haptic.ok(); else haptic.hit();

    $("#scene-caption").textContent = place(roll.plate);
    renderResult(roll.plate, ev);
    syncActions(); renderExtras();
    state.rolling = false; btnSpin.classList.remove("is-rolling"); setSpinLabel("Крутить ещё");
  }

  async function saveCurrent() {
    const roll = state.current;
    if (!roll || roll.saved) return;
    try {
      const r = await api("save", { roll_id: roll.id });
      roll.saved = true; state.garage = r.garage;
      syncActions(); playIcon($(".ico", $("#btn-save"))); haptic.ok();
      toast(t(r.forever ? "Сохранено навсегда" : "Сохранено в гараж"));
    } catch (e) {
      haptic.warn();
      if (e.code === "garage_full" && e.data.invoice_url && tg) tg.openInvoice(e.data.invoice_url, s => { if (s === "paid") { roll.saved = true; syncActions(); refresh(); toast(t("Сохранено навсегда")); } });
      else toast(e.code === "garage_full" ? t("Гараж полон. Освободи место или сохрани навсегда в боте") : e.message);
    }
  }
  async function shareCurrent() {
    if (!state.current) return;
    try { await api("share", { roll_id: state.current.id }); $("#btn-share").classList.add("is-done"); playIcon($(".ico", $("#btn-share"))); haptic.ok(); toast(t("Карточка отправлена в чат с ботом")); }
    catch (e) { toast(e.message); haptic.warn(); }
  }
  async function aiCurrent() {
    const roll = state.current; if (!roll) return;
    const b = $("#btn-ai"), box = $("#ai-box");
    b.disabled = true;
    try {
      const d = await api("ai", { roll_id: roll.id });
      box.innerHTML = `<b>${fmtMoney(d.price, roll.plate.country === "RU" ? "RUB" : "USD")}</b>${esc(d.comment)}<small>${t("Нейросеть")}</small>`;
      box.hidden = false; haptic.ok();
    } catch (e) { toast(e.message); haptic.warn(); }
    b.disabled = false;
  }

  /* ------------------------------------------------------------ Энергия */
  let energyTimer = null;
  function setEnergy(en, bump) {
    const grew = en.current > state.energy.current;
    state.energy = en;
    $("#energy-val").textContent = en.current;
    if (bump || grew) { const el = $("#energy"); el.classList.remove("is-bump"); void el.offsetWidth; el.classList.add("is-bump"); }
    clearInterval(energyTimer);
    const tick = () => {
      if (en.current >= en.max) { $("#energy-timer").textContent = ""; return; }
      $("#energy-timer").textContent = fmtTimer(en.next_in);
      if (--en.next_in < 0) { clearInterval(energyTimer); api("energy").then(setEnergy).catch(() => {}); }
    };
    tick(); energyTimer = setInterval(tick, 1000);
  }
  function openEnergy(empty) {
    const en = state.energy;
    openSheet(`<h2>${t(empty ? "Энергия кончилась" : "Энергия")}</h2>
      <p>${t("Один бросок тратит одну энергию. Она восстанавливается сама, а можно пополнить сразу")}${en.current < en.max ? ` · +1 ${fmtTimer(en.next_in)}` : ""}</p>
      <div class="packs">${state.packs.map((p, i) => `<button class="pack" type="button" data-pack="${esc(p.id)}">
        <span class="pack-art">${'<img src="static/img/3d/bolt.png" alt="">'.repeat(i + 1)}</span>
        <span class="pack-name"><b>+${p.amount}</b><small>${p.amount} ${t("бросков")}</small></span>
        <span class="pack-price"><img src="static/img/3d/star.png" alt="">${p.stars}</span></button>`).join("")}</div>`);
    $$(".pack", $("#sheet")).forEach(b => b.addEventListener("click", () => buyEnergy(b.dataset.pack)));
  }
  async function buyEnergy(pack) {
    haptic.tap();
    try {
      const r = await api("energy/buy", { pack });
      if (r.energy) { closeSheet(); setEnergy(r.energy, true); haptic.ok(); toast(t("Энергия пополнена")); return; }
      if (r.invoice_url && tg) tg.openInvoice(r.invoice_url, async status => {
        if (status !== "paid") return;
        closeSheet();
        const before = state.energy.current;
        for (let i = 0; i < 8; i++) { await sleep(700); try { const en = await api("energy"); if (en.current > before) { setEnergy(en, true); haptic.ok(); toast(t("Энергия пополнена")); return; } } catch (e) { /* повторим */ } }
      });
    } catch (e) { toast(e.message); haptic.warn(); }
  }

  /* ------------------------------------------------------------ Обязательная подписка */
  function openSponsors(list) {
    openSheet(`<h2>${t("Подпишись на спонсоров")}</h2><p>${t("Чтобы крутить номера, подпишись на каналы ниже и нажми «Проверить подписку»")}</p>
      <div class="packs">${list.map(s => `<button class="pack" type="button" data-link="${esc(s.link)}">
        <span class="pack-art"><img src="static/img/3d/key.png" alt=""></span>
        <span class="pack-name"><b>${esc(s.title)}</b><small>${t("Подписаться")}</small></span></button>`).join("")}</div>
      <button class="btn btn-primary btn-wide" id="sp-check" type="button">${t("Проверить подписку")}</button>`);
    $$(".pack[data-link]", $("#sheet")).forEach(b => b.addEventListener("click", () => {
      haptic.tap();
      const link = b.dataset.link;
      if (!link) return;
      if (tg && link.startsWith("https://t.me/")) tg.openTelegramLink(link);
      else if (tg) tg.openLink(link);
      else window.open(link, "_blank");
    }));
    $("#sp-check").addEventListener("click", () => { closeSheet(); spin(true); });
  }

  /* ------------------------------------------------------------ Шторка */
  function openSheet(html) { const s = $("#sheet"); s.innerHTML = html; s.hidden = false; $("#sheet-back").hidden = false; }
  function closeSheet() { $("#sheet").hidden = true; $("#sheet-back").hidden = true; }
  $("#sheet-back").addEventListener("click", closeSheet);
  const langsHTML = () => `<div class="langs">${I.LANGS.map(([code, name, flag]) => `<button class="lang ${code === I.lang ? "is-on" : ""}" type="button" data-lang="${code}">${ball(flag)}<span>${name}</span></button>`).join("")}</div>`;
  function openLang() {
    openSheet(`<h2>${t("Язык")}</h2><p></p>${langsHTML()}`);
    $$(".lang", $("#sheet")).forEach(b => b.addEventListener("click", () => { haptic.tap(); I.set(b.dataset.lang); applyLang(); closeSheet(); }));
  }

  /* ------------------------------------------------------------ Лента */
  function startFeed() {
    if (state.feed.es) return;
    const es = new EventSource("api/feed"), box = $("#feed");
    state.feed.es = es;
    es.onmessage = msg => {
      const { plate, eval: e } = JSON.parse(msg.data), f = state.feed, rare = e.score >= 28, [val] = priceOf(plate, e);
      f.count += 1; if (rare) f.rare += 1;
      const rub = plate.country === "RU" ? val : val * 90;
      if (!f.best || rub > f.best) { f.best = rub; $("#feed-best").textContent = priceText(plate, e); }
      $("#feed-count").textContent = f.count; $("#feed-rare").textContent = f.rare;
      const row = document.createElement("div");
      row.className = "feed-row" + (rare ? " is-rare" : "");
      row.style.setProperty("--tier", e.tier_color);
      row.innerHTML = `${mini(plate)}<div class="feed-info"><b class="${e.score >= 12 ? "t" : ""}">${esc(tierName(e))}</b><small>${esc(countryName(plate.country))} · ${clock()}</small></div><div class="feed-price ${val ? "" : "zero"}">${val ? priceText(plate, e) : "—"}</div>`;
      box.prepend(row);
      while (box.children.length > 30) box.lastChild.remove();
    };
    es.onerror = () => { es.close(); state.feed.es = null; setTimeout(() => { if (state.tab === "feed") startFeed(); }, 3000); };
  }
  function stopFeed() { if (state.feed.es) { state.feed.es.close(); state.feed.es = null; } }

  /* ------------------------------------------------------------ Гараж и топ */
  function fmtTtl(expires) { const s = Math.max(0, Math.round(expires - Date.now() / 1000)); return s > 3600 ? Math.floor(s / 3600) + " " + t("ч") : Math.max(1, Math.floor(s / 60)) + " " + t("мин"); }
  function renderGarage() {
    const g = state.garage;
    $("#garage-empty").hidden = true;
    $("#garage-stats").innerHTML = `<div><b>${state.stats.spins || 0}</b><span>${t("прокруток")}</span></div><div><b>${state.stats.best_score || 0}</b><span>${t("рекорд очков")}</span></div><div><b>${g.length}/${state.stats.slots || 0}</b><span>${t("мест в гараже")}</span></div>`;
    $("#garage-list").innerHTML = g.map((r, i) => `<div class="garage-item" style="--tier:${r.eval.tier_color};animation-delay:${i * 50}ms">${mini(r.plate, "mid")}
      <div class="garage-info"><b>${priceText(r.plate, r.eval)}</b><span>${esc(tierName(r.eval))} · ${r.eval.score}</span><small>${r.forever ? t("навсегда") : `${t("сгорит через")} ${fmtTtl(r.expires)}`}</small></div></div>`).join("")
      + Array.from({ length: Math.max(0, Math.min(5, (state.stats.slots || 0) - g.length)) }, () => `<div class="garage-item is-free"><span class="pw mid"><span class="slot-free"></span></span><div class="garage-info"><small>${t("Свободное место")}</small></div></div>`).join("");
  }
  async function loadTop() {
    try {
      const top = await api("top");
      const initial = n => esc((n || "?").trim().charAt(0).toUpperCase());
      const pod = top.slice(0, 3), rest = top.slice(3);
      $("#top-list").innerHTML = top.length
        ? `<div class="podium">${[1, 0, 2].filter(i => pod[i]).map(i => `<div class="pod pod-${i + 1}"><span class="pod-ava">${initial(pod[i].name)}<img src="static/img/3d/medal${i + 1}.png" alt=""></span><b>${esc(pod[i].name)}</b><small>${esc(pod[i].plate_text)}</small><span class="pod-step"><b>${pod[i].score}</b><i>${t("очков")}</i></span></div>`).join("")}</div>`
          + (rest.length ? `<div class="board">${rest.map((p, i) => `<div class="board-row"><span class="board-place">${i + 4}</span><span class="board-ava">${initial(p.name)}</span><span class="board-name"><b>${esc(p.name)}</b><small>${esc(p.plate_text)}</small></span><span class="board-score">${p.score}</span></div>`).join("")}</div>` : "")
        : `<div class="board"><div class="board-row"><span class="board-name"><b>${t("Пока никого. Стань первым")}</b></span></div></div>`;
    } catch (e) { /* топ необязателен */ }
  }

  /* ------------------------------------------------------------ Страны */
  function renderWorld() {
    const { mode, countries } = state.settings, modes = ["ru", "world", "custom"];
    $("#mode-seg").style.setProperty("--seg", modes.indexOf(mode));
    $$("#mode-seg button").forEach(b => b.classList.toggle("is-on", b.dataset.mode === mode));
    const grid = $("#country-grid");
    grid.classList.toggle("is-locked", mode !== "custom");
    const on = c => mode === "world" || (mode === "ru" ? c === "RU" : countries.includes(c));
    grid.innerHTML = state.countries.map(c => `<button type="button" class="globe ${on(c.code) ? "is-on" : ""}" data-code="${c.code}">${ball(c.code)}<span>${esc(countryName(c.code))}</span></button>`).join("");
    const label = mode === "ru" ? t("Россия") : mode === "world" ? t("Весь мир") : `${countries.length} ${t("стран")}`;
    $("#scene-mode").innerHTML = (mode === "ru" ? ball("RU", "sm") : `<img src="static/img/3d/globe.png" alt="">`) + `<span>${esc(label)}</span>`;
    $("#row-lang-val").textContent = (I.LANGS.find(l => l[0] === I.lang) || [])[1] || "";
  }
  async function saveSettings(patch) {
    state.settings = { ...state.settings, ...patch };
    renderWorld();
    try { state.settings = await api("settings", state.settings); } catch (e) { toast(e.message); }
  }
  $("#mode-seg").addEventListener("click", e => {
    const b = e.target.closest("button"); if (!b) return;
    haptic.tap();
    const patch = { mode: b.dataset.mode };
    if (b.dataset.mode === "custom" && !state.settings.countries.length) patch.countries = ["RU", "DE", "US", "AE"];
    saveSettings(patch);
  });
  $("#country-grid").addEventListener("click", e => {
    const b = e.target.closest(".globe"); if (!b) return;
    haptic.tap();
    const set = new Set(state.settings.mode === "custom" ? state.settings.countries : state.settings.mode === "world" ? state.countries.map(c => c.code) : ["RU"]);
    set.has(b.dataset.code) ? set.delete(b.dataset.code) : set.add(b.dataset.code);
    if (!set.size) return toast(t("Оставь хотя бы одну страну"));
    saveSettings({ mode: "custom", countries: Array.from(set) });   // нажатие на шар сразу включает «свой набор»
  });
  $("#scene-mode").addEventListener("click", () => openTab("world"));
  $("#estimate-form").addEventListener("submit", async e => {
    e.preventDefault();
    const text = $("#estimate-input").value.trim(); if (!text) return;
    haptic.tap(); $("#estimate-input").blur();
    try {
      const { plate, eval: ev } = await api("estimate", { text }), box = $("#estimate-result");
      box.innerHTML = `${framed(plate, tierName(ev), ev.tier_color)}<div class="result"><div class="result-head"><span class="tier"><i></i><span></span></span><span class="rank"></span></div><div class="price"></div><ul class="reasons"></ul></div>`;
      $$(".slot", box).forEach((s, i) => { s.style.animationDelay = i * 50 + "ms"; s.classList.add("is-stamp"); });
      renderResult(plate, ev, $(".result", box));
      haptic.ok();
      box.scrollIntoView({ behavior: "smooth", block: "center" });
    } catch (err) { toast(err.message); haptic.warn(); }
  });
  $("#row-lang").addEventListener("click", () => { haptic.tap(); openLang(); });
  $("#row-tour").addEventListener("click", () => { haptic.tap(); runTour(false); });

  /* ------------------------------------------------------------ Вкладки */
  const TABS = ["spin", "feed", "garage", "world"];
  $("#tabs").addEventListener("click", e => { const b = e.target.closest("button"); if (b) openTab(b.dataset.tab); });
  function openTab(name) {
    if (name === state.tab) { window.scrollTo({ top: 0, behavior: "smooth" }); return; }
    haptic.tap();
    state.tab = name;
    $("#tabs").style.setProperty("--tab", TABS.indexOf(name));
    $$("#tabs button").forEach(b => { const on = b.dataset.tab === name; b.classList.toggle("is-on", on); if (on) playIcon($(".ico", b)); });
    $$(".screen").forEach(s => s.classList.toggle("is-active", s.dataset.screen === name));
    $(".dock").classList.toggle("no-spin", name !== "spin");
    if (name === "feed") startFeed(); else stopFeed();
    if (name === "garage") { renderGarage(); loadTop(); }
    if (name === "world") renderWorld();
    window.scrollTo(0, 0);
  }

  /* ------------------------------------------------------------ Toast */
  let toastTimer;
  function toast(text) { const el = $("#toast"); el.hidden = true; void el.offsetWidth; el.textContent = text; el.hidden = false; clearTimeout(toastTimer); toastTimer = setTimeout(() => { el.hidden = true; }, 2600); }

  /* ------------------------------------------------------------ Язык */
  function applyLang() {
    $$("[data-i18n]").forEach(el => { if (!el.dataset.ru) el.dataset.ru = el.textContent.trim(); el.textContent = t(el.dataset.ru); });
    renderWorld();
    if (state.tab === "garage") { renderGarage(); loadTop(); }
    if (!state.rolling) showCurrent(false);
    if (!state.current) setSpinLabel("Крутить");
    renderExtras();
  }

  /* ------------------------------------------------------------ Знакомство */
  const SLIDES = [
    { h: "Крути номера", p: "Каждый бросок — случайный номер. Российский или любой из 19 стран мира", build: stage => {
      stage.innerHTML = `<div class="slide">${tourPlate(ruPlate("А", "777", "А", "А", "777"), "Мифический", "#FF3B3B", 44, "translate(-50%,-320%) rotateX(60deg) rotateZ(-8deg)", "translate(calc(-50% + var(--px) * 14px),-50%) rotateX(calc(var(--py) * -10deg)) rotateY(calc(var(--px) * 14deg))", 0)}</div>`;
      const stop = startRolling(stage); setTimeout(() => { stop(); settle(stage, 70); }, 900);
    } },
    { h: "У каждого своя цена", p: "Три семёрки, зеркала, блатные серии. Чем реже сочетание, тем дороже номер", build: stage => {
      const rows = [[ruPlate("О", "000", "О", "О", "77"), "legendary", "#FFB020", "12 000 000 ₽", 20], [ruPlate("Е", "001", "К", "Х", "777"), "mythic", "#FF3B3B", "45 000 000 ₽", 46], [ruPlate("Х", "666", "Х", "Х", "95"), "epic", "#E85CFF", "2 400 000 ₽", 72]];
      stage.innerHTML = `<div class="slide">${rows.map(([p, tier, color, price, top], i) => tourPlate(p, I.tier(tier), color, top, `translate(${i % 2 ? 60 : -160}%,-50%) rotateY(${i % 2 ? -50 : 50}deg) scale(.8)`, `translate(calc(-50% + var(--px) * ${(i - 1) * 16 + 8}px),-50%) rotateY(calc(var(--px) * 12deg)) rotateZ(${(i - 1) * 2.5}deg) scale(.86)`, i) + `<span class="slide-tag" style="top:calc(${top}% + 11vw + 14px);--tier:${color};--i:${i}"><i></i>${price}</span>`).join("")}</div>`;
    } },
    { h: "Собери гараж", p: "Сохраняй лучшие номера, кидай их в чаты и поднимайся в топе игроков", build: stage => {
      const fan = [[ruPlate("В", "001", "О", "Р", "78"), -9, 34], [ruPlate("К", "100", "К", "К", "77"), 5, 50], [ruPlate("М", "777", "М", "М", "99"), -3, 66]];
      stage.innerHTML = `<div class="slide">${fan.map(([p, rot, top], i) => tourPlate(p, "НОМЕРА", "", top, "translate(-50%,260%) rotateX(-50deg)", `translate(calc(-50% + var(--px) * ${10 + i * 8}px),-50%) rotateZ(${rot}deg) rotateY(calc(var(--px) * 10deg)) scale(.84)`, i)).join("")}
        <img class="slide-art" src="static/img/3d/trophy.png" alt="" style="right:6%;top:9%;--from:translateY(-140px) rotate(30deg);--to:translate(calc(var(--px) * -22px),calc(var(--py) * -14px)) rotate(10deg);--i:1">
        <img class="slide-art" src="static/img/3d/bolt.png" alt="" style="left:7%;bottom:8%;--from:translateY(140px) rotate(-30deg);--to:translate(calc(var(--px) * 26px),calc(var(--py) * 16px)) rotate(-12deg);--i:2"></div>`;
    } },
  ];
  const tourPlate = (p, lip, color, top, from, to, i) => `<div class="pf fly" style="top:${top}%;--from:${from};--to:${to};--i:${i};${color ? `--tier:${color}` : ""}">${plateHTML(p)}<div class="pf-lip"><span>${esc(lip)}</span></div><div class="pf-glare"></div></div>`;

  function runTour(withLang) {
    const tour = $("#tour"), stage = $("#tour-stage"), text = $("#tour-text"), next = $("#tour-next"), dots = $("#tour-dots");
    let step = withLang ? -1 : 0;
    const total = SLIDES.length + (withLang ? 1 : 0);
    const show = () => {
      const pos = step + (withLang ? 1 : 0);
      dots.innerHTML = Array.from({ length: total }, (_, i) => `<i class="${i === pos ? "is-on" : ""}"></i>`).join("");
      text.classList.remove("is-in"); void text.offsetWidth; text.classList.add("is-in");
      if (step < 0) {
        stage.innerHTML = `<div class="tour-langs"><span class="logo-plate"><b>НОМЕРА</b><i>777</i></span>${langsHTML()}</div>`;
        $$(".lang", stage).forEach(b => b.addEventListener("click", () => { haptic.tap(); I.set(b.dataset.lang); $$(".lang", stage).forEach(x => x.classList.toggle("is-on", x === b)); paint(); }));
      } else SLIDES[step].build(stage);
      paint();
    };
    const paint = () => {
      text.innerHTML = step < 0 ? `<h1>${t("Выбери язык")}</h1><p>${t("Язык можно поменять позже в разделе «Страны»")}</p>` : `<h1>${t(SLIDES[step].h)}</h1><p>${t(SLIDES[step].p)}</p>`;
      next.textContent = t(step === SLIDES.length - 1 ? "Начать" : "Дальше");
    };
    next.onclick = () => {
      haptic.tap();
      if (step === SLIDES.length - 1) { try { localStorage.setItem("plates_tour", "1"); } catch (e) { /* хранилище недоступно */ } tour.hidden = true; stage.innerHTML = ""; applyLang(); return; }
      step += 1; show();
    };
    tour.hidden = false;
    show();
  }

  /* ------------------------------------------------------------ Старт */
  async function refresh() {
    const b = await api("bootstrap");
    Object.assign(state, { user: b.user, ai: !!b.ai, countries: b.countries, settings: b.settings, garage: b.garage, stats: b.stats, packs: b.energy_packs || [] });
    setEnergy(b.energy);
    if (b.last && !state.current) state.current = b.last;
    renderWorld();
    if (!state.rolling) showCurrent(false);
    renderExtras();
    if (state.tab === "garage") renderGarage();
  }

  btnSpin.addEventListener("click", spin);
  $("#btn-save").addEventListener("click", saveCurrent);
  $("#btn-share").addEventListener("click", shareCurrent);
  $("#btn-ai").addEventListener("click", aiCurrent);
  $("#energy").addEventListener("click", () => { haptic.tap(); openEnergy(false); });

  I.set(I.saved() || I.guess(tg && tg.initDataUnsafe && tg.initDataUnsafe.user && tg.initDataUnsafe.user.language_code));
  $("#boot-plate").innerHTML = framed(demoPlate(), "НОМЕРА");
  $("#ghosts").innerHTML = [[ruPlate("О", "000", "О", "О", "77"), 8, 14, 34, -8], [ruPlate("Х", "999", "Х", "Х", "99"), 62, 20, 30, 7], [ruPlate("В", "001", "О", "Р", "78"), 70, 70, 26, -5], [ruPlate("М", "555", "М", "М", "50"), 4, 74, 24, 6]]
    .map(([p, x, y, w, r]) => `<span class="pw" style="left:${x}%;top:${y}%;width:${w}%;rotate:${r}deg">${plateHTML(p)}</span>`).join("");
  mountIcons();
  showCurrent(false);

  const bootAt = performance.now();
  let seenTour = false;
  try { seenTour = !!localStorage.getItem("plates_tour"); } catch (e) { /* хранилище недоступно */ }
  refresh().catch(e => toast(t("Нет связи с сервером") + ": " + e.message)).finally(async () => {
    await sleep(Math.max(0, 1100 - (performance.now() - bootAt)));
    applyLang();
    $("#app").hidden = false;
    if (!seenTour) runTour(true);
    $("#boot").classList.add("is-done");
    if (tg && tg.initDataUnsafe && tg.initDataUnsafe.start_param === "feed") openTab("feed");
  });
})();
