/* force.js — 轻量力导向图（M4b 任务 6，零外部依赖，局域网无 CDN）。
 *
 * 数据：GET /api/v1/graph（同 cookie 鉴权）。渲染：canvas 2D。
 * 布局：斥力(Coulomb) + 弹簧(spring) + 向心重力，模拟冷却后停算；
 * 交互：滚轮缩放、空白拖拽平移、节点拖拽、单击节点看边证据、
 * 双击实体节点跳到 ?entity= 一跳展开。
 */
(function () {
  var cfg = window.CENHUA_GRAPH || {};
  var cv = document.getElementById('cv');
  var tip = document.getElementById('tip');
  var status = document.getElementById('status');
  if (!cv || !window.fetch) return;
  var ctx = cv.getContext('2d');
  var stage = document.getElementById('stage');

  var COL = {doc: '#2456d6', entity: '#8a93a5', hub: '#d97b16'};
  var W = 0, H = 0, DPR = window.devicePixelRatio || 1;
  var nodes = [], edges = [], byId = {};
  var view = {x: 0, y: 0, k: 1};              // 平移 + 缩放
  var alpha = 0, raf = null;
  var dragNode = null, panning = false, last = null, moved = 0;

  function resize() {
    W = stage.clientWidth; H = stage.clientHeight;
    cv.width = W * DPR; cv.height = H * DPR;
    ctx.setTransform(DPR, 0, 0, DPR, 0, 0);
  }
  window.addEventListener('resize', function () { resize(); draw(); });

  function load() {
    var url = '/api/v1/graph?max_nodes=' + (cfg.maxNodes || 80);
    if (cfg.entity) url += '&entity=' + encodeURIComponent(cfg.entity);
    status.textContent = '加载中…';
    fetch(url, {credentials: 'same-origin'}).then(function (r) {
      if (r.status === 401) { location.href = '/login'; throw new Error('401'); }
      return r.json();
    }).then(function (g) {
      if (g.error) { status.textContent = '错误：' + g.error; return; }
      byId = {};
      nodes = g.nodes.map(function (n, i) {
        var a = i * 2.399963;                  // 黄金角初始散布
        var o = {id: n.id, kind: n.kind, name: n.name, df: n.df,
                 hub: n.hub, tier: n.tier,
                 x: Math.cos(a) * (30 + 8 * Math.sqrt(i)),
                 y: Math.sin(a) * (30 + 8 * Math.sqrt(i)), vx: 0, vy: 0};
        byId[n.id] = o;
        return o;
      });
      edges = g.edges.filter(function (e) {
        return byId[e.from] && byId[e.to];
      }).map(function (e) {
        return {from: byId[e.from], to: byId[e.to], type: e.type,
                weight: e.weight || 0.1, source: e.source,
                evidence: e.evidence || ''};
      });
      status.textContent = '节点 ' + nodes.length + ' / 边 ' + edges.length +
        '（全库 ' + g.total_nodes + ' 节点' + (g.truncated ? '，已截断' : '') +
        ' · ts=' + (g.ts || 'n/a') + (g.center ? ' · 中心=' + g.center : '') + '）';
      alpha = 1;
      if (!raf) tick();
    }).catch(function () { status.textContent = '图谱数据加载失败'; });
  }

  function step() {
    var i, j, a, b, dx, dy, d2, d, f;
    for (i = 0; i < nodes.length; i++) {       // 斥力 O(n^2)，个人库规模够用
      for (j = i + 1; j < nodes.length; j++) {
        a = nodes[i]; b = nodes[j];
        dx = b.x - a.x; dy = b.y - a.y;
        d2 = dx * dx + dy * dy || 1;
        if (d2 > 90000) continue;              // 150px 外忽略
        f = 900 / d2;
        d = Math.sqrt(d2);
        a.vx -= dx / d * f; a.vy -= dy / d * f;
        b.vx += dx / d * f; b.vy += dy / d * f;
      }
    }
    for (i = 0; i < edges.length; i++) {       // 弹簧（强边短、弱边长）
      a = edges[i].from; b = edges[i].to;
      dx = b.x - a.x; dy = b.y - a.y;
      d = Math.sqrt(dx * dx + dy * dy) || 1;
      var rest = 90 - 40 * Math.min(1, edges[i].weight);
      f = (d - rest) * 0.02;
      a.vx += dx / d * f; a.vy += dy / d * f;
      b.vx -= dx / d * f; b.vy -= dy / d * f;
    }
    for (i = 0; i < nodes.length; i++) {       // 向心 + 阻尼 + 积分
      a = nodes[i];
      a.vx += -a.x * 0.004; a.vy += -a.y * 0.004;
      if (a !== dragNode) {
        a.vx *= 0.85; a.vy *= 0.85;
        a.x += a.vx * alpha * 3; a.y += a.vy * alpha * 3;
      } else { a.vx = 0; a.vy = 0; }
    }
    alpha *= 0.985;
  }

  function draw() {
    ctx.clearRect(0, 0, W, H);
    ctx.save();
    ctx.translate(W / 2 + view.x, H / 2 + view.y);
    ctx.scale(view.k, view.k);
    var i, e, a, b;
    ctx.lineWidth = 1 / view.k;
    for (i = 0; i < edges.length; i++) {
      e = edges[i]; a = e.from; b = e.to;
      ctx.strokeStyle = e.type === 'mentions' ? '#c9d4e8' :
        (e.source === 'manual' ? '#1a7f4b' : 'rgba(120,132,148,.5)');
      ctx.beginPath(); ctx.moveTo(a.x, a.y); ctx.lineTo(b.x, b.y); ctx.stroke();
      if (view.k > 0.7) {
        ctx.fillStyle = '#7a8494'; ctx.font = (10 / view.k) + 'px sans-serif';
        ctx.fillText(e.type, (a.x + b.x) / 2, (a.y + b.y) / 2);
      }
    }
    for (i = 0; i < nodes.length; i++) {
      a = nodes[i];
      var r = (a.kind === 'doc' ? 6 : 4) + Math.min(6, Math.sqrt(a.df));
      ctx.fillStyle = a.hub ? COL.hub : (a.kind === 'doc' ? COL.doc : COL.entity);
      ctx.beginPath(); ctx.arc(a.x, a.y, r, 0, 6.2832); ctx.fill();
      if (view.k > 0.5 || a.hub || a.kind === 'doc') {
        ctx.fillStyle = '#1c2330';
        ctx.font = (11 / view.k) + 'px sans-serif';
        ctx.fillText(a.name.length > 14 ? a.name.slice(0, 14) + '…' : a.name,
                     a.x + r + 2, a.y + 3);
      }
    }
    ctx.restore();
  }

  function tick() {
    raf = null;
    if (alpha > 0.02 || dragNode) { step(); draw(); raf = requestAnimationFrame(tick); }
    else draw();
  }

  function toWorld(px, py) {
    return {x: (px - W / 2 - view.x) / view.k, y: (py - H / 2 - view.y) / view.k};
  }
  function pick(px, py) {
    var p = toWorld(px, py), best = null, bd = 1e9;
    for (var i = 0; i < nodes.length; i++) {
      var n = nodes[i];
      var r = (n.kind === 'doc' ? 6 : 4) + Math.min(6, Math.sqrt(n.df)) + 3;
      var d = (n.x - p.x) * (n.x - p.x) + (n.y - p.y) * (n.y - p.y);
      if (d < r * r && d < bd) { bd = d; best = n; }
    }
    return best;
  }
  function evPos(ev) {
    var b = cv.getBoundingClientRect();
    return {x: ev.clientX - b.left, y: ev.clientY - b.top};
  }

  cv.addEventListener('mousedown', function (ev) {
    var p = evPos(ev);
    dragNode = pick(p.x, p.y);
    panning = !dragNode;
    last = p; moved = 0;
  });
  window.addEventListener('mousemove', function (ev) {
    var p = evPos(ev);
    if (dragNode) {
      var w = toWorld(p.x, p.y);
      dragNode.x = w.x; dragNode.y = w.y;
      moved++; alpha = Math.max(alpha, 0.3); if (!raf) tick();
    } else if (panning) {
      view.x += p.x - last.x; view.y += p.y - last.y;
      moved++; draw();
    } else if (tip) {
      var n = pick(p.x, p.y);
      if (n) {
        tip.hidden = false;
        tip.style.left = Math.min(W - 240, p.x + 14) + 'px';
        tip.style.top = (p.y + 14) + 'px';
        tip.textContent = n.name + ' · ' + (n.kind === 'doc' ? '文档' : '实体') +
          ' · df=' + n.df + (n.hub ? ' · 枢纽' : '') + ' · ' + n.tier;
      } else tip.hidden = true;
    }
    last = p;
  });
  window.addEventListener('mouseup', function (ev) {
    if (moved < 4 && dragNode) showDetail(dragNode);
    dragNode = null; panning = false;
  });
  cv.addEventListener('wheel', function (ev) {
    ev.preventDefault();
    var k = view.k * (ev.deltaY < 0 ? 1.12 : 0.89);
    view.k = Math.max(0.15, Math.min(6, k));
    draw();
  }, {passive: false});
  cv.addEventListener('dblclick', function (ev) {
    var p = evPos(ev), n = pick(p.x, p.y);
    if (n && n.kind === 'entity') {
      location.href = '/graph?entity=' + encodeURIComponent(n.name) +
        '&max_nodes=' + (cfg.maxNodes || 80);
    }
  });

  function showDetail(n) {
    var box = document.getElementById('detail');
    var title = document.getElementById('detail-title');
    var body = document.getElementById('detail-body');
    var lines = [];
    for (var i = 0; i < edges.length; i++) {
      var e = edges[i];
      if (e.from !== n && e.to !== n) continue;
      var other = e.from === n ? e.to : e.from;
      lines.push(e.from.name + ' —[' + e.type + ' · ' + e.weight.toFixed(2) +
        ' · ' + e.source + ']→ ' + other.name +
        (e.evidence ? '\n    ' + e.evidence : ''));
    }
    title.textContent = n.name + '（' + (n.kind === 'doc' ? '文档' : '实体') +
      ' · df=' + n.df + '）';
    body.textContent = lines.join('\n') || '（视图中无相邻边）';
    box.hidden = false;
  }

  resize();
  load();
})();
