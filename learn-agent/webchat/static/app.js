/* app.js —— webchat 页面的大脑接线：把 /api/chat 的 SSE 流变成「气泡 + 动作日志 + 打字机」
 *
 * 分工：服务端一次把一条消息的完整一跑跑完（工具调用 + 回答），按 SSE 推两件事——
 *   type=log    → 活动日志一行，滚进 agent 气泡的「执行动作」区（agent 正在干什么）
 *   type=answer → 最终回答全文，页面逐字打字机打出
 */
(function () {
  "use strict";

  var chat = document.getElementById("chat");
  var welcome = document.getElementById("welcome");
  var input = document.getElementById("input");
  var sendBtn = document.getElementById("send");
  var newChatBtn = document.getElementById("newChat");

  var busy = false;

  /* ---------- 小工具 ---------- */
  function el(tag, cls, text) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text !== undefined) n.textContent = text;
    return n;
  }
  function scrollBottom() { chat.scrollTop = chat.scrollHeight; }
  function setBusy(on) {
    busy = on;
    sendBtn.disabled = on;
    input.disabled = on;
  }

  /* ---------- 渲染三件套 ---------- */
  function addUser(text) {
    var row = el("div", "row user");
    row.appendChild(el("div", "bubble", text));
    chat.appendChild(row);
    scrollBottom();
  }

  function beginAgentTurn() {
    var row = el("div", "row agent");
    row.appendChild(el("div", "avatar", "A"));
    var bubble = el("div", "bubble");
    bubble.appendChild(el("div", "status", "正在思考"));
    // 圆点正在思考动画（简单起见用单行文字 + 圆点）
    var status = bubble.firstChild;
    status.innerHTML = "";
    status.appendChild(el("span", "dot"));
    status.appendChild(el("span", "dot"));
    status.appendChild(el("span", "dot"));
    row.appendChild(bubble);
    chat.appendChild(row);
    scrollBottom();
    return { bubble: bubble, status: status, acts: null, answered: false };
  }

  function addLog(turn, text) {
    if (!turn.acts) {
      turn.acts = el("div", "acts");
      turn.acts.appendChild(el("div", "acts-title", "执行动作"));
      turn.bubble.appendChild(turn.acts);   // 正在思考的下方，最终回答之前
    }
    turn.acts.appendChild(el("div", "act", text));
    scrollBottom();
  }

  function showAnswer(turn, text, code) {
    turn.answered = true;
    if (turn.status.parentNode) turn.status.parentNode.removeChild(turn.status);
    var ans = el("div", "answer typing");
    turn.bubble.appendChild(ans);
    typeIt(ans, text, function () {
      ans.classList.remove("typing");
      if (code && code !== "END_TURN") {
        turn.bubble.appendChild(el("div", "code", "收尾：" + code));
      }
    });
  }

  function typeIt(node, text, done) {
    var i = 0;
    var tick = setInterval(function () {
      i += 1;
      node.textContent = text.slice(0, i);
      scrollBottom();
      if (i >= text.length) {
        clearInterval(tick);
        node.textContent = text;
        if (done) done();
      }
    }, 16);
  }

  /* ---------- SSE 流处理 ---------- */
  function handleEvent(chunk, turn) {
    chunk.split("\n").forEach(function (line) {
      if (line.indexOf("data:") !== 0) return;
      var raw = line.slice(5).trim();
      if (!raw) return;
      var ev;
      try { ev = JSON.parse(raw); } catch (e) { return; }
      if (ev.type === "log") {
        addLog(turn, ev.text);
      } else if (ev.type === "answer") {
        showAnswer(turn, ev.text, ev.code);
      }
    });
  }

  /* ---------- 发送 ---------- */
  async function send() {
    var msg = input.value.trim();
    if (!msg || busy) return;

    addUser(msg);
    if (welcome && !welcome.classList.contains("hidden")) welcome.classList.add("hidden");
    var turn = beginAgentTurn();
    setBusy(true);

    try {
      var resp = await fetch("/api/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message: msg }),
        credentials: "same-origin"
      });
      if (!resp.ok || !resp.body) throw new Error("服务端返回 HTTP " + resp.status);

      var reader = resp.body.getReader();
      var dec = new TextDecoder("utf-8");
      var buf = "";
      while (true) {
        var r = await reader.read();
        if (r.done) break;
        buf += dec.decode(r.value, { stream: true });
        var idx;
        while ((idx = buf.indexOf("\n\n")) >= 0) {        // SSE 事件以空行分隔
          var chunk = buf.slice(0, idx);
          buf = buf.slice(idx + 2);
          handleEvent(chunk, turn);
        }
      }
      if (!turn.answered) {
        turn.status.textContent = "（这轮没拿到回答）";
      }
    } catch (err) {
      console.error(err);
      if (turn.status.parentNode) {
        turn.status.textContent = "出错了：" + err.message;
      } else {
        turn.bubble.appendChild(el("div", "code", "出错了：" + err.message));
      }
    } finally {
      setBusy(false);
      input.value = "";
      autosize();
      input.focus();
    }
  }

  /* ---------- 输入区 ---------- */
  function autosize() {
    input.style.height = "auto";
    input.style.height = Math.min(input.scrollHeight, 160) + "px";
  }
  input.addEventListener("input", autosize);
  input.addEventListener("keydown", function (e) {
    if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); }
  });
  sendBtn.addEventListener("click", send);

  /* ---------- 新对话 ---------- */
  newChatBtn.addEventListener("click", async function () {
    if (busy) return;
    try { await fetch("/api/reset", { method: "POST", credentials: "same-origin" }); }
    catch (e) { console.warn("reset 失败", e); }
    Array.prototype.forEach.call(chat.querySelectorAll(".row"), function (n) { n.remove(); });
    if (welcome) welcome.classList.remove("hidden");
    input.value = "";
    input.focus();
  });

  /* ---------- 开场建议（点一下直接问） ---------- */
  var suggests = document.getElementById("suggests");
  if (suggests) {
    suggests.addEventListener("click", function (e) {
      var chip = e.target.closest(".chip");
      if (!chip) return;
      input.value = chip.textContent;
      send();
    });
  }

  input.focus();
})();
