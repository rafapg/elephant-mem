(function(){
  const C = window.__CORE__ || {meta:{counts:{}},entities:[],index:[]};
  const app = document.getElementById("app");
  const q = document.getElementById("q");
  document.getElementById("counts").textContent =
    `${C.meta.counts.entities||0} entities · ${C.meta.counts.facts||0} facts · ${C.meta.counts.sources||0} sources`;

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
  const titleOfEnt = id => (entById.get(id)||{}).title || id.split("/").pop().replace(/\.md$/,"");
  // local graph panel (graph.js) — additive: the textual lists stay as they are
  const graph = id => window.localGraph && window.localGraph(id, document.getElementById("lg"), {routeOf});

  function chips(tags, kind){
    let h = kind?`<span class="chip k">${esc(kind)}</span>`:"";
    (tags||[]).slice(0,6).forEach(t=>h+=`<span class="chip">${esc(t)}</span>`);
    return h;
  }
  function badges(r){
    let h="";
    if(r.conf) h+=`<span class="badge b-${r.conf}">${r.conf}</span>`;
    if(r.status && r.status!=="active") h+=` <span class="badge b-${r.status}">${r.status}</span>`;
    return h;
  }

  // ── fact / entity / source cards ──
  function factCard(r){
    const ents = (r.ents||[]).map(e=>`<a href="${routeOf(e)}">${esc(titleOfEnt(e))}</a>`).join(", ");
    return `<div class="card"><p class="d"><a href="${routeOf(r.id)}">${esc(r.desc)}</a></p>
      <div class="meta">${badges(r)} ${r.date?`<span>${esc(r.date)}</span>`:""}
      ${ents?`<span>· ${ents}</span>`:""} ${chips(r.tags)}</div></div>`;
  }
  function srcRow(r){
    return `<div class="card"><p class="d"><a href="${routeOf(r.id)}">${esc(r.desc)}</a></p>
      <div class="meta">${r.channel?`<span class="chip">${esc(r.channel)}</span>`:""}
      ${r.kind?`<span>${esc(r.kind)}</span>`:""} ${r.date?`<span>· ${esc(r.date)}</span>`:""} ${chips(r.tags)}</div></div>`;
  }

  // ── views ──
  function home(){
    const groups={}; C.entities.forEach(e=>(groups[e.kind]=groups[e.kind]||[]).push(e));
    const kinds=Object.keys(groups).sort((a,b)=>{
      const ia=KIND_ORDER.indexOf(a),ib=KIND_ORDER.indexOf(b);
      return (ia<0?99:ia)-(ib<0?99:ib)||a.localeCompare(b);});
    let side=`<div class="side"><h4>entities</h4>`;
    kinds.forEach(k=>side+=`<a href="#/kind/${k}"><span style="text-transform:capitalize">${k}</span><span class="n">${groups[k].length}</span></a>`);
    side+=`<h4 style="margin-top:1rem">browse</h4>
      <a href="#/facts"><span>Facts</span><span class="n">${C.meta.counts.facts}</span></a>
      <a href="#/sources"><span>Sources</span><span class="n">${C.meta.counts.sources}</span></a></div>`;
    const recent=[...C.index].filter(r=>r.date).sort((a,b)=>b.date.localeCompare(a.date)).slice(0,12);
    let mainh=`<div><h1>${esc(C.meta.bundle||"elephant")} knowledge</h1>
      <p class="desc">A navigable view of the bundle — generated ${esc((C.meta.generated||"").replace("T"," "))}.</p>
      <div class="grid">`;
    kinds.forEach(k=>{
      const items=groups[k].slice().sort((a,b)=>a.title.localeCompare(b.title)).slice(0,8);
      mainh+=`<div class="kindcard"><h3>${k} <span class="n" style="color:var(--muted);font-size:12px">${groups[k].length}</span></h3>`;
      items.forEach(e=>mainh+=`<div><a href="${routeOf(e.id)}">${esc(e.title)}</a></div>`);
      if(groups[k].length>8) mainh+=`<div><a href="#/kind/${k}" style="font-size:12px">all ${groups[k].length} →</a></div>`;
      mainh+=`</div>`;
    });
    mainh+=`</div><h2>Recent</h2>${recent.map(r=>r.t==="f"?factCard(r):srcRow(r)).join("")}</div>`;
    app.innerHTML=`<div class="layout">${side}${mainh}</div>`;
  }

  function kindList(kind){
    const items=C.entities.filter(e=>e.kind===kind).sort((a,b)=>a.title.localeCompare(b.title));
    app.innerHTML=`<span class="back" onclick="history.back()">← back</span>
      <h1 style="text-transform:capitalize">${esc(kind)} <span class="n" style="color:var(--muted);font-size:1rem">${items.length}</span></h1>
      ${items.map(e=>`<div class="card"><p class="d"><a href="${routeOf(e.id)}">${esc(e.title)}</a></p>
        <div class="meta">${e.desc?esc(e.desc):""}</div></div>`).join("")||'<div class="empty">none</div>'}`;
  }

  function entityView(id){
    const e=entById.get(id);
    if(!e){app.innerHTML='<div class="empty">unknown entity</div>';return;}
    const fcards=e.factIds.map(fid=>idxById.get(fid)).filter(Boolean)
      .sort((a,b)=>(b.date||"").localeCompare(a.date||"")).map(factCard).join("");
    const al=e.aliases&&e.aliases.length?`<div class="meta">also: ${e.aliases.map(esc).join(", ")}</div>`:"";
    app.innerHTML=`<span class="back" onclick="history.back()">← back</span>
      <h1>${esc(e.title)} <span class="chip k">${esc(e.kind)}</span></h1>
      <p class="desc">${esc(e.desc)}</p>${al}
      <div class="meta">${chips(e.tags)}</div>
      ${e.prose?`<div class="prose">${e.prose}</div>`:""}
      <div class="lg" id="lg"></div>
      <h2>Facts <span class="n" style="color:var(--muted);font-size:.85rem">${e.factIds.length}</span></h2>
      ${fcards||'<div class="empty">no facts link here yet</div>'}`;
    graph(id);
  }

  async function factView(id){
    const r=idxById.get(id);
    if(!r){app.innerHTML='<div class="empty">unknown fact</div>';return;}
    app.innerHTML=`<span class="back" onclick="history.back()">← back</span><div class="empty">loading…</div>`;
    await loadShard("f",r.sh);
    const full=(shards.f[r.sh]||{})[id]||{};
    const ents=(r.ents||[]).map(e=>`<a href="${routeOf(e)}">${esc(titleOfEnt(e))}</a>`).join(", ");
    const srcs=(full.sources||[]).map(s=>`<a href="${routeOf(s)}">${esc((idxById.get(s)||{}).desc||s)}</a>`).join("<br>");
    let rels="";
    Object.entries(full.relations||{}).forEach(([k,arr])=>{
      const links=arr.map(x=>`<a href="${routeOf(x)}">${esc((idxById.get(x)||{}).desc||x)}</a>`).join(", ");
      if(links) rels+=`<div class="rel"><b>${k.replace(/-/g," ")}:</b> ${links}</div>`;
    });
    app.innerHTML=`<span class="back" onclick="history.back()">← back</span>
      <h1 style="font-size:1.2rem">${esc(r.desc)}</h1>
      <div class="meta">${badges(r)} ${r.date?`<span>occurred ${esc(r.date)}</span>`:""}
        ${full.times?`<span>· referenced ${full.times}×</span>`:""} ${chips(r.tags)}</div>
      ${ents?`<div class="meta" style="margin-top:.5rem">about: ${ents}</div>`:""}
      ${full.body?`<div class="prose">${full.body}</div>`:""}
      <div class="lg" id="lg"></div>
      ${rels?`<h2>Relations</h2>${rels}`:""}
      ${srcs?`<h2>Sources</h2><div class="card">${srcs}</div>`:""}`;
    graph(id);
  }

  async function sourceView(id){
    const r=idxById.get(id);
    if(!r){app.innerHTML='<div class="empty">unknown source</div>';return;}
    app.innerHTML=`<span class="back" onclick="history.back()">← back</span><div class="empty">loading…</div>`;
    await loadShard("s",r.sh);
    const full=(shards.s[r.sh]||{})[id]||{};
    const facts=(full.factIds||[]).map(f=>idxById.get(f)).filter(Boolean).map(factCard).join("");
    app.innerHTML=`<span class="back" onclick="history.back()">← back</span>
      <h1 style="font-size:1.2rem">${esc(r.desc)}</h1>
      <div class="meta">${r.channel?`<span class="chip">${esc(r.channel)}</span>`:""}
        ${r.kind?`<span>${esc(r.kind)}</span>`:""} ${r.date?`<span>· ${esc(r.date)}</span>`:""} ${chips(r.tags)}</div>
      ${full.resource?`<div class="meta" style="margin-top:.4rem">origin: ${/^https?:/.test(full.resource)?`<a href="${esc(full.resource)}" target="_blank" rel="noopener">${esc(full.resource)}</a>`:esc(full.resource)}</div>`:""}
      ${full.body?`<div class="prose">${full.body}</div>`:""}
      <h2>Facts from this source <span class="n" style="color:var(--muted);font-size:.85rem">${(full.factIds||[]).length}</span></h2>
      ${facts||'<div class="empty">none linked</div>'}`;
  }

  // ── browse-all with type filter ──
  let listFilter="all";
  function browseList(kind){
    const isFacts = kind==="facts";
    const rows=C.index.filter(r=>r.t===(isFacts?"f":"s"))
      .sort((a,b)=>(b.date||"").localeCompare(a.date||""));
    app.innerHTML=`<span class="back" onclick="history.back()">← back</span>
      <h1 style="text-transform:capitalize">${kind} <span class="n" style="color:var(--muted);font-size:1rem">${rows.length}</span></h1>
      <div id="rows">${rows.slice(0,300).map(isFacts?factCard:srcRow).join("")}</div>
      ${rows.length>300?`<p class="desc">showing first 300 of ${rows.length} — use search to narrow.</p>`:""}`;
  }

  // ── search ──
  function search(term){
    const t=term.toLowerCase();
    const eHits=C.entities.filter(e=>
      (e.title+" "+e.desc+" "+(e.aliases||[]).join(" ")+" "+(e.tags||[]).join(" ")).toLowerCase().includes(t)).slice(0,40);
    const iHits=C.index.filter(r=>
      ((r.desc||"")+" "+(r.tags||[]).join(" ")+" "+(r.channel||"")).toLowerCase().includes(t)).slice(0,60);
    let h=`<h1>Search <span class="n" style="color:var(--muted);font-size:1rem">${eHits.length+iHits.length}+ hits</span></h1>`;
    if(eHits.length){h+=`<h2>Entities</h2>`+eHits.map(e=>
      `<div class="card"><p class="d"><a href="${routeOf(e.id)}">${esc(e.title)}</a> <span class="chip k">${esc(e.kind)}</span></p>
       <div class="meta">${e.desc?esc(e.desc):""}</div></div>`).join("");}
    const fHits=iHits.filter(r=>r.t==="f"), sHits=iHits.filter(r=>r.t==="s");
    if(fHits.length){h+=`<h2>Facts</h2>`+fHits.map(factCard).join("");}
    if(sHits.length){h+=`<h2>Sources</h2>`+sHits.map(srcRow).join("");}
    if(!eHits.length&&!iHits.length) h+='<div class="empty">no matches</div>';
    app.innerHTML=h;
  }

  // ── router ──
  function render(){
    const h=decodeURIComponent(location.hash||"#/");
    window.scrollTo(0,0);
    if(h==="#/"||h==="") return home();
    if(h.startsWith("#/kind/")) return kindList(h.slice(7));
    if(h==="#/facts") return browseList("facts");
    if(h==="#/sources") return browseList("sources");
    if(h.startsWith("#/search/")) { q.value=h.slice(9); return search(h.slice(9)); }
    const id=h.slice(1)+".md";
    if(h.startsWith("#/entities/")) return entityView(id);
    if(h.startsWith("#/facts/")) return factView(id);
    if(h.startsWith("#/sources/")) return sourceView(id);
    home();
  }
  let deb;
  q.addEventListener("input",()=>{clearTimeout(deb);deb=setTimeout(()=>{
    const v=q.value.trim();
    if(v.length>=2) location.hash="#/search/"+encodeURIComponent(v);
    else if(location.hash.startsWith("#/search/")) location.hash="#/";
  },160);});
  window.addEventListener("hashchange",render);
  render();
})();