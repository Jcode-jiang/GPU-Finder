/* GPU Finder Dashboard — 无依赖前端 */
(() => {
  "use strict";

  const $ = (sel, root = document) => root.querySelector(sel);
  const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));

  const state = {
    snapshot: null,
    loading: true,
    error: "",
    family: "all",
    onlyAvailable: false,
    hiddenPlatforms: new Set(),
    sort: "price",
    theme: localStorage.getItem("gf-theme") || "",
    config: null,
    rentEnabled: false,
    rent: { options: null, offer: null, quote: null, instance: null, timer: null, platform: "compshare" },
  };

  const PLATFORM_FALLBACK = {
    autodl: { accent: "#4F7CFF", initial: "A" },
    matpool: { accent: "#14B8A6", initial: "矩" },
    compshare: { accent: "#7C5CFF", initial: "优" },
    gpushare: { accent: "#F59E0B", initial: "恒" },
  };

  const FAMILY_LABEL = { rtx4090: "RTX 4090", rtx5090: "RTX 5090" };
  const SOURCE_LABEL = { api: "官网实时", scrape: "官网抓取" };

  // ------------------------------------------------------------------ 工具
  function el(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined && text !== null) node.textContent = String(text);
    return node;
  }

  function icon(path, viewBox = "0 0 24 24") {
    const NS = "http://www.w3.org/2000/svg";
    const svg = document.createElementNS(NS, "svg");
    svg.setAttribute("viewBox", viewBox);
    svg.setAttribute("fill", "none");
    const p = document.createElementNS(NS, "path");
    p.setAttribute("d", path);
    p.setAttribute("stroke", "currentColor");
    p.setAttribute("stroke-width", "1.8");
    p.setAttribute("stroke-linecap", "round");
    p.setAttribute("stroke-linejoin", "round");
    svg.appendChild(p);
    return svg;
  }

  function platformMeta(id, platforms) {
    const fromSnap = (platforms || []).find((p) => p.id === id);
    const fb = PLATFORM_FALLBACK[id] || { accent: "#64748b", initial: "?" };
    return {
      accent: (fromSnap && fromSnap.accent) || fb.accent,
      initial: fb.initial,
      name: (fromSnap && fromSnap.name) || id,
      homepage: (fromSnap && fromSnap.homepage) || "#",
    };
  }

  function relativeTime(ts) {
    if (!ts) return "";
    const sec = Math.max(0, Math.round(Date.now() / 1000 - ts));
    if (sec < 45) return "刚刚更新";
    if (sec < 3600) return `${Math.round(sec / 60)} 分钟前更新`;
    if (sec < 86400) return `${Math.round(sec / 3600)} 小时前更新`;
    return `${Math.round(sec / 86400)} 天前更新`;
  }

  function clockTime(iso) {
    if (!iso) return "";
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return "";
    return d.toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit", second: "2-digit" });
  }

  function noteFor(o) {
    if (o.specs && o.specs.config) return o.specs.config;
    if (o.specs && (o.specs.cpu_cores || o.specs.ram_gb || o.specs.disk_gb)) {
      return [o.specs.cpu_cores ? `${o.specs.cpu_cores}C` : null, o.specs.ram_gb ? `${o.specs.ram_gb}G 内存` : null, o.specs.disk_gb ? `${o.specs.disk_gb}G 硬盘` : null]
        .filter(Boolean)
        .join(" · ");
    }
    const note = o.notes || o.billing || "";
    return note.length > 46 ? note.slice(0, 45) + "…" : note;
  }

  function money(p) {
    if (typeof p !== "number" || !isFinite(p)) return null;
    return p >= 100 ? p.toFixed(0) : p >= 10 ? p.toFixed(1) : p.toFixed(2);
  }

  function toast(message) {
    const node = $("#toast");
    node.textContent = message;
    node.classList.add("show");
    clearTimeout(toast._t);
    toast._t = setTimeout(() => node.classList.remove("show"), 2200);
  }

  // ------------------------------------------------------------------ 主题
  function applyTheme() {
    const dark = state.theme
      ? state.theme === "dark"
      : window.matchMedia("(prefers-color-scheme: dark)").matches;
    document.documentElement.dataset.theme = dark ? "dark" : "light";
    const btn = $("#theme");
    btn.title = dark ? "切换浅色" : "切换深色";
  }

  // ------------------------------------------------------------------ 数据
  async function fetchSnapshot(force = false) {
    if (state.loading && !state.snapshot) renderSkeleton();
    try {
      const resp = await fetch(force ? "/api/snapshot?refresh=1" : "/api/snapshot", {
        headers: { Accept: "application/json" },
      });
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      const data = await resp.json();
      state.snapshot = data;
      state.error = "";
    } catch (err) {
      state.error = String(err && err.message ? err.message : err);
    } finally {
      state.loading = false;
      render();
    }
  }

  async function doRefresh() {
    const btn = $("#refresh");
    if (btn.classList.contains("busy")) return;
    btn.classList.add("busy");
    btn.disabled = true;
    try {
      const resp = await fetch("/api/refresh", { method: "POST", headers: { "Content-Type": "application/json" }, body: "{}" });
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      state.snapshot = await resp.json();
      state.error = "";
      toast("已刷新全部平台");
    } catch (err) {
      state.error = String(err);
      toast("刷新失败，稍后再试");
    } finally {
      btn.classList.remove("busy");
      btn.disabled = false;
      render();
    }
  }

  // ------------------------------------------------------------------ 过滤
  function visibleOffers() {
    const snap = state.snapshot;
    if (!snap) return [];
    let offers = (snap.offers || []).slice();
    if (state.family !== "all") offers = offers.filter((o) => o.family === state.family);
    if (state.onlyAvailable) offers = offers.filter((o) => o.available === true);
    if (state.hiddenPlatforms.size) offers = offers.filter((o) => !state.hiddenPlatforms.has(o.platform));
    const sorters = {
      price: (a, b) =>
        (a.family === "rtx4090" ? 0 : 1) - (b.family === "rtx4090" ? 0 : 1) ||
        (a.available === true ? 0 : 1) - (b.available === true ? 0 : 1) ||
        (a.price == null ? 1 : 0) - (b.price == null ? 1 : 0) ||
        (a.price ?? 1e9) - (b.price ?? 1e9),
      stock: (a, b) => (b.stock ?? -1) - (a.stock ?? -1) || (a.price ?? 1e9) - (b.price ?? 1e9),
      platform: (a, b) => String(a.platform_name).localeCompare(String(b.platform_name), "zh") || (a.price ?? 1e9) - (b.price ?? 1e9),
    };
    offers.sort(sorters[state.sort] || sorters.price);
    return offers;
  }

  function cheapestIds() {
    const out = new Set();
    const snap = state.snapshot;
    if (!snap) return out;
    for (const fam of ["rtx4090", "rtx5090"]) {
      const pool = (snap.offers || []).filter((o) => o.family === fam && o.available === true && o.price != null);
      if (!pool.length) continue;
      const cheapest = pool.reduce((a, b) => (a.price <= b.price ? a : b));
      out.add(cheapest.id);
    }
    return out;
  }

  // ------------------------------------------------------------------ 渲染
  function renderSkeleton() {
    const hero = $("#hero");
    hero.textContent = "";
    for (const fam of ["rtx4090", "rtx5090"]) {
      const card = el("div", "hero-card");
      card.dataset.gpu = fam;
      card.appendChild(el("div", "skeleton", ""));
      card.firstChild.style.cssText = "height:14px;width:38%;margin-bottom:16px";
      const p = el("div", "skeleton", "");
      p.style.cssText = "height:34px;width:58%;margin-bottom:14px";
      card.appendChild(p);
      const s = el("div", "skeleton", "");
      s.style.cssText = "height:12px;width:72%";
      card.appendChild(s);
      hero.appendChild(card);
    }
    const offers = $("#offers");
    offers.textContent = "";
    offers.appendChild(el("div", "empty-state", "正在连接本地服务…"));
  }

  function render() {
    if (!state.snapshot) {
      renderSkeleton();
      $("#updated-text").textContent = state.error ? "连接失败" : "正在加载…";
      $(".updated .dot").className = "dot " + (state.error ? "error" : "loading");
      return;
    }
    renderHeader();
    renderHero();
    renderChips();
    renderOffers();
    renderProviders();
  }

  function renderHeader() {
    const snap = state.snapshot;
    const dot = $(".updated .dot");
    const text = $("#updated-text");
    const age = Math.max(0, Date.now() / 1000 - (snap.generated_ts || 0));
    dot.className = "dot" + (state.error ? " error" : age > 3600 ? " stale" : "");
    const label = state.error ? "连接失败" : relativeTime(snap.generated_ts);
    text.textContent = label;
    $("#updated").title = `${snap.generated_at || ""} · ${snap.summary?.offers ?? 0} 条报价`;
    const version = $("#version");
    if (version) version.textContent = "v1.0.0";
  }

  function renderHero() {
    const hero = $("#hero");
    hero.textContent = "";
    const snap = state.snapshot;
    const platforms = snap.platforms || [];
    const all = snap.offers || [];

    for (const fam of ["rtx4090", "rtx5090"]) {
      const offers = all.filter((o) => o.family === fam);
      const available = offers.filter((o) => o.available === true);
      const priced = (available.length ? available : offers).filter((o) => o.price != null);
      const cheapest = priced.length ? priced.reduce((a, b) => (a.price <= b.price ? a : b)) : null;
      const meta = cheapest ? platformMeta(cheapest.platform, platforms) : null;
      const platformCount = new Set(offers.map((o) => o.platform)).size;

      const card = el("div", "hero-card");
      card.dataset.gpu = fam;

      const top = el("div", "hero-top");
      const badge = el("div", "gpu-badge");
      const dot = el("span", "chip-dot");
      badge.appendChild(dot);
      const name = el("span", null, FAMILY_LABEL[fam]);
      badge.appendChild(name);
      badge.appendChild(el("span", "vram", fam === "rtx4090" ? "24 GB" : "32 GB"));
      top.appendChild(badge);
      if (cheapest && cheapest.available) {
        const b = el("span", "badge ok");
        b.appendChild(el("span", "bdot"));
        b.appendChild(el("span", null, "最低有货价"));
        top.appendChild(b);
      } else if (cheapest) {
        top.appendChild(el("span", "badge unk", "暂无有货"));
      } else {
        top.appendChild(el("span", "badge unk", "暂无报价"));
      }
      card.appendChild(top);

      if (cheapest) {
        const price = el("div", "hero-price");
        price.appendChild(el("span", "cur", "¥"));
        price.appendChild(el("span", "num", money(cheapest.price) ?? "—"));
        price.appendChild(el("span", "unit", "/ 卡 · 小时"));
        card.appendChild(price);

        const sub = el("div", "hero-sub");
        const platformName = el("b", null, cheapest.platform_name);
        sub.append("来自 ", platformName);
        if (cheapest.region) sub.append(` · ${cheapest.region}`);
        card.appendChild(sub);
      } else {
        card.appendChild(el("div", "hero-empty", "当前筛选条件下暂无报价"));
      }

      const stats = el("div", "hero-stats");
      const s1 = el("span");
      s1.append("有货 ", el("b", null, String(available.length)), ` / ${offers.length} 条`);
      const s2 = el("span");
      s2.append("覆盖 ", el("b", null, String(platformCount)), " 个平台");
      stats.append(s1, s2);
      card.appendChild(stats);
      hero.appendChild(card);
    }
  }

  function renderChips() {
    const wrap = $("#platform-chips");
    wrap.textContent = "";
    const snap = state.snapshot;
    const platforms = snap.platforms || [];
    for (const p of platforms) {
      const meta = platformMeta(p.id, platforms);
      const offers = (snap.offers || []).filter((o) => o.platform === p.id);
      const chip = el("button", "chip");
      chip.type = "button";
      const avatar = el("span", "avatar", meta.initial);
      avatar.style.background = meta.accent;
      chip.appendChild(avatar);
      chip.appendChild(el("span", null, p.name));
      chip.appendChild(el("span", "count", String(offers.length)));
      if (state.hiddenPlatforms.has(p.id)) chip.classList.add("off");
      chip.setAttribute("aria-pressed", String(!state.hiddenPlatforms.has(p.id)));
      chip.addEventListener("click", () => {
        if (state.hiddenPlatforms.has(p.id)) state.hiddenPlatforms.delete(p.id);
        else state.hiddenPlatforms.add(p.id);
        render();
      });
      wrap.appendChild(chip);
    }
  }

  function renderOffers() {
    const wrap = $("#offers");
    wrap.textContent = "";
    const offers = visibleOffers();
    const cheapest = cheapestIds();

    if (!offers.length) {
      const empty = el("div", "empty-state");
      empty.appendChild(el("b", null, state.onlyAvailable ? "当前没有有货的资源" : "没有符合条件的报价"));
      empty.append(state.onlyAvailable ? "关掉「只看有货」，或稍后刷新看看。" : "试试切换显卡或平台筛选。");
      wrap.appendChild(empty);
      return;
    }

    const head = el("div", "offer-head");
    ["平台 / 地区", "显卡", "价格", "库存", ""].forEach((t) => head.appendChild(el("span", null, t)));
    wrap.appendChild(head);

    const platforms = state.snapshot.platforms || [];
    offers.forEach((o, idx) => {
      const meta = platformMeta(o.platform, platforms);
      const row = el("div", "offer");
      row.style.setProperty("--i", String(Math.min(idx, 12)));
      if (cheapest.has(o.id)) row.classList.add("cheapest");
      if (o.available === false) row.classList.add("soldout");

      // 平台
      const pcell = el("div", "platform-cell");
      const avatar = el("span", "p-avatar", meta.initial);
      avatar.style.background = `linear-gradient(145deg, ${meta.accent}, color-mix(in srgb, ${meta.accent} 70%, #000))`;
      pcell.appendChild(avatar);
      const pmeta = el("div", "meta");
      const nameRow = el("div", "name");
      nameRow.appendChild(document.createTextNode(o.platform_name));
      if (cheapest.has(o.id)) {
        const b = el("span", "badge ok");
        b.style.marginLeft = "6px";
        b.appendChild(el("span", null, "最低"));
        nameRow.appendChild(b);
      }
      pmeta.appendChild(nameRow);
      pmeta.appendChild(el("div", "region", o.region || "—"));
      pcell.appendChild(pmeta);
      row.appendChild(pcell);

      // 显卡
      const gcell = el("div", "gpu-cell");
      const gname = el("div", "gpu-name");
      gname.appendChild(el("span", null, o.gpu));
      if (o.vram_gb) gname.appendChild(el("span", "vram-tag", `${o.vram_gb}G`));
      gcell.appendChild(gname);
      const noteText = noteFor(o);
      if (noteText) gcell.appendChild(el("div", "gpu-note", noteText));
      row.appendChild(gcell);

      // 价格
      const price = el("div", "price-cell" + (o.price == null ? " unknown" : ""));
      if (o.price != null) {
        price.appendChild(el("span", "cur", "¥"));
        price.appendChild(el("span", "amount", money(o.price)));
        price.appendChild(el("span", "per", "/时"));
      } else {
        price.appendChild(el("span", "amount", "价格未知"));
      }
      row.appendChild(price);

      // 库存
      const stock = el("div", "stock-cell");
      const badge = el("span", "badge " + (o.available === true ? "ok" : o.available === false ? "no" : "unk"));
      badge.appendChild(el("span", "bdot"));
      badge.appendChild(el("span", null, o.available === true ? (o.stock != null ? `有货 ${o.stock}` : "有货") : o.available === false ? "无货" : "库存未知"));
      stock.appendChild(badge);
      const src = el("div", "src-line");
      src.appendChild(el("span", "badge live", SOURCE_LABEL[o.source] || o.source || ""));
      if (o.capacity) src.appendChild(el("span", null, `共 ${o.capacity} 卡`));
      stock.appendChild(src);
      row.appendChild(stock);

      // 操作
      const actions = el("div", "actions");
      if (o.rent && o.rent.platform) {
        const rentBtn = el("button", "link-btn rent-btn", "租");
        rentBtn.type = "button";
        rentBtn.disabled = o.available !== true;
        rentBtn.title = o.available === true ? "一键租用这台实例" : "当前无库存";
        rentBtn.addEventListener("click", () => openRent(o));
        actions.appendChild(rentBtn);
      }
      const link = el("a", "link-btn");
      link.href = o.url || "#";
      link.target = "_blank";
      link.rel = "noopener noreferrer";
      link.appendChild(document.createTextNode("打开"));
      link.appendChild(icon("M8 16 16 8M9 8h7v7"));
      actions.appendChild(link);
      row.appendChild(actions);

      wrap.appendChild(row);
    });

    const footer = el("div", "offer-foot-note");
    footer.style.cssText = "padding:11px 20px;font-size:10.5px;color:var(--muted);border-top:1px solid var(--border);display:flex;gap:10px;flex-wrap:wrap";
    footer.append(`共 ${offers.length} 条 · 价格单位 元/卡/小时 · 库存为官方接口瞬时快照，热门卡可能被抢占`);
    wrap.appendChild(footer);
  }

  function renderProviders() {
    const wrap = $("#providers");
    wrap.textContent = "";
    const snap = state.snapshot;
    const platforms = snap.platforms || [];
    for (const p of platforms) {
      const meta = platformMeta(p.id, platforms);
      const card = el("div", "provider-card");
      const avatar = el("span", "p-avatar", meta.initial);
      avatar.style.background = meta.accent;
      card.appendChild(avatar);

      const body = el("div", "pc-body");
      const top = el("div", "pc-top");
      top.appendChild(el("span", "pc-name", p.name));
      const mode = p.mode === "live" ? "官网实时" : p.mode === "auth" ? "需要登录" : "抓取失败";
      const modeEl = el("span", "pc-mode", `· ${mode} · ${p.latency_ms ?? 0}ms`);
      top.appendChild(modeEl);
      body.appendChild(top);
      const msg = p.message || (p.mode === "live" ? `${p.offer_count} 条报价已更新` : "");
      body.appendChild(el("div", "pc-msg", msg || "数据正常"));
      card.appendChild(body);
      wrap.appendChild(card);
    }
  }

  // ------------------------------------------------------------------ 设置
  async function openSettings() {
    const drawer = $("#drawer");
    drawer.classList.add("open");
    drawer.setAttribute("aria-hidden", "false");
    try {
      const resp = await fetch("/api/config");
      const cfg = await resp.json();
      state.config = cfg;
      $("#token-autodl").placeholder = cfg.credentials?.autodl_token?.configured ? "已配置（留空不修改）" : "未配置";
      $("#token-gpushare").placeholder = cfg.credentials?.gpushare_token?.configured ? "已配置（留空不修改）" : "未配置";
      $("#token-matpool").placeholder = cfg.credentials?.matpool_token?.configured ? "已配置（留空不修改）" : "未配置";
      $("#matpool-user-id").placeholder = cfg.credentials?.matpool_user_id?.configured ? "已配置（留空不修改）" : "未配置";
      $("#compshare-public").placeholder = cfg.credentials?.compshare_public_key?.configured ? "已配置（留空不修改）" : "未配置";
      $("#compshare-secret").placeholder = cfg.credentials?.compshare_private_key?.configured ? "已配置（留空不修改）" : "未配置";
      $("#refresh-interval").value = String(cfg.refresh_interval ?? 300);
      await loadRentOptions();
    } catch (err) {
      toast("读取配置失败");
    }
  }

  function closeSettings() {
    const drawer = $("#drawer");
    drawer.classList.remove("open");
    drawer.setAttribute("aria-hidden", "true");
  }

  async function saveSettings() {
    const payload = {
      refresh_interval: Number($("#refresh-interval").value),
      credentials: {},
      rent: {
        enabled: $("#rent-enabled").checked,
        image_id: $("#rent-image").value,
        disk_gb: Number($("#rent-disk").value) || 100,
        auto_stop_minutes: Number($("#rent-autostop").value) || 0,
        max_hourly_price: Number($("#rent-maxprice").value) || 5,
      },
    };
    const a = $("#token-autodl").value.trim();
    const g = $("#token-gpushare").value.trim();
    const mp = $("#token-matpool").value.trim();
    const mu = $("#matpool-user-id").value.trim();
    const cp = $("#compshare-public").value.trim();
    const cs = $("#compshare-secret").value.trim();
    if (a) payload.credentials.autodl_token = a;
    if (g) payload.credentials.gpushare_token = g;
    if (mp) payload.credentials.matpool_token = mp;
    if (mu) payload.credentials.matpool_user_id = mu;
    if (cp) payload.credentials.compshare_public_key = cp;
    if (cs) payload.credentials.compshare_private_key = cs;
    const btn = $("#save-settings");
    btn.disabled = true;
    try {
      const resp = await fetch("/api/config", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      $("#save-hint").textContent = "已保存";
      $("#token-autodl").value = "";
      $("#token-gpushare").value = "";
      $("#compshare-public").value = "";
      $("#compshare-secret").value = "";
      toast("设置已保存");
      setTimeout(() => ($("#save-hint").textContent = ""), 2500);
      state.rentEnabled = $("#rent-enabled").checked;
      closeSettings();
      await loadRentOptions();
      if (a || g || cp || cs) doRefresh();
    } catch (err) {
      toast("保存失败：" + err);
    } finally {
      btn.disabled = false;
    }
  }


  // ------------------------------------------------------------------ 一键租卡
  async function loadRentOptions() {
    try {
      const resp = await fetch("/api/rent/options");
      const data = await resp.json();
      if (!resp.ok) throw new Error(data.error || `HTTP ${resp.status}`);
      state.rent.options = data;
      state.rentEnabled = !!(data.settings && data.settings.enabled);
      const sel = $("#rent-image");
      sel.textContent = "";
      const auto = el("option", null, "自动（优先 PyTorch，其次 Ubuntu 带驱动）");
      auto.value = "";
      sel.appendChild(auto);
      (data.images || []).forEach((img) => {
        const opt = el("option", null, `${img.name}${img.type === "System" ? " · 系统" : ""}`);
        opt.value = img.id;
        sel.appendChild(opt);
      });
      sel.value = (data.settings && data.settings.image_id) || "";
      $("#rent-enabled").checked = !!(data.settings && data.settings.enabled);
      $("#rent-disk").value = (data.settings && data.settings.disk_gb) || 100;
      $("#rent-autostop").value = (data.settings && data.settings.auto_stop_minutes) || 0;
      $("#rent-maxprice").value = (data.settings && data.settings.max_hourly_price) || 5;
      $("#rent-balance").textContent = `账户余额：¥${Number(data.balance || 0).toFixed(2)}`;
      return data;
    } catch (err) {
      $("#rent-balance").textContent = `读取租卡选项失败：${err.message || err}`;
      return null;
    }
  }

  function openRentModal() {
    const modal = $("#rent-modal");
    modal.classList.add("open");
    modal.setAttribute("aria-hidden", "false");
    $("#rent-confirm").checked = false;
    $("#rent-go").disabled = true;
    $("#rent-go").textContent = "确认租用";
    $("#rent-error").hidden = true;
    $("#rent-ssh").hidden = true;
    $("#rent-ssh").textContent = "";
    $("#rent-confirm-wrap").hidden = false;
  }

  function closeRentModal() {
    const modal = $("#rent-modal");
    modal.classList.remove("open");
    modal.setAttribute("aria-hidden", "true");
  }

  async function openRent(offer) {
    if (!state.rentEnabled) {
      toast("请先在设置里启用一键租卡");
      openSettings();
      return;
    }
    if (offer.available !== true) {
      toast("这台机器当前无货");
      return;
    }
    const rentSpec = offer.rent;
    const platform = rentSpec.platform || "compshare";
    state.rent.platform = platform;
    const who = platform === "autodl" ? "AutoDL"
      : platform === "gpushare" ? "恒源云"
      : platform === "matpool" ? "矩池云" : "优云智算";
    const confirmWrap = $("#rent-confirm-wrap");
    if (confirmWrap) confirmWrap.querySelector("span").textContent = `我确认创建按量计费实例，费用由我的${who}账户承担`;
    state.rent.offer = offer;
    state.rent.quote = null;
    state.rent.instance = null;
    openRentModal();
    const summary = $("#rent-summary");
    summary.textContent = "";
    summary.appendChild(el("div", "rent-line", "正在检查官方库存与价格…"));
    try {
      let endpoint;
      let payload;
      if (platform === "autodl" || platform === "gpushare" || platform === "matpool") {
        endpoint = platform === "autodl" ? "/api/rent/autodl/quote"
          : platform === "gpushare" ? "/api/rent/gpushare/quote" : "/api/rent/matpool/quote";
        payload = {
          gpu_type: rentSpec.gpu_type,
          region: rentSpec.region,
          price: rentSpec.price,
        };
      } else {
        const specs = offer.specs || {};
        if (!specs.gpu_type || !specs.region_id || !specs.zone_id) {
          throw new Error("缺少租卡参数，请刷新行情后重试");
        }
        endpoint = "/api/rent/quote";
        payload = {
          gpu_type: specs.gpu_type,
          region: specs.region_id,
          zone: specs.zone_id,
          cpu: Number(specs.cpu) || 0,
          mem_gb: Number(specs.mem_gb) || 0,
        };
      }
      const resp = await fetch(endpoint, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      const data = await resp.json();
      if (!resp.ok) throw new Error(data.error || "报价失败");
      state.rent.quote = data.quote;
      renderRentQuote(data.quote);
    } catch (err) {
      showRentError(String(err.message || err));
    }
  }

  function renderRentQuote(q) {
    const summary = $("#rent-summary");
    summary.textContent = "";
    const line = (k, v, cls) => {
      const row = el("div", "rent-line" + (cls ? " " + cls : ""));
      row.appendChild(el("span", "k", k));
      row.appendChild(el("span", "v", v));
      summary.appendChild(row);
    };
    line("平台", q.platform === "autodl" ? "AutoDL · 官方市场接口"
      : q.platform === "gpushare" ? "恒源云 · 官方市场接口"
      : q.platform === "matpool" ? "矩池云 · 官方市场接口" : "优云智算 · 官方 API");
    line("区域", q.zone_name || q.zone);
    line("显卡", `${state.rent.offer.gpu}，1 卡`);
    line("配置", `${q.cpu}C · ${q.mem_gb}G 内存`);
    line("镜像", q.image_name || q.image_id);
    line("系统盘", q.disk_gb ? `${q.disk_gb}GB SSD` : "平台默认");
    line("自动关机", q.auto_stop_minutes > 0 ? `${q.auto_stop_minutes} 分钟后` : "不自动关机");
    const priceRow = el("div", "rent-line big");
    priceRow.appendChild(el("span", "k", "按量价格"));
    const v = el("span", "v", `¥${(q.price ?? 0).toFixed(2)}`);
    v.appendChild(el("small", null, "/小时"));
    priceRow.appendChild(v);
    summary.appendChild(priceRow);
    line("库存", q.capacity === false ? "当前不足，无法创建" : q.capacity === true ? "充足（官方容量检查）" : "未知");
    const max = q.max_hourly_price ?? 5;
    if (q.price != null && q.price > max) {
      showRentError(`当前价格 ¥${q.price.toFixed(2)}/时 超过设置上限 ¥${max.toFixed(2)}/时`);
      return;
    }
    if (q.capacity === false) {
      showRentError("当前规格库存不足，请换区域或稍后重试");
      return;
    }
    $("#rent-go").disabled = true;
  }

  function showRentError(message) {
    const node = $("#rent-error");
    node.textContent = message;
    node.hidden = false;
  }

  async function confirmRent() {
    const q = state.rent.quote;
    if (!q) return;
    if (!$("#rent-confirm").checked) return;
    $("#rent-go").disabled = true;
    $("#rent-confirm-wrap").hidden = true;
    $("#rent-go").textContent = "创建中…";
    const summary = $("#rent-summary");
    const status = el("div", "rent-line");
    status.id = "rent-progress";
    status.appendChild(el("span", "k", "状态"));
    const v = el("span", "v");
    v.innerHTML = '<span class="spinner-sm"></span>正在创建实例…';
    status.appendChild(v);
    summary.appendChild(status);
    try {
      const platform = state.rent.platform || "compshare";
      const endpoint = platform === "autodl" ? "/api/rent/autodl/create"
        : platform === "gpushare" ? "/api/rent/gpushare/create"
        : platform === "matpool" ? "/api/rent/matpool/create" : "/api/rent/create";
      const payload = (platform === "autodl" || platform === "gpushare" || platform === "matpool")
        ? {
            machine_id: q.machine_id, image_id: q.image_id, name: "", confirm: "RENT",
            gpu_type: q.gpu_type, region: q.region, price: q.price,
          }
        : {
            gpu_type: q.gpu_type, region: q.region, zone: q.zone,
            cpu: q.cpu, mem_gb: q.mem_gb, image_id: q.image_id, confirm: "RENT",
          };
      const resp = await fetch(endpoint, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      const data = await resp.json();
      if (!resp.ok) throw new Error(data.error || "创建失败");
      state.rent.instance = data.instance;
      if (data.instance.warning) toast(data.instance.warning);
      else toast("实例已创建，正在等待分配…");
      renderRentInstance(data.instance);
      startRentPolling(data.instance.uhost_id);
      loadInstances();
    } catch (err) {
      $("#rent-confirm-wrap").hidden = false;
      $("#rent-go").disabled = false;
      $("#rent-go").textContent = "确认租用";
      showRentError(String(err.message || err));
      const p = $("#rent-progress");
      if (p) p.remove();
    }
  }

  function startRentPolling(id) {
    clearInterval(state.rent.timer);
    state.rent.timer = setInterval(async () => {
      try {
        const platform = state.rent.platform || "compshare";
        const url = platform === "autodl" ? "/api/rent/autodl/instances"
          : platform === "gpushare" ? "/api/rent/gpushare/instances"
          : platform === "matpool" ? "/api/rent/matpool/instances" : "/api/rent/instances";
        const resp = await fetch(url);
        const data = await resp.json();
        const inst = (data.instances || []).find((i) => i.uhost_id === id);
        if (!inst) return;
        state.rent.instance = inst;
        renderRentInstance(inst);
        loadInstances();
        if (isRunning(inst) || inst.released) {
          clearInterval(state.rent.timer);
        }
      } catch (err) {
        /* 下次再试 */
      }
    }, 5000);
  }

  function renderRentInstance(inst) {
    const summary = $("#rent-summary");
    if (!summary.textContent && !summary.children.length) return;
    const progress = $("#rent-progress");
    if (progress) progress.remove();
    let stateLine = summary.querySelector("[data-state-line]");
    if (!stateLine) {
      stateLine = el("div", "rent-line");
      stateLine.dataset.stateLine = "1";
      stateLine.appendChild(el("span", "k", "实例状态"));
      const v = el("span", "v", "");
      v.dataset.stateValue = "1";
      stateLine.appendChild(v);
      summary.appendChild(stateLine);
    }
    const value = stateLine.querySelector("[data-state-value]");
    value.textContent = `${stateLabel(inst.state)}${inst.auto_stop_at ? " · 定时关机已设置" : ""}`;
    value.className = "v" + (isRunning(inst) ? " rent-ok" : "");
    if (isRunning(inst) && inst.ssh && inst.ssh.command) {
      $("#rent-ssh").hidden = false;
      renderSshBox($("#rent-ssh"), inst);
      $("#rent-confirm-wrap").hidden = true;
      $("#rent-go").textContent = "完成";
      $("#rent-go").disabled = false;
    }
    if (inst.error) showRentError(inst.error);
  }

  function renderSshBox(box, inst) {
    box.textContent = "";
    const rows = [
      ["SSH", inst.ssh.command || `ssh root@${inst.ip}`],
      ["IP", inst.ip || "—"],
      ["用户", inst.ssh.user || "root"],
      ["密码", inst.ssh.password || "等待平台分配…"],
    ];
    rows.forEach(([k, v]) => {
      const row = el("div", "ssh-row");
      row.appendChild(el("span", "k", k));
      const val = el("span", "v", v);
      val.title = v;
      row.appendChild(val);
      const btn = el("button", "copy-btn", "复制");
      btn.type = "button";
      btn.addEventListener("click", () => copyText(v, k));
      row.appendChild(btn);
      box.appendChild(row);
    });
    const actions = el("div", "instance-actions");
    const release = el("button", "link-btn", "释放实例");
    release.type = "button";
    release.addEventListener("click", () => releaseInstance(inst.uhost_id));
    actions.appendChild(release);
    box.appendChild(actions);
  }

  async function copyText(text, label) {
    try {
      await navigator.clipboard.writeText(text);
      toast(`${label} 已复制`);
    } catch (err) {
      toast("复制失败，请手动选择");
    }
  }

  async function releaseInstance(id) {
    if (!window.confirm("确认释放实例？系统盘数据会被清除，费用停止累计。")) return;
    toast("正在关机并释放…");
    try {
      const platform = (state.rent.instance && state.rent.instance.platform) || state.rent.platform || "compshare";
      const endpoint = platform === "autodl" ? "/api/rent/autodl/terminate"
        : platform === "gpushare" ? "/api/rent/gpushare/terminate"
        : platform === "matpool" ? "/api/rent/matpool/terminate" : "/api/rent/terminate";
      const resp = await fetch(endpoint, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ uhost_id: id }),
      });
      const data = await resp.json();
      if (!resp.ok) throw new Error(data.error || "释放失败");
      toast("实例已释放");
      if (state.rent.instance && state.rent.instance.uhost_id === id) {
        state.rent.instance = data.instance;
        closeRentModal();
      }
      loadInstances();
    } catch (err) {
      toast(String(err.message || err));
    }
  }

  async function loadInstances() {
    try {
      const [c, a, g, m] = await Promise.all([
        fetch("/api/rent/instances").then((r) => (r.ok ? r.json() : { instances: [] })).catch(() => ({ instances: [] })),
        fetch("/api/rent/autodl/instances").then((r) => (r.ok ? r.json() : { instances: [] })).catch(() => ({ instances: [] })),
        fetch("/api/rent/gpushare/instances").then((r) => (r.ok ? r.json() : { instances: [] })).catch(() => ({ instances: [] })),
        fetch("/api/rent/matpool/instances").then((r) => (r.ok ? r.json() : { instances: [] })).catch(() => ({ instances: [] })),
      ]);
      renderInstances([...(c.instances || []), ...(a.instances || []), ...(g.instances || []), ...(m.instances || [])]);
    } catch (err) {
      /* 忽略 */
    }
  }

  function renderInstances(list) {
    const wrap = $("#instances");
    const active = list.filter((i) => !i.released);
    if (!active.length) {
      wrap.hidden = true;
      wrap.textContent = "";
      return;
    }
    wrap.hidden = false;
    wrap.textContent = "";
    active.forEach((inst) => {
      const card = el("div", "instance-card");
      const top = el("div", "instance-top");
      top.appendChild(el("span", "instance-name", inst.name || inst.uhost_id));
      const stateBadge = el("span", "badge " + (isRunning(inst) ? "ok" : "unk"), stateLabel(inst.state));
      top.appendChild(stateBadge);
      top.appendChild(el("span", "instance-meta", `${inst.gpu_type} · ${inst.zone_name || inst.zone} · ¥${(inst.price ?? 0).toFixed(2)}/时`));
      const acts = el("div", "instance-actions");
      const release = el("button", "link-btn", "释放");
      release.type = "button";
      release.addEventListener("click", () => releaseInstance(inst.uhost_id));
      acts.appendChild(release);
      top.appendChild(acts);
      card.appendChild(top);
      if (isRunning(inst) && inst.ssh && inst.ssh.command) {
        const box = el("div", "ssh-box");
        renderSshBox(box, inst);
        card.appendChild(box);
      } else {
        card.appendChild(el("div", "instance-meta", "实例初始化中，稍后自动显示 SSH 信息…"));
      }
      wrap.appendChild(card);
    });
  }

  // ------------------------------------------------------------------ 事件
  function bind() {
    $("#refresh").addEventListener("click", doRefresh);
    $("#theme").addEventListener("click", () => {
      const dark = document.documentElement.dataset.theme === "dark";
      state.theme = dark ? "light" : "dark";
      localStorage.setItem("gf-theme", state.theme);
      applyTheme();
    });
    $("#settings").addEventListener("click", openSettings);
    $("#drawer-close").addEventListener("click", closeSettings);
    $("#drawer").addEventListener("click", (e) => {
      if (e.target === $("#drawer")) closeSettings();
    });
    $("#save-settings").addEventListener("click", saveSettings);
    $("#rent-close").addEventListener("click", closeRentModal);
    $("#rent-cancel").addEventListener("click", closeRentModal);
    $("#rent-modal").addEventListener("click", (e) => {
      if (e.target === $("#rent-modal")) closeRentModal();
    });
    $("#rent-confirm").addEventListener("change", (e) => {
      $("#rent-go").disabled = !e.target.checked || !state.rent.quote || state.rent.quote.capacity === false;
    });
    $("#rent-go").addEventListener("click", () => {
      if (state.rent.instance && !state.rent.instance.released) closeRentModal();
      else confirmRent();
    });

    $$("#family-seg .seg").forEach((btn) => {
      btn.addEventListener("click", () => {
        state.family = btn.dataset.family;
        $$("#family-seg .seg").forEach((b) => b.classList.toggle("active", b === btn));
        render();
      });
    });
    $("#only-available").addEventListener("change", (e) => {
      state.onlyAvailable = e.target.checked;
      render();
    });
    $("#sort").addEventListener("change", (e) => {
      state.sort = e.target.value;
      render();
    });

    document.addEventListener("keydown", (e) => {
      if (e.metaKey || e.ctrlKey || e.altKey) return;
      const tag = (e.target.tagName || "").toLowerCase();
      if (tag === "input" || tag === "select" || tag === "textarea") {
        if (e.key === "Escape") closeSettings();
        return;
      }
      if (e.key === "r" || e.key === "R") doRefresh();
      if (e.key === "Escape") closeSettings();
      if (e.key === "1") $('[data-family="rtx4090"]').click();
      if (e.key === "2") $('[data-family="rtx5090"]').click();
      if (e.key === "0") $('[data-family="all"]').click();
    });

    window.matchMedia("(prefers-color-scheme: dark)").addEventListener("change", () => {
      if (!state.theme) applyTheme();
    });

    setInterval(() => {
      if (document.visibilityState === "visible") fetchSnapshot(false);
    }, 120000);

    setInterval(() => {
      if (document.visibilityState === "visible") loadInstances();
    }, 15000);
  }

  // ------------------------------------------------------------------ 启动
  applyTheme();
  bind();
  fetchSnapshot(false);
  loadInstances();
  fetch("/api/config")
    .then((r) => (r.ok ? r.json() : null))
    .then((cfg) => {
      if (cfg && cfg.rent) state.rentEnabled = !!cfg.rent.enabled;
    })
    .catch(() => {});
  if (location.hash === "#settings") {
    setTimeout(openSettings, 400);
  }
})();
