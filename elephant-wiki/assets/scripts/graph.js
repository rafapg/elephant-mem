// The local knowledge graph view — one hop around the page's own node, drawn on
// a canvas by a spring sim that stops as soon as the layout settles.
// Entry point: window.localGraph(id, containerEl, {routeOf}).
(function(){
  const CAP = 40;      // this bundle is power-law: the busiest entity has 329 neighbours
  const FRAMES = 200;  // hard frame cap; annealing normally stops the sim well before it
  const KE = 0.03;     // mean per-node squared step that counts as settled
  const COOL = 0.985;  // step multiplier decay — a 41-node star jitters forever without it
  const REP = 2400, SPRING = 0.02, PULL = 0.012, DAMP = 0.82, VMAX = 12;
  const SMALL = 14;    // at or below this many nodes, every label is drawn, not just the hovered one
  const KIND = {person:"#7a5b34",team:"#9a7b4a",org:"#5f6d86",project:"#4a7a5e",
                tool:"#8a6a86",concept:"#6f6a55",event:"#a07340",place:"#4f7d7d",repo:"#7d6a4f"};
  const FACT = "#2b2721";  // the centred fact, deliberately unlike any entity kind
  const LINE = "#e6e2da", LINE_ON = "#c6b294", ACCENT = "#7a5b34", BG = "#faf9f7";

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
  function model(id){
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
    return {centre:centre, nodes:all.slice(0,CAP), total:all.length};
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
    el.innerHTML = "";
    const g = model(id);
    if(!g || !g.nodes.length) return;  // fewer than 2 nodes: no panel at all
    const nodes = [g.centre].concat(g.nodes);

    const head = document.createElement("h4");
    head.textContent = "local graph · " + (g.total>g.nodes.length
      ? `showing ${g.nodes.length} of ${g.total} neighbours`
      : `${g.nodes.length} neighbour${g.nodes.length>1?"s":""}`);
    const cv = document.createElement("canvas");
    el.appendChild(head); el.appendChild(cv);
    const ctx = cv.getContext && cv.getContext("2d");
    if(!ctx){ el.innerHTML=""; return; }  // no 2d context: draw nothing

    const p = {nodes:nodes, centre:nodes[0], off:[], rel:null, raf:0, frame:0, alpha:1,
               hover:null, drag:null, moved:0, W:600, H:320, L:100, dead:false,
               small:nodes.length<=SMALL};
    // The panel is sized to the graph, not the other way round: a 4-node star in a
    // 320px box reads as an empty box, and the rest length then follows the box, so
    // both a sparse and a 41-node page fill the space they are given.
    cv.style.height = Math.round(clamp(150+6*nodes.length, 150, 320)) + "px";

    function size(){
      const dpr = window.devicePixelRatio||1;
      p.W = cv.clientWidth||p.W; p.H = cv.clientHeight||p.H;
      cv.width = Math.round(p.W*dpr); cv.height = Math.round(p.H*dpr);
      ctx.setTransform(dpr,0,0,dpr,0,0);  // CSS pixels everywhere below; crisp on retina
      // The star's radius is whatever the box can actually show: half the height
      // less the widest node and the standing label. Deriving it (rather than
      // picking a ratio) means the layout fills any panel size, including a resize.
      p.L = clamp(Math.min(p.H/2, 0.42*p.W) - 20 - (p.small?14:0), 50, 150);
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
      n.r = i? clamp(4+7*rel(n.w),4,11) : 13;
      n.lw = i? clamp(0.7+2.1*rel(n.w),0.7,3) : 0;
      n.col = n.fact?FACT:(KIND[n.kind]||"#8a8375");
    });

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
        a.y=clamp(a.y+dy, a.r+2, p.H-a.r-2-(p.small?14:0));  // room for the standing label
        ke += dx*dx+dy*dy;
      }
      return ke/n.length;
    }

    function label(a){
      const t=(a.label||"").slice(0,80);
      ctx.font="12px -apple-system,BlinkMacSystemFont,'Segoe UI',Helvetica,sans-serif";
      const w=ctx.measureText(t).width+10, x=clamp(a.x-w/2,2,Math.max(2,p.W-w-2)), y=clamp(a.y-a.r-21,2,p.H-19);
      ctx.fillStyle="rgba(250,249,247,.95)"; ctx.strokeStyle=LINE; ctx.lineWidth=1;
      ctx.beginPath(); ctx.rect(x,y,w,17); ctx.fill(); ctx.stroke();
      ctx.fillStyle="#1c1a17"; ctx.textBaseline="middle"; ctx.fillText(t,x+5,y+9.5);
    }
    // A sparse graph with no labels is decorative: you cannot tell who a dot is
    // without hovering it one at a time. Dense pages keep hover-only, where forty
    // standing labels would be worse than none.
    function standing(){
      ctx.font="11px -apple-system,BlinkMacSystemFont,'Segoe UI',Helvetica,sans-serif";
      ctx.fillStyle="#6b665e"; ctx.textAlign="center"; ctx.textBaseline="top";
      for(let i=1;i<p.nodes.length;i++){
        const a=p.nodes[i];
        if(a===p.hover) continue;                 // the hovered node gets the boxed label instead
        let t=a.label||"";
        if(t.length>22) t=t.slice(0,21)+"…";
        ctx.fillText(t, clamp(a.x, 4+ctx.measureText(t).width/2, p.W-4-ctx.measureText(t).width/2), a.y+a.r+3);
      }
      ctx.textAlign="left";
    }
    function draw(){
      const n=p.nodes;
      ctx.clearRect(0,0,p.W,p.H);
      for(let i=1;i<n.length;i++){
        const b=n[i], on=!p.hover||p.hover===b||p.hover===p.centre;
        ctx.strokeStyle = p.hover&&(p.hover===b)?LINE_ON:(on?LINE:"#efece6");
        ctx.lineWidth = b.lw;
        ctx.beginPath(); ctx.moveTo(p.centre.x,p.centre.y); ctx.lineTo(b.x,b.y); ctx.stroke();
      }
      n.forEach(a=>{
        const r=a.r;
        ctx.beginPath();
        if(a.fact){ ctx.moveTo(a.x,a.y-r);ctx.lineTo(a.x+r,a.y);ctx.lineTo(a.x,a.y+r);ctx.lineTo(a.x-r,a.y);ctx.closePath(); }
        else ctx.arc(a.x,a.y,r,0,6.2832);
        ctx.fillStyle=a.col; ctx.fill();
        ctx.lineWidth=1.5; ctx.strokeStyle=BG; ctx.stroke();
        if(a===p.centre||a===p.hover){
          ctx.beginPath(); ctx.arc(a.x,a.y,r+3.5,0,6.2832);
          ctx.lineWidth=1.5; ctx.strokeStyle=ACCENT; ctx.stroke();
        }
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
    on(window,"hashchange",()=>teardown(p));

    active = p;
    reheat();
    return p;
  };
  window.localGraph.model = model;  // pure node-set builder, for tests
})();
