/* joblog.js — SSE 进度订阅（M3b 任务 9 的浏览器端）。
 *
 * 用法：容器 <div id="log" data-job="ID" data-status-url="/api/v1/jobs/ID"></div>
 * 断线重连：EventSource 自动重连；按 data-cursor 带 ?cursor= 续订（幂等重放）。
 */
(function () {
  function attach(el) {
    var job = el.getAttribute('data-job');
    var base = el.getAttribute('data-status-url');
    if (!job || !base || el.getAttribute('data-bound')) return;
    el.setAttribute('data-bound', '1');
    if (!el.querySelector('pre')) {
      el.innerHTML = '<pre class="log"></pre><div class="jstate"></div>';
    }
    var pre = el.querySelector('pre');
    var state = el.querySelector('.jstate');
    pre.textContent = '';
    state.textContent = 'queued…';

    function subscribe(cursor) {
      var es = new EventSource(base + '?cursor=' + cursor);
      var settled = false;
      es.addEventListener('chunk', function (e) {
        var d = JSON.parse(e.data);
        pre.textContent += d.text + '\n';
        el.setAttribute('data-cursor', d.cursor + 1);
        pre.scrollTop = pre.scrollHeight;
      });
      es.addEventListener('progress', function (e) {
        var d = JSON.parse(e.data);
        state.textContent = d.state + ' ' + Math.round((d.progress || 0) * 100) + '%';
      });
      function finish(cls, label) {
        return function (e) {
          settled = true;
          try { state.textContent = label + (e.data ? ' ' + e.data : ''); } catch (x) {}
          state.className = 'jstate ' + cls;
          es.close();
        };
      }
      es.addEventListener('done', finish('ok', 'done'));
      es.addEventListener('failed', finish('bad', 'failed'));
      es.addEventListener('aborted', finish('bad', 'aborted'));
      es.onerror = function () {
        if (settled) return;
        es.close();
        state.textContent = 'disconnected — reconnecting…';
        setTimeout(function () {
          subscribe(parseInt(el.getAttribute('data-cursor') || '0', 10));
        }, 1500);
      };
    }
    subscribe(parseInt(el.getAttribute('data-cursor') || '0', 10));
  }
  window.cenhuaAttachJobLog = attach;
  document.addEventListener('DOMContentLoaded', function () {
    document.querySelectorAll('[data-job]').forEach(attach);
  });
  document.body.addEventListener('htmx:afterSwap', function (e) {
    (e.detail.target || e.target).querySelectorAll &&
      (e.detail.target || e.target).querySelectorAll('[data-job]').forEach(attach);
  });
})();
