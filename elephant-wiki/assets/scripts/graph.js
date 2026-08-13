// The local knowledge graph view — one hop around the page's own node, drawn on
// a canvas by a spring sim that stops as soon as the layout settles.
// Entry point: window.localGraph(id, containerEl, {routeOf}).
(function(){
  const CAP = 40;      // this bundle is power-law: the busiest entity has 329 neighbours
  // The rail is no longer ~250px: above 2400px it is the widest track on the
  // screen. Derived from window.innerWidth and NOT from the box's clientWidth —
  // clientWidth reads 0 while the rail is display:none (the .norail views, the
  // <=1180px band before layout settles), and a 0 slipping past a guard would
  // pin every graph to 18 nodes, which looks exactly like the bug this fixes.
  // innerWidth is never 0 and has no ordering dependency on when the box was
  // built. 1440 -> 18, 1920 -> 29, >=2400 -> 40.
  const railCap = () => clamp(Math.round(18 + (window.innerWidth - 1440)/44), 18, CAP);
  const FRAMES = 200;  // hard frame cap; annealing normally stops the sim well before it
  const KE = 0.03;     // mean per-node squared step that counts as settled
  const COOL = 0.985;  // step multiplier decay — a 41-node star jitters forever without it
  const REP = 2400, SPRING = 0.02, PULL = 0.012, DAMP = 0.82, VMAX = 12;
  // 14 was right for a 300px-tall canvas. At >=1700px the canvas is at least
  // 512x384 and at 3200px it is 1472x1104, where 26 standing labels fit
  // comfortably. Same viewport source as railCap, so the two never disagree.
  // A third tier above the spec's two. At >=2400px the rail canvas is at least
  // 1094x820 — larger than the expanded sheet's own 1400x920 box, which already
  // draws all forty labels legibly. Without this the owner's 1472x1104 canvas
  // showed forty anonymous dots, which is the decorative-graph failure the
  // 0.1.0-beta.3 notes record, returning at 46% of the screen.
  const SMALL = 14, SMALL_WIDE = 26;
  // CAP+1, not CAP: `nodes` is the centre plus its neighbours, so a full
  // forty-neighbour page has length 41 and a bare CAP excludes the exact pages
  // this tier exists for.
  const smallCap = () => window.innerWidth >= 2400 ? CAP + 1
                       : window.innerWidth >= 1700 ? SMALL_WIDE : SMALL;
  // Hue per kind, with saturation and lightness left to the theme: one hex per
  // kind cannot serve both a near-white and a near-black canvas.
  // person is deliberately not on the accent's hue: this bundle is person-heavy,
  // and tinting the commonest kind the same warm tone as the accent made every
  // graph read as one colour and as if every node were selected.
  const HUE = {person:212,team:280,org:262,project:152,tool:32,concept:68,
               event:8,place:186,repo:96};
  // CVD: a Vienot LMS deuteranopia/protanopia pass on these nine hues at a
  // MATCHED lightness collapses person/team/org and tool/concept/repo to a
  // worst-pair OKLab distance of 0.0133 — below any JND. Hue is the channel
  // dichromacy destroys; lightness is the one it leaves intact. These offsets
  // keep every hue exactly as it was and separate the collapsing clusters by L
  // instead. Worst pair rises to 0.042 (3.2x), and every kind still clears 3:1
  // against the rail in both themes. Do not "tidy" these to zero: re-run the
  // simulation before changing any of them.
  const LK = {person:6, team:3, org:-6, project:-3, tool:-6,
              concept:0, event:-6, place:3, repo:-6};
  // Must match --ui in the sheet. The old string named 'Segoe UI' but not
  // system-ui, so a Linux canvas label diverged from the DOM text beside it.
  const GFONT = '-apple-system,BlinkMacSystemFont,system-ui,"Segoe UI",Roboto,'
              + '"Helvetica Neue",Arial,sans-serif';

  // A canvas cannot inherit a CSS variable, so the palette is read off the root
  // element and re-read when the theme flips.
  function palette(){
    const cs = getComputedStyle(document.documentElement);
    const v = n => cs.getPropertyValue(n).trim();
    const dark = document.documentElement.getAttribute("data-theme") === "dark";
    // s 44 -> 46 and l 41 -> 37 in light: on the new, much quieter rail the old
    // values put `concept` at 2.86:1, below 1.4.11's 3:1 for a graphical object.
    // Dark is untouched at 52/63 — the theme the owner likes.
    const s = dark?52:46, base = dark?63:37;
    const kind = {};
    Object.keys(HUE).forEach(k=>kind[k] = `hsl(${HUE[k]} ${s}% ${base+LK[k]}%)`);
    // The centred fact is a neutral, and a diamond rather than a circle: at full
    // text contrast it was the heaviest mark on a canvas of pastels and read as a
    // hole punched in the middle. The shape carries "not a kind", not the weight.
    return {kind:kind, other:`hsl(262 6% ${dark?58:46}%)`,
            fact:v("--b70")||"#484a4f",
            // Edges move from --line (1.39:1) to --b40 (2.26:1). A UI hairline
            // and an edge between forty nodes on a 1472px canvas are different
            // jobs. --b40 is a ramp token already declared in both themes, so
            // this is additive — no rename, no test surgery.
            edge:v("--b40")||"#adaaa6",
            line:v("--line")||"#dad8d4",
            dim:v("--line-soft")||"#e4e3df", accent:v("--accent")||"#8d4002",
            muted:v("--muted")||"#5c5f64", text:v("--text")||"#1b1e23"};
  }
  // The ring drawn around a node hides the edges running under it, so it has to
  // be the colour actually behind the canvas — which differs between the rail
  // and the expanded sheet. Walk up to the first ancestor that paints.
  function behind(el){
    for(let n=el; n && n!==document.documentElement; n=n.parentElement){
      const c = getComputedStyle(n).backgroundColor;
      if(c && !/^(transparent|rgba\(0, 0, 0, 0\))$/.test(c)) return c;
    }
    return getComputedStyle(document.body).backgroundColor || "#fff";
  }

  let maps = null, active = null;
  function M(){
    if(!maps){
      const C = window.__CORE__ || {entities:[],index:[]};
      maps = {ent:new Map(C.entities.map(e=>[e.id,e])), idx:new Map(C.index.map(r=>[r.id,r]))};
    }
    return maps;
  }
  const titleOf = id => (M().ent.get(id)||{}).title || id.split("/").pop().replace(/\.md$/,"");
  const clamp = (v,a,b) => v<a?a:v>b?b:v;

  // ── node set ──
  // An entity's neighbours are the entities it co-occurs with in a fact: the fact
  // is the edge, not a node, and the edge weight is how many facts they share. A
  // fact centres itself and links the entities it names. Both directions live in
  // the eager index (entity.factIds / row.ents), so no shard is ever loaded —
  // which is also why sources get no panel: their factIds are shard-only.
  function model(id, cap){
    const m = M(), e = m.ent.get(id), w = new Map();
    let centre;
    if(e){
      centre = {id:id, label:e.title, kind:e.kind};
      (e.factIds||[]).forEach(fid=>{
        const r = m.idx.get(fid); if(!r) return;
        (r.ents||[]).forEach(o=>{ if(o!==id && m.ent.has(o)) w.set(o,(w.get(o)||0)+1); });
      });
    }else{
      const r = m.idx.get(id);
      if(!r || r.t!=="f") return null;
      centre = {id:id, label:r.desc, fact:true};
      (r.ents||[]).forEach(o=>{ if(o!==id && m.ent.has(o)) w.set(o,1); });
    }
    const all = [];
    w.forEach((n,nid)=>all.push({id:nid, label:titleOf(nid), kind:(m.ent.get(nid)||{}).kind, w:n}));
    // weight first, then title, then id — the same page must draw the same graph
    all.sort((a,b)=> b.w-a.w || a.label.localeCompare(b.label) || (a.id<b.id?-1:1));
    return {centre:centre, nodes:all.slice(0, cap||CAP), total:all.length};
  }

  function teardown(p){
    if(p.dead) return;
    p.dead = true;
    if(p.raf) cancelAnimationFrame(p.raf);
    if(p.rel) p.rel();
    p.off.forEach(f=>f());
    if(active===p) active = null;
  }

  window.localGraph = function(id, el, api){
    if(active) teardown(active);
    if(!el) return;
    api = api || {};
    el.innerHTML = "";
    const fill = !!api.fill;                      // the expanded sheet sizes the canvas itself
    const g = model(id, api.cap || (fill?CAP:railCap()));
    if(!g || !g.nodes.length) return;  // fewer than 2 nodes: no panel at all
    const nodes = [g.centre].concat(g.nodes);
    let pal = palette();

    const hd = document.createElement("div");
    hd.className = "hd";
    const head = document.createElement("h4");
    head.textContent = "local graph";
    hd.appendChild(head);
    // The count is a caption under the canvas, not part of the label: in a 250px
    // rail "local graph · 18 of 153 neighbours" wrapped onto two lines and read
    // as the heading of the whole panel.
    const cnt = document.createElement("div");
    cnt.className = "cnt";
    cnt.textContent = g.total>g.nodes.length
      ? `${g.nodes.length} of ${g.total} neighbours`
      : `${g.nodes.length} neighbour${g.nodes.length>1?"s":""}`;
    if(api.expandable){
      const b = document.createElement("button");
      b.className = "exp"; b.textContent = "⤢";
      b.title = "Expand the graph"; b.setAttribute("aria-label","Expand the graph");
      b.addEventListener("click", ev=>{ ev.stopPropagation(); openExpanded(id, el, api); });
      hd.appendChild(b);
    }
    const box = document.createElement("div");
    box.className = "box";
    const cv = document.createElement("canvas");
    box.appendChild(cv);
    el.appendChild(hd); el.appendChild(box); el.appendChild(cnt);
    const ctx = cv.getContext && cv.getContext("2d");
    if(!ctx){ el.innerHTML=""; return; }  // no 2d context: draw nothing

    const p = {nodes:nodes, centre:nodes[0], off:[], rel:null, raf:0, frame:0, alpha:1,
               hover:null, drag:null, moved:0, W:600, H:320, L:100, dead:false,
               small:api.labels===true || nodes.length<=smallCap()};
    // The panel is sized to the graph, not the other way round: a 4-node star in a
    // 320px box reads as an empty box, and the rest length then follows the box, so
    // both a sparse and a 19-node page fill the space they are given. The expanded
    // sheet is the exception — there the box is given and the graph fills it.
    // The 300px ceiling was chosen for a 250px rail and is wrong on an 1800px
    // screen. Derived from innerHeight, NOT from getComputedStyle(box).maxHeight
    // — reading a resolved px value back out of a clamp()-valued real property is
    // an untested claim, and there is no need to make it. Above 1700px the box
    // has a definite height from CSS aspect-ratio and `height:100%!important`
    // overrides this inline value, the same way the <=1180px tier already does.
    if(!fill) cv.style.height = Math.round(clamp(190 + 11*nodes.length, 240,
        clamp(0.34*window.innerHeight, 300, 620))) + "px";
    let bg = behind(box);

    function size(){
      const dpr = window.devicePixelRatio||1;
      p.W = cv.clientWidth||p.W; p.H = cv.clientHeight||p.H;
      cv.width = Math.round(p.W*dpr); cv.height = Math.round(p.H*dpr);
      ctx.setTransform(dpr,0,0,dpr,0,0);  // CSS pixels everywhere below; crisp on retina
      // The star's radius is whatever the box can actually show: half the height
      // less the widest node and the standing label. Deriving it (rather than
      // picking a ratio) means the layout fills any panel size, including a
      // resize — and the ceiling has to grow with the box, or the expanded sheet
      // draws a 150px wheel in the middle of 700px of nothing.
      const ceil = Math.max(150, Math.min(p.H,p.W)/2 - 44);
      p.L = clamp(Math.min(p.H/2, 0.42*p.W) - 20 - (p.small?14:0), 50, ceil);
    }
    size();
    // weights span three orders of magnitude between pages, so scale them against
    // the heaviest edge on THIS page: degree always reads across the full 4..11px.
    const top = Math.log2(1+Math.max(1,g.nodes[0].w));
    const rel = w => Math.log2(1+w)/top;
    // Golden-angle ring seeded by index, never random — and seeded AT the rest
    // length, not inside it: the anneal stops on energy, so a tight seed settles
    // at half the radius it should and the star reads as a blob.
    nodes.forEach((n,i)=>{
      const a = i*2.399963, rad = i? p.L*(0.9+0.004*i) : 0;
      n.x = p.W/2+Math.cos(a)*rad; n.y = p.H/2+Math.sin(a)*rad; n.vx = 0; n.vy = 0;
      // 4-11px nodes are correct in a 286px rail and invisible on a 1472px
      // canvas. Scale with the smaller canvas dimension, capped at 1.9x.
      const k = clamp(Math.min(p.W,p.H)/340, 1, 1.9);
      n.r = i? clamp(4+7*rel(n.w),4,11)*k : 13*k;
      n.lw = i? clamp(0.7+2.1*rel(n.w),0.7,3) : 0;
    });
    const recolor = () => p.nodes.forEach(n=>{
      n.col = n.fact ? pal.fact : (pal.kind[n.kind] || pal.other);
    });
    recolor();

    function step(){
      const n = p.nodes, cx = p.W/2, cy = p.H/2;
      let ke = 0;
      for(let i=0;i<n.length;i++) for(let j=i+1;j<n.length;j++){   // 41 nodes: O(n²) is free
        const a=n[i], b=n[j];
        let dx=b.x-a.x, dy=b.y-a.y, d2=dx*dx+dy*dy;
        if(d2<1){ dx=1+i*0.01; dy=1-j*0.01; d2=dx*dx+dy*dy; }      // deterministic un-stick
        const d=Math.sqrt(d2), f=REP/Math.max(d2,64), fx=f*dx/d, fy=f*dy/d;
        a.vx-=fx; a.vy-=fy; b.vx+=fx; b.vy+=fy;
      }
      for(let i=1;i<n.length;i++){                                 // every edge runs to the centre
        const a=p.centre, b=n[i];
        const dx=b.x-a.x, dy=b.y-a.y, d=Math.sqrt(dx*dx+dy*dy)||1;
        const f=(d-p.L)*SPRING, fx=f*dx/d, fy=f*dy/d;
        a.vx+=fx; a.vy+=fy; b.vx-=fx; b.vy-=fy;
      }
      p.alpha *= COOL;
      for(let i=0;i<n.length;i++){
        // Only the centre is pulled to the middle. A neighbour pulled there too
        // fights its own spring and settles at ~0.6 of the rest length; the spring
        // plus the edge clamp already keep a star in frame.
        const a=n[i], pull=a===p.centre?PULL*5:0;
        a.vx=clamp((a.vx+(cx-a.x)*pull)*DAMP,-VMAX,VMAX);
        a.vy=clamp((a.vy+(cy-a.y)*pull)*DAMP,-VMAX,VMAX);
        if(a===p.drag){ a.vx=0; a.vy=0; continue; }
        const dx=a.vx*p.alpha, dy=a.vy*p.alpha;
        a.x=clamp(a.x+dx, a.r+2, p.W-a.r-2);
        // room for the standing label, at whichever end of the box it is drawn
        a.y=clamp(a.y+dy, a.r+2+(p.small?12:0), p.H-a.r-2-(p.small?14:0));
        ke += dx*dx+dy*dy;
      }
      return ke/n.length;
    }

    function label(a){
      const t=(a.label||"").slice(0,80);
      ctx.font='500 13.5px '+GFONT;                          // step 5, the hover box
      const w=ctx.measureText(t).width+12, x=clamp(a.x-w/2,2,Math.max(2,p.W-w-2)), y=clamp(a.y-a.r-24,2,p.H-22);
      ctx.fillStyle=bg; ctx.strokeStyle=pal.line; ctx.lineWidth=1;
      ctx.beginPath(); ctx.rect(x,y,w,20); ctx.fill(); ctx.stroke();
      ctx.fillStyle=pal.text; ctx.textBaseline="middle"; ctx.fillText(t,x+6,y+11);
    }
    // A sparse graph with no labels is decorative: you cannot tell who a dot is
    // without hovering it one at a time. Dense pages keep hover-only, where forty
    // standing labels would be worse than none.
    function standing(){
      ctx.font='400 12px '+GFONT;                            // step 6, standing labels
      ctx.fillStyle=pal.muted; ctx.textAlign="center";
      for(let i=1;i<p.nodes.length;i++){
        const a=p.nodes[i];
        if(a===p.hover) continue;                 // the hovered node gets the boxed label instead
        let t=a.label||"";
        if(t.length>22) t=t.slice(0,21)+"…";
        // Outward from the centre, not always below: with forty labels all sitting
        // under their node, every label on the top of the ring landed inside the
        // ring and collided with the node above it.
        const up = a.y < p.centre.y;
        ctx.textBaseline = up?"bottom":"top";
        ctx.fillText(t, clamp(a.x, 4+ctx.measureText(t).width/2, p.W-4-ctx.measureText(t).width/2),
                     up ? a.y-a.r-3 : a.y+a.r+3);
      }
      ctx.textAlign="left"; ctx.textBaseline="alphabetic";
    }
    function draw(){
      const n=p.nodes;
      ctx.clearRect(0,0,p.W,p.H);
      // Edges: --b40 at rest, --line-soft when something else is hovered. The
      // accent NEVER touches an edge — the comment above HUE records that
      // colliding the accent with node colour made every graph read as one
      // colour, and the accent's hue floor (>=46) exists for the same reason.
      for(let i=1;i<n.length;i++){
        const b=n[i], on=!p.hover||p.hover===b||p.hover===p.centre;
        ctx.globalAlpha = on ? 1 : 0.35;
        ctx.strokeStyle = on ? pal.edge : pal.dim;
        ctx.lineWidth = b.lw * (p.hover===b ? 1.6 : 1);
        ctx.beginPath(); ctx.moveTo(p.centre.x,p.centre.y); ctx.lineTo(b.x,b.y); ctx.stroke();
      }
      ctx.globalAlpha = 1;
      n.forEach(a=>{
        const r=a.r;
        // Hover focus: the difference between an instrument and a physics demo.
        // Everything that is not the hovered node or the centre drops to .32, so
        // a 40-node star becomes a readable one-hop query.
        ctx.globalAlpha = (!p.hover || a===p.hover || a===p.centre) ? 1 : 0.32;
        ctx.beginPath();
        if(a.fact){ ctx.moveTo(a.x,a.y-r);ctx.lineTo(a.x+r,a.y);ctx.lineTo(a.x,a.y+r);ctx.lineTo(a.x-r,a.y);ctx.closePath(); }
        else ctx.arc(a.x,a.y,r,0,6.2832);
        ctx.fillStyle=a.col; ctx.fill();
        ctx.lineWidth=1.5; ctx.strokeStyle=bg; ctx.stroke();
        if(a===p.centre||a===p.hover){
          // The accent's ONLY appearance on the canvas. A 1.5px gap in the
          // background colour separates the ring from the fill, so it can never
          // be mistaken for a kind colour.
          ctx.beginPath(); ctx.arc(a.x,a.y,r+2,0,6.2832);
          ctx.lineWidth=1.5; ctx.strokeStyle=bg; ctx.stroke();
          ctx.beginPath(); ctx.arc(a.x,a.y,r+4,0,6.2832);
          ctx.lineWidth=2; ctx.strokeStyle=pal.accent; ctx.stroke();
        }
        ctx.globalAlpha = 1;
      });
      if(p.small) standing();
      if(p.hover) label(p.hover);
    }

    function tick(){
      p.raf=0;
      if(p.dead) return;
      if(el.isConnected===false) return teardown(p);  // view re-rendered under us
      const ke=step();
      draw();
      p.frame++;
      if(p.drag || (p.frame<FRAMES && ke>KE)) p.raf=requestAnimationFrame(tick);
    }
    function reheat(){ p.frame=0; p.alpha=Math.max(p.alpha,0.6); if(!p.raf && !p.dead) p.raf=requestAnimationFrame(tick); }

    function on(t,ev,fn){ t.addEventListener(ev,fn); p.off.push(()=>t.removeEventListener(ev,fn)); }
    const pos = e => { const b=cv.getBoundingClientRect(); return [e.clientX-b.left, e.clientY-b.top]; };
    const at = (x,y) => p.nodes.find(a=>{const dx=x-a.x,dy=y-a.y;return dx*dx+dy*dy<=(a.r+4)*(a.r+4)})||null;
    function hover(h){
      if(h===p.hover) return;
      p.hover=h; cv.style.cursor=h?"pointer":"default";
      if(!p.raf) draw();
    }
    on(cv,"mousemove",e=>{ if(!p.drag){ const q=pos(e); hover(at(q[0],q[1])); } });
    on(cv,"mouseleave",()=>{ if(!p.drag) hover(null); });
    on(cv,"mousedown",e=>{
      const q=pos(e), h=at(q[0],q[1]);
      if(!h) return;
      e.preventDefault();
      p.drag=h; p.moved=0;
      const ox=h.x-q[0], oy=h.y-q[1];   // grab offset: measure travel from the pointer, not
      const mv=ev=>{                    // from the node, or a click near its rim reads as a drag
        if(ev.buttons===0) return up(); // mouseup fired outside the window: buttons reads 0 the
                                         // moment the pointer returns — end the drag instead of
                                         // leaking an unbounded rAF loop with a stuck p.drag
        const m=pos(ev);
        p.moved=Math.max(p.moved, Math.abs(m[0]-q[0])+Math.abs(m[1]-q[1]));
        h.x=clamp(m[0]+ox,h.r,p.W-h.r); h.y=clamp(m[1]+oy,h.r,p.H-h.r);
        reheat();
      };
      const up=()=>{
        if(p.rel) p.rel();
        p.drag=null;
        if(p.moved<5 && h!==p.centre && api && api.routeOf) location.hash=api.routeOf(h.id);
        else reheat();  // a drag settles the graph around the node instead of navigating
      };
      p.rel=()=>{ window.removeEventListener("mousemove",mv); window.removeEventListener("mouseup",up); p.rel=null; };
      window.addEventListener("mousemove",mv); window.addEventListener("mouseup",up);
    });
    // Released outside the window AND never moved back in: the buttons===0 check
    // above never gets a mousemove to fire on, so blur is the only signal left
    // that the drag is over. Ends it without navigating.
    on(window,"blur",()=>{
      if(!p.drag) return;
      if(p.rel) p.rel();
      p.drag = null;
      reheat();
    });
    on(window,"resize",()=>{ if(el.isConnected===false) return teardown(p); size(); reheat(); });
    // A window resize is not the only way the box changes size: the panel shares a
    // flex line with the mentions block on narrow viewports, and a rail can be
    // shown or hidden between routes. Re-measuring from the element itself means
    // the layout never depends on when the caller happened to call us.
    if(window.ResizeObserver){
      const ro = new ResizeObserver(()=>{
        if(p.dead) return;
        if(Math.abs(cv.clientWidth-p.W)<1 && Math.abs(cv.clientHeight-p.H)<1) return;
        size(); reheat();
      });
      ro.observe(cv);
      p.off.push(()=>ro.disconnect());
    }
    on(window,"hashchange",()=>teardown(p));
    // The palette lives in CSS, the canvas does not: without this a theme flip
    // leaves the graph drawn in the other theme's colours until you navigate.
    on(window,"elephant-theme",()=>{
      pal = palette(); bg = behind(box); recolor();
      if(!p.raf) draw();
    });

    active = p;
    reheat();
    return p;
  };

  // ── the expanded sheet ───────────────────────────────────────────────────
  // The rail is too narrow for labels, so the full graph lives in an overlay.
  // There is only ever one simulation (`active`), so expanding hands it over
  // and closing hands it back rather than running two.
  let sheet = null;
  function openExpanded(id, railEl, railApi){
    closeExpanded(false);
    const host = railApi.host || document.body;
    const ov = document.createElement("div");
    ov.className = "ov";
    ov.innerHTML = '<div class="sheet"><div class="bar"><h4></h4>'
                 + '<button class="x" title="Close" aria-label="Close">✕</button></div>'
                 + '<div class="lg"></div></div>';
    host.appendChild(ov);
    const lg = ov.querySelector(".lg");
    const inst = window.localGraph(id, lg, {routeOf:railApi.routeOf, host:host,
                                            cap:CAP, labels:true, fill:true});
    if(!inst){ ov.remove(); return; }
    const cap = lg.querySelector(".cnt");
    ov.querySelector(".bar h4").textContent =
      "local graph · " + (inst.centre.label||"") + (cap?" · "+cap.textContent:"");
    const esc = ev=>{ if(ev.key==="Escape"){ ev.preventDefault(); closeExpanded(true); } };
    ov.addEventListener("click", ev=>{
      if(ev.target===ov || ev.target.closest(".x")) closeExpanded(true);
    });
    document.addEventListener("keydown", esc);
    sheet = {ov:ov, esc:esc, back:{id:id, el:railEl, api:railApi}};
  }
  function closeExpanded(restore){
    if(!sheet) return;
    const s = sheet; sheet = null;
    document.removeEventListener("keydown", s.esc);
    if(active) teardown(active);        // the sheet's own simulation
    s.ov.remove();
    // Only the close button and Escape restore. The router calls this while it is
    // rebuilding the rail, so restoring there would seed a simulation into an
    // element it is about to empty, leaving it ticking against a detached canvas.
    if(restore) window.localGraph(s.back.id, s.back.el, s.back.api);
  }

  window.localGraph.model = model;  // pure node-set builder, for tests
  window.localGraph.closeExpanded = closeExpanded;
})();
