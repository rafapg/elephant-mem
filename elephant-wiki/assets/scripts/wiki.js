(function(){
  const C = window.__CORE__ || {meta:{counts:{}},entities:[],index:[]};
  const app = document.getElementById("app");
  const pane = document.getElementById("pane");
  const nav = document.getElementById("nav");
  const lgEl = document.getElementById("lg");
  const menEl = document.getElementById("mentions");
  const popEl = document.getElementById("pop");
  const ovHost = document.getElementById("ovhost");
  const q = document.getElementById("q");

  // ── lookup maps ──
  const entById = new Map(C.entities.map(e=>[e.id,e]));
  const idxById = new Map(C.index.map(r=>[r.id,r]));
  const KIND_ORDER = ["person","team","org","project","tool","concept","event","place"];

  // ── lazy shard cache ──
  const shards = {f:{},s:{}};
  const loaded = new Set();
  window.__SHARD__ = (t,key,obj)=>{ Object.assign(shards[t][key]||(shards[t][key]={}), obj); };
  function loadShard(t,sh){
    return new Promise(res=>{
      const key = t+":"+sh;
      if(loaded.has(key)) return res();
      const s=document.createElement("script");
      s.src=`data/${t==="f"?"facts":"sources"}-${sh}.js`;
      s.onload=()=>{loaded.add(key);res()};
      s.onerror=()=>{loaded.add(key);res()};
      document.head.appendChild(s);
    });
  }
  const routeOf = id => "#"+id.replace(/\.md$/,"");
  const esc = s => (s||"").replace(/[&<>"]/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));
  // A malformed percent-escape makes decodeURIComponent throw a URIError, and
  // two of the three call sites are inside the router — so a hash like
  // "#/search/%" typed or pasted into the address bar killed navigation and
  // left the page stuck until a reload. Falling back to the raw string means
  // the route simply fails to match and you land on the home view.
  const dec = s => { try { return decodeURIComponent(s); } catch(e) { return s; } };
  const titleOfEnt = id => (entById.get(id)||{}).title || id.split("/").pop().replace(/\.md$/,"");
  const cap1 = s => (s||"").charAt(0).toUpperCase()+(s||"").slice(1);

  // ── theme ──
  // The value is resolved before first paint by an inline script in <head>; this
  // only flips it, persists the choice, and tells the canvas to re-read its
  // colours, which it cannot get from CSS on its own.
  const themeBtn = document.getElementById("theme");
  // Inline SVG, not ☀/☾: those two code points fall back to whatever glyph the
  // platform has, and on this machine the moon rendered as a thin bracket.
  const SUN = '<svg viewBox="0 0 16 16" width="14" height="14" fill="none" stroke="currentColor"'
    + ' stroke-width="1.5" stroke-linecap="round"><circle cx="8" cy="8" r="3.1"/>'
    + '<path d="M8 1.4v1.5M8 13.1v1.5M1.4 8h1.5M13.1 8h1.5M3.4 3.4l1 1M11.6 11.6l1 1'
    + 'M12.6 3.4l-1 1M4.4 11.6l-1 1"/></svg>';
  const MOON = '<svg viewBox="0 0 16 16" width="14" height="14" fill="none" stroke="currentColor"'
    + ' stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">'
    + '<path d="M13.4 10.1A5.9 5.9 0 016.1 2.7a5.7 5.7 0 107.3 7.4z"/></svg>';
  const paintToggle = () =>
    themeBtn.innerHTML = document.documentElement.getAttribute("data-theme")==="dark" ? SUN : MOON;
  themeBtn.addEventListener("click", ev=>{
    ev.stopPropagation();
    const next = document.documentElement.getAttribute("data-theme")==="dark" ? "light" : "dark";
    document.documentElement.setAttribute("data-theme", next);
    try{ localStorage.setItem("elephant-theme", next); }catch(e){}
    paintToggle();
    window.dispatchEvent(new Event("elephant-theme"));
  });
  paintToggle();
  document.getElementById("brand").addEventListener("click",()=>location.hash="#/");

  // ── the explorer, built once and kept in sync by the router ──
  const groups={}; C.entities.forEach(e=>(groups[e.kind]=groups[e.kind]||[]).push(e));
  const kinds=Object.keys(groups).sort((a,b)=>{
    const ia=KIND_ORDER.indexOf(a),ib=KIND_ORDER.indexOf(b);
    return (ia<0?99:ia)-(ib<0?99:ib)||a.localeCompare(b);});
  kinds.forEach(k=>groups[k].sort((a,b)=>a.title.localeCompare(b.title)));

  function buildNav(){
    let h=`<h4>Entities <span class="n"></span></h4>`;
    kinds.forEach(k=>{
      // wrapped, so the group row can stick to the top of the rail while its own
      // entities scroll under it — with 183 orgs open the label is otherwise gone
      h+=`<div class="grp"><div class="row" data-kind="${esc(k)}"><span class="tw">▶</span>`
       + `<span>${esc(cap1(k))}</span><span class="n">${groups[k].length}</span></div>`
       + `<div class="sub" data-sub="${esc(k)}" hidden></div></div>`;
    });
    h+=`<h4>Browse</h4>
      <div class="row" data-go="#/facts"><span class="tw"></span><span>Facts</span><span class="n">${C.meta.counts.facts||0}</span></div>
      <div class="row" data-go="#/sources"><span class="tw"></span><span>Sources</span><span class="n">${C.meta.counts.sources||0}</span></div>`;
    nav.innerHTML=h;
    nav.querySelector("h4 .n").textContent = C.meta.counts.entities||C.entities.length;
  }
  // 541 rows across nine groups: filled on first expand rather than at boot, so
  // opening the page costs one group, not all of them.
  function fillGroup(k){
    const box=nav.querySelector(`.sub[data-sub="${k}"]`);
    if(!box || box.dataset.done) return box;
    box.innerHTML = groups[k].map(e=>
      `<div class="row" data-go="${routeOf(e.id)}" data-id="${esc(e.id)}" title="${esc(e.title)}">`
      + `<span>${esc(e.title)}</span></div>`).join("");
    box.dataset.done="1";
    return box;
  }
  function expand(k, open){
    const row=nav.querySelector(`.row[data-kind="${k}"]`), box=fillGroup(k);
    if(!row||!box) return;
    const want = open===undefined ? box.hidden : open;
    box.hidden = !want; row.classList.toggle("open", want);
  }
  nav.addEventListener("click", ev=>{
    const row = ev.target.closest(".row");
    if(!row) return;
    if(row.dataset.kind){
      // chevron toggles the group, the rest of the row opens the kind's own page —
      // the split Obsidian's file tree uses for a folder that is also a place
      if(ev.target.closest(".tw")) expand(row.dataset.kind);
      else location.hash = "#/kind/"+row.dataset.kind;
      return;
    }
    if(row.dataset.go) location.hash = row.dataset.go;
  });
  function markNav(hash, entId){
    nav.querySelectorAll(".row.on").forEach(r=>r.classList.remove("on"));
    let hit=null;
    if(entId){
      const e=entById.get(entId);
      if(e){ expand(e.kind, true); hit=nav.querySelector(`.row[data-id="${CSS.escape(entId)}"]`); }
    }
    if(!hit) hit=nav.querySelector(`.row[data-go="${CSS.escape(hash)}"]`);
    if(!hit && hash.startsWith("#/kind/"))
      hit=nav.querySelector(`.row[data-kind="${CSS.escape(hash.slice(7))}"]`);
    if(!hit) return;
    hit.classList.add("on");
    const r=hit.getBoundingClientRect(), pr=nav.getBoundingClientRect();
    if(r.top<pr.top+28 || r.bottom>pr.bottom-8) hit.scrollIntoView({block:"center"});
  }

  // ── pieces ──
  function chips(tags, kind){
    let h = kind?`<span class="chip k">${esc(kind)}</span>`:"";
    (tags||[]).slice(0,6).forEach(t=>
      h+=`<a class="chip" href="#/search/${encodeURIComponent(t)}">${esc(t)}</a>`);
    return h;
  }
  function badges(r){
    let h="";
    if(r.conf) h+=`<span class="badge b-${r.conf}">${r.conf}</span>`;
    if(r.status && r.status!=="active") h+=`<span class="badge b-${r.status}">${r.status}</span>`;
    return h;
  }
  function factCard(r){
    const ents = (r.ents||[]).slice(0,5).map(e=>
      `<a href="${routeOf(e)}">${esc(titleOfEnt(e))}</a>`).join(", ");
    return `<div class="item" data-go="${routeOf(r.id)}">
      <a class="t" href="${routeOf(r.id)}">${esc(r.desc)}</a>
      <div class="meta">${badges(r)}${r.date?`<span class="dt">${esc(r.date)}</span>`:""}
      ${ents?`<span>${ents}</span>`:""}${chips(r.tags)}</div></div>`;
  }
  function srcRow(r){
    return `<div class="item" data-go="${routeOf(r.id)}">
      <a class="t" href="${routeOf(r.id)}">${esc(r.desc)}</a>
      <div class="meta">${r.channel?`<span class="chip">${esc(r.channel)}</span>`:""}
      ${r.kind?`<span>${esc(r.kind)}</span>`:""}${r.date?`<span class="dt">${esc(r.date)}</span>`:""}
      ${chips(r.tags)}</div></div>`;
  }
  function entRow(e){
    // Entity rows carry a description, not apparatus, so they opt out of the
    // apparatus grid and the ledger spine. `.item.flat` restores display:block.
    return `<div class="item flat" data-go="${routeOf(e.id)}">
      <a class="t" href="${routeOf(e.id)}">${esc(e.title)}</a> <span class="chip k">${esc(e.kind)}</span>
      ${e.desc?`<div class="meta">${esc(e.desc)}</div>`:""}</div>`;
  }
  const h1of = t => `<h1 class="${(t||"").length>52?"long":""}">${esc(t)}</h1>`;
  function crumb(parts){
    return `<div class="crumb">` + parts.map((p,i)=>
      (i?`<span>/</span>`:"") + (p.go?`<a href="${p.go}">${esc(p.label)}</a>`:`<span>${esc(p.label)}</span>`)
    ).join("") + `</div>`;
  }

  // ── the right rail ──
  const appEl = document.querySelector(".app");
  const showRail = on => appEl.classList.toggle("norail", !on);
  function clearRail(){
    if(window.localGraph && window.localGraph.closeExpanded) window.localGraph.closeExpanded();
    lgEl.innerHTML=""; menEl.innerHTML=""; showRail(false);
  }
  // Order matters twice over. The rail has to be visible before the canvas is
  // sized, or clientWidth reads 0 out of a display:none column. And mentions has
  // to be filled *before* the graph: under 1180px the two blocks share a flex
  // line, so measuring the canvas while its sibling is still empty handed it the
  // whole band, and the star stayed seeded for a box that no longer existed.
  function fillRail(id, kicker){
    showRail(true);
    mentions(id, kicker);
    if(window.localGraph) window.localGraph(id, lgEl, {routeOf:routeOf, host:ovHost, expandable:true});
    if(!lgEl.children.length && !menEl.children.length) showRail(false);
  }
  // The textual half of the graph: who this page shares facts with, in order.
  // Same model the canvas draws, so the two can never disagree.
  function mentions(id, kicker){
    if(!window.localGraph || !window.localGraph.model) return;
    const g = window.localGraph.model(id);
    if(!g) return;
    const rows = g.nodes.slice(0,10).map(n=>
      `<div class="row" data-go="${routeOf(n.id)}" title="${esc(n.label)}">`
      + `<span>${esc(n.label)}</span><span class="n">${n.w}</span></div>`).join("");
    if(!rows) return;
    menEl.innerHTML = `<h4>Linked mentions</h4>`
      + (kicker?`<div class="row kick" style="pointer-events:none"><span>${esc(kicker.label)}</span>`
                + `<span class="n">${kicker.n}</span></div>`:"")
      + rows
      + (g.total>10?`<div class="more" style="margin:.4rem .35rem">and ${g.total-10} more</div>`:"");
  }
  menEl.addEventListener("click", ev=>{
    const row=ev.target.closest(".row[data-go]");
    if(row) location.hash=row.dataset.go;
  });

  // ── views ──
  function home(){
    const recent=[...C.index].filter(r=>r.date).sort((a,b)=>b.date.localeCompare(a.date)).slice(0,12);
    let h=`${h1of((C.meta.bundle||"elephant")+" knowledge")}
      <p class="desc">${C.meta.counts.entities||0} entities · ${C.meta.counts.facts||0} facts ·
      ${C.meta.counts.sources||0} sources — generated ${esc((C.meta.generated||"").replace("T"," "))}.</p>
      <div class="grid">`;
    kinds.forEach(k=>{
      const items=groups[k].slice(0,8);
      h+=`<div class="kindcard"><h3>${esc(k)} <span class="n">${groups[k].length}</span></h3>`;
      items.forEach(e=>h+=`<div><a href="${routeOf(e.id)}">${esc(e.title)}</a></div>`);
      if(groups[k].length>8) h+=`<div><a href="#/kind/${esc(k)}">all ${groups[k].length} →</a></div>`;
      h+=`</div>`;
    });
    h+=`</div><div class="sect">Recent</div>${recent.map(r=>r.t==="f"?factCard(r):srcRow(r)).join("")}`;
    app.innerHTML=h;
  }

  function kindList(kind){
    const items=groups[kind]||[];
    app.innerHTML=crumb([{label:"Entities"},{label:cap1(kind)}])
      + h1of(cap1(kind)) + `<p class="desc">${items.length} entities</p>`
      + (items.map(entRow).join("")||'<div class="empty">none</div>');
  }

  function entityView(id){
    const e=entById.get(id);
    if(!e){app.innerHTML='<div class="empty">unknown entity</div>';return;}
    const fcards=e.factIds.map(fid=>idxById.get(fid)).filter(Boolean)
      .sort((a,b)=>(b.date||"").localeCompare(a.date||"")).map(factCard).join("");
    app.innerHTML=crumb([{label:"Entities"},{label:cap1(e.kind),go:"#/kind/"+e.kind},{label:e.title}])
      + h1of(e.title)
      + `<div class="meta"><span class="chip k">${esc(e.kind)}</span>${chips(e.tags)}</div>`
      + (e.desc?`<p class="desc">${esc(e.desc)}</p>`:"")
      + (e.aliases&&e.aliases.length?`<div class="meta">also known as ${e.aliases.map(esc).join(", ")}</div>`:"")
      + (e.prose?`<div class="prose">${e.prose}</div>`:"")
      + `<div class="sect">Facts <span class="n">${e.factIds.length}</span></div>`
      + (fcards||'<div class="empty">no facts link here yet</div>');
    fillRail(id, {label:"Facts here", n:e.factIds.length});
  }

  async function factView(id){
    const r=idxById.get(id);
    if(!r){app.innerHTML='<div class="empty">unknown fact</div>';return;}
    app.innerHTML='<div class="empty">loading…</div>';
    await loadShard("f",r.sh);
    if(routeNow()!==id) return;              // navigated away while the shard loaded
    const full=(shards.f[r.sh]||{})[id]||{};
    const srcs=(full.sources||[]).map(s=>
      `<div class="item" data-go="${routeOf(s)}"><a class="t" href="${routeOf(s)}">`
      + `${esc((idxById.get(s)||{}).desc||s)}</a></div>`).join("");
    let rels="";
    Object.entries(full.relations||{}).forEach(([k,arr])=>{
      const links=arr.map(x=>`<a href="${routeOf(x)}">${esc((idxById.get(x)||{}).desc||x)}</a>`).join(", ");
      if(links) rels+=`<div class="rel"><b>${esc(k.replace(/-/g," "))}</b><br>${links}</div>`;
    });
    app.innerHTML=crumb([{label:"Facts",go:"#/facts"},{label:r.date||"fact"}])
      + h1of(r.desc)
      + `<div class="meta">${badges(r)}${r.date?`<span class="dt">${esc(r.date)}</span>`:""}
         ${full.times?`<span>referenced ${full.times}×</span>`:""}${chips(r.tags)}</div>`
      + (full.body?`<div class="prose">${full.body}</div>`:"")
      + (rels?`<div class="sect">Relations</div>${rels}`:"")
      + (srcs?`<div class="sect">Sources</div>${srcs}`:"");
    fillRail(id, null);
  }

  async function sourceView(id){
    const r=idxById.get(id);
    if(!r){app.innerHTML='<div class="empty">unknown source</div>';return;}
    app.innerHTML='<div class="empty">loading…</div>';
    await loadShard("s",r.sh);
    if(routeNow()!==id) return;
    const full=(shards.s[r.sh]||{})[id]||{};
    const facts=(full.factIds||[]).map(f=>idxById.get(f)).filter(Boolean).map(factCard).join("");
    app.innerHTML=crumb([{label:"Sources",go:"#/sources"},{label:r.channel||r.kind||"source"}])
      + h1of(r.desc)
      + `<div class="meta">${r.channel?`<span class="chip">${esc(r.channel)}</span>`:""}
         ${r.kind?`<span>${esc(r.kind)}</span>`:""}${r.date?`<span class="dt">${esc(r.date)}</span>`:""}
         ${chips(r.tags)}</div>`
      + (full.resource?`<div class="meta">origin: ${/^https?:/.test(full.resource)
           ?`<a href="${esc(full.resource)}" target="_blank" rel="noopener">${esc(full.resource)}</a>`
           :esc(full.resource)}</div>`:"")
      + (full.body?`<div class="prose">${full.body}</div>`:"")
      + `<div class="sect">Facts from this source <span class="n">${(full.factIds||[]).length}</span></div>`
      + (facts||'<div class="empty">none linked</div>');
  }

  function browseList(kind){
    const isFacts = kind==="facts";
    const rows=C.index.filter(r=>r.t===(isFacts?"f":"s"))
      .sort((a,b)=>(b.date||"").localeCompare(a.date||""));
    app.innerHTML=crumb([{label:"Browse"},{label:cap1(kind)}])
      + h1of(cap1(kind)) + `<p class="desc">${rows.length} in the bundle</p>`
      + rows.slice(0,300).map(isFacts?factCard:srcRow).join("")
      + (rows.length>300?`<p class="more">Showing the 300 most recent of ${rows.length} — search to narrow.</p>`:"");
  }

  function search(term){
    const t=term.toLowerCase();
    const eHits=C.entities.filter(e=>
      (e.title+" "+e.desc+" "+(e.aliases||[]).join(" ")+" "+(e.tags||[]).join(" ")).toLowerCase().includes(t)).slice(0,40);
    const iHits=C.index.filter(r=>
      ((r.desc||"")+" "+(r.tags||[]).join(" ")+" "+(r.channel||"")).toLowerCase().includes(t)).slice(0,60);
    const fHits=iHits.filter(r=>r.t==="f"), sHits=iHits.filter(r=>r.t==="s");
    let h=crumb([{label:"Search"},{label:term}]) + h1of("“"+term+"”")
      + `<p class="desc">${eHits.length+iHits.length}${eHits.length+iHits.length>=100?"+":""} matches</p>`;
    if(eHits.length) h+=`<div class="sect">Entities <span class="n">${eHits.length}</span></div>`+eHits.map(entRow).join("");
    if(fHits.length) h+=`<div class="sect">Facts <span class="n">${fHits.length}</span></div>`+fHits.map(factCard).join("");
    if(sHits.length) h+=`<div class="sect">Sources <span class="n">${sHits.length}</span></div>`+sHits.map(srcRow).join("");
    if(!eHits.length&&!iHits.length) h+='<div class="empty">no matches</div>';
    app.innerHTML=h;
  }

  // ── hover preview ──
  // Obsidian's page preview, on the data core.js already holds: entities in
  // full, facts in the slim index. Never loads a shard, so hovering a list of
  // 300 facts costs nothing. One delegated pair of listeners, not 300.
  let popT=0, popFor=null;
  function popFill(id){
    const e=entById.get(id);
    if(e) return `<span class="t">${esc(e.title)}</span>`
      + `<div class="meta"><span class="chip k">${esc(e.kind)}</span>`
      + `<span>${e.factIds.length} fact${e.factIds.length===1?"":"s"}</span></div>`
      + (e.desc?`<p class="d">${esc(e.desc)}</p>`:"");
    const r=idxById.get(id);
    if(!r) return null;
    return `<span class="t">${esc(r.t==="f"?"Fact":"Source")}</span>`
      + `<p class="d">${esc(r.desc)}</p>`
      + `<div class="meta">${badges(r)}${r.date?`<span class="dt">${esc(r.date)}</span>`:""}`
      + `${r.channel?`<span class="chip">${esc(r.channel)}</span>`:""}</div>`;
  }
  function popShow(a){
    const id = dec(a.getAttribute("href")).slice(1)+".md";
    const html = popFill(id);
    if(!html) return;
    popFor=id;
    popEl.innerHTML=html; popEl.hidden=false;
    const r=a.getBoundingClientRect(), b=popEl.getBoundingClientRect();
    let x=r.left, y=r.bottom+7;
    if(x+b.width>innerWidth-12) x=Math.max(12,innerWidth-12-b.width);
    if(y+b.height>innerHeight-12) y=Math.max(12,r.top-b.height-7);
    popEl.style.left=Math.round(x)+"px"; popEl.style.top=Math.round(y)+"px";
    popEl.setAttribute("data-on","");
  }
  function popHide(){
    clearTimeout(popT); popFor=null;
    popEl.removeAttribute("data-on"); popEl.hidden=true;
  }
  // Not `.t`: that is a row's own title, and the row already shows the whole
  // description, its date, its badges and its entities. Previewing it put a
  // floating copy of the sentence on top of the sentence.
  const PREVIEWABLE = 'a[href^="#/entities/"],a[href^="#/facts/"],a[href^="#/sources/"]';
  document.addEventListener("mouseover", ev=>{
    const a = ev.target.closest && ev.target.closest(PREVIEWABLE);
    if(!a || a.classList.contains("chip") || a.classList.contains("t")) return;
    clearTimeout(popT);
    popT=setTimeout(()=>popShow(a), 260);
  });
  document.addEventListener("mouseout", ev=>{
    const a = ev.target.closest && ev.target.closest(PREVIEWABLE);
    if(a) popHide();
  });
  pane.addEventListener("scroll",()=>{ if(popFor) popHide(); }, {passive:true});

  // ── a row is clickable everywhere, not only on its title ──
  document.addEventListener("click", ev=>{
    if(ev.target.closest("a,button")) return;
    const it=ev.target.closest(".item[data-go]");
    if(it) location.hash=it.dataset.go;
  });

  // ── router ──
  const routeNow = () => {
    const h=dec(location.hash||"#/");
    return h.startsWith("#/entities/")||h.startsWith("#/facts/")||h.startsWith("#/sources/")
      ? h.slice(1)+".md" : null;
  };
  function render(){
    const h=dec(location.hash||"#/");
    popHide(); clearRail();
    pane.scrollTop=0; window.scrollTo(0,0);
    const id=h.slice(1)+".md";
    markNav(h, h.startsWith("#/entities/")?id:null);
    if(h==="#/"||h==="") return home();
    if(h.startsWith("#/kind/")) return kindList(h.slice(7));
    if(h==="#/facts") return browseList("facts");
    if(h==="#/sources") return browseList("sources");
    if(h.startsWith("#/search/")) { q.value=h.slice(9); return search(h.slice(9)); }
    if(h.startsWith("#/entities/")) return entityView(id);
    if(h.startsWith("#/facts/")) return factView(id);
    if(h.startsWith("#/sources/")) return sourceView(id);
    home();
  }

  // ── search box + keyboard ──
  let deb;
  q.addEventListener("input",()=>{clearTimeout(deb);deb=setTimeout(()=>{
    const v=q.value.trim();
    if(v.length>=2) location.hash="#/search/"+encodeURIComponent(v);
    else if(location.hash.startsWith("#/search/")) location.hash="#/";
  },160);});
  q.addEventListener("keydown",ev=>{
    if(ev.key==="Escape"){ q.value=""; q.blur(); if(location.hash.startsWith("#/search/")) location.hash="#/"; }
  });
  document.getElementById("kbd").textContent = /Mac|iP/.test(navigator.platform||"") ? "⌘K" : "/";
  document.addEventListener("keydown",ev=>{
    const typing = /^(INPUT|TEXTAREA)$/.test((ev.target.tagName||""));
    if((ev.key==="k"||ev.key==="K") && (ev.metaKey||ev.ctrlKey)){ ev.preventDefault(); q.focus(); q.select(); return; }
    if(ev.key==="/" && !typing && !ev.metaKey && !ev.ctrlKey){ ev.preventDefault(); q.focus(); q.select(); }
  });

  buildNav();
  window.addEventListener("hashchange",render);
  render();
})();
