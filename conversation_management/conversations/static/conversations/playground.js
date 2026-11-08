/*
  Playground: a small chat client for the REST API (session login + CSRF token).
  Shows what each layer did: session (Redis), last turn (LangGraph),
  AI memory (checkpointer) and conversation (PostgreSQL).
*/
(() => {
  const $ = (id) => document.getElementById(id);
  const app = $("app");
  const maxTokens = Number(app.dataset.maxTokens);
  const list = $("conversation-list");
  const thread = $("thread");
  const banner = $("banner");
  const form = $("composer");
  const input = $("message");
  const sendButton = $("send");
  const deleteButton = $("delete-chat");
  let currentId = null;

  const RESOLUTION = {
    llm: "rewritten by the LLM",
    fallback: "joined with the previous question (LLM unavailable)",
    unchanged: "used as typed",
  };

  function csrfToken() {
    const match = document.cookie.match(/(?:^|; )csrftoken=([^;]+)/);
    return match ? decodeURIComponent(match[1]) : "";
  }

  async function api(method, path, body) {
    const response = await fetch(path, {
      method,
      credentials: "same-origin",
      headers: { "Content-Type": "application/json", "X-CSRFToken": csrfToken() },
      body: body ? JSON.stringify(body) : undefined,
    });
    const data = response.status === 204 ? null : await response.json().catch(() => null);
    return { ok: response.ok, status: response.status, data };
  }

  function el(tag, attrs = {}, ...children) {
    const node = document.createElement(tag);
    for (const [key, value] of Object.entries(attrs)) {
      if (key === "class") node.className = value;
      else node.setAttribute(key, value);
    }
    for (const child of children) node.append(child);
    return node;
  }

  function showBanner(text, isError = false) {
    banner.textContent = text;
    banner.className = `banner${isError ? " is-error" : ""}`;
    banner.hidden = !text;
  }

  function relative(iso) {
    const minutes = Math.round((Date.now() - new Date(iso)) / 60000);
    if (minutes < 1) return "just now";
    if (minutes < 60) return `${minutes} min ago`;
    const hours = Math.round(minutes / 60);
    return hours < 48 ? `${hours} h ago` : new Date(iso).toLocaleDateString();
  }

  function fillPanel(id, rows) {
    const panel = $(id);
    panel.replaceChildren();
    for (const [term, value] of rows) {
      panel.append(el("dt", {}, term));
      const dd = el("dd");
      if (value instanceof Node) dd.append(value);
      else dd.textContent = value ?? "–";
      panel.append(dd);
    }
  }

  const pill = (text, kind) => el("span", { class: `pill ${kind}` }, text);

  // ---- panels ------------------------------------------------------------
  async function refreshSession() {
    const { data } = await api("GET", "/api/v1/session/");
    if (!data || !data.active) {
      fillPanel("session-panel", [["Status", pill("none", "warn")], ["Note", "Expired or not started yet"]]);
      return data;
    }
    fillPanel("session-panel", [
      ["Status", pill("active", "no")],
      ["Session ID", data.session_id.slice(0, 12) + "…"],
      ["Active chat", data.active_conversation_id ? data.active_conversation_id.slice(0, 8) + "…" : "none"],
      ["Expires in", `${Math.round(data.expires_in_seconds / 60)} min`],
    ]);
    return data;
  }

  function renderTurn(memory) {
    const meter = el("div", { class: "meter" }, el("span", {
      class: memory.context_tokens > maxTokens * 0.8 ? "high" : "",
      style: `width:${Math.min(100, (memory.context_tokens / maxTokens) * 100)}%`,
    }));
    const tokens = el("div", {}, `${memory.context_tokens} / ${maxTokens} tokens`, meter);
    fillPanel("turn-panel", [
      ["Follow-up?", memory.is_follow_up ? pill("yes", "yes") : pill("no", "no")],
      ["Why", memory.follow_up_reasons.join("; ")],
      ["Searched as", memory.standalone_question],
      ["Resolution", RESOLUTION[memory.resolution] || memory.resolution],
      ["Context", tokens],
      ["Summarised", memory.summarized ? pill(`yes (${memory.summary_method})`, "warn") : "no"],
    ]);
  }

  async function refreshMemory(id) {
    if (!id) return fillPanel("memory-panel", [["Messages kept", "–"]]);
    const { data } = await api("GET", `/api/v1/conversations/${id}/memory/`);
    if (!data) return;
    fillPanel("memory-panel", [
      ["Messages kept", String(data.messages_in_memory)],
      ["Summary", data.summary || "none yet"],
    ]);
  }

  function renderConversationPanel(conversation) {
    if (!conversation) return fillPanel("conversation-panel", [["Status", "–"]]);
    fillPanel("conversation-panel", [
      ["Status", conversation.status === "active" ? pill("active", "no") : pill(conversation.status, "bad")],
      ["Messages", String(conversation.message_count)],
      ["Last activity", relative(conversation.last_activity_at)],
      ["Read-only from", new Date(conversation.expires_at).toLocaleString()],
    ]);
    $("chat-title").textContent = conversation.title || "New conversation";
    $("chat-meta").textContent = `ID ${conversation.id}`;
    deleteButton.hidden = false;
  }

  // ---- thread ------------------------------------------------------------
  function addMessage(message) {
    const bubble = el("li", { class: `bubble ${message.role}${message.status === "failed" ? " failed" : ""}` },
      el("span", { class: "seq" }, `#${message.sequence} ${message.role}${message.status === "failed" ? " · failed" : ""}`),
      message.content);
    thread.append(bubble);
    if (message.role === "user" && message.is_follow_up) {
      thread.append(el("li", { class: "rewrite" },
        el("b", {}, "Follow-up → searched as: "), `“${message.standalone_question}” `,
        el("span", {}, `(${RESOLUTION[message.resolution] || message.resolution})`)));
    }
  }

  function renderThread(messages) {
    thread.replaceChildren();
    if (!messages.length) {
      thread.append(el("li", { class: "empty-thread" }, "Ask a question, then ask a follow-up like “And for part-time staff?” to see it rewritten."));
    }
    messages.forEach(addMessage);
    thread.scrollTop = thread.scrollHeight;
  }

  // ---- conversations -----------------------------------------------------
  async function loadConversations() {
    const { data } = await api("GET", "/api/v1/conversations/");
    const items = data?.results || [];
    list.replaceChildren();
    if (!items.length) list.append(el("li", { class: "empty" }, "No conversations yet."));
    for (const c of items) {
      const button = el("button", { class: "conversation-item", type: "button", "aria-current": String(c.id === currentId) },
        el("strong", {}, c.title || "Untitled"),
        el("span", { class: c.status === "expired" ? "status-expired" : "" },
          `${c.status === "expired" ? "expired · " : ""}${c.message_count} messages · ${relative(c.last_activity_at)}`));
      button.addEventListener("click", () => openConversation(c.id));
      list.append(el("li", {}, button));
    }
  }

  async function openConversation(id) {
    currentId = id;
    showBanner("");
    const [detail, history] = await Promise.all([
      api("GET", `/api/v1/conversations/${id}/`),
      api("GET", `/api/v1/conversations/${id}/messages/`),
    ]);
    if (!detail.ok) return showBanner(detail.data?.detail || "Could not open the conversation.", true);
    renderConversationPanel(detail.data);
    renderThread(history.data?.results || []);
    if (detail.data.status === "expired") showBanner("This conversation has expired. You can read it, but new messages need a new conversation.");
    await Promise.all([refreshMemory(id), loadConversations(), refreshSession()]);
  }

  function startBlank() {
    currentId = null;
    $("chat-title").textContent = "New conversation";
    $("chat-meta").textContent = "Send a message to start.";
    deleteButton.hidden = true;
    renderThread([]);
    renderConversationPanel(null);
    refreshMemory(null);
    showBanner("");
  }

  // ---- actions -----------------------------------------------------------
  async function send(text) {
    showBanner("");
    sendButton.disabled = true;
    const pending = el("li", { class: "bubble assistant" }, "Checking the conversation memory…");
    thread.querySelector(".empty-thread")?.remove();
    thread.append(el("li", { class: "bubble user" }, text), pending);
    thread.scrollTop = thread.scrollHeight;

    const result = currentId
      ? await api("POST", `/api/v1/conversations/${currentId}/messages/`, { message: text })
      : await api("POST", "/api/v1/chat/", { message: text });
    sendButton.disabled = false;

    if (!result.ok) {
      pending.remove();
      thread.lastElementChild?.remove();
      const detail = result.data?.detail || Object.values(result.data || {}).flat().join(" ") || `Error ${result.status}`;
      showBanner(detail, true);
      if (currentId) await openConversation(currentId);
      return;
    }
    const turn = result.data;
    currentId = turn.conversation.id;
    await openConversation(currentId);
    renderTurn(turn.memory);
    if (turn.session.started_now) showBanner("A new session started (the previous one expired or this is your first message).");
  }

  form.addEventListener("submit", (event) => {
    event.preventDefault();
    const text = input.value.trim();
    if (!text) return input.focus();
    input.value = "";
    send(text);
  });
  input.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      form.requestSubmit();
    }
  });
  document.querySelectorAll("[data-suggest]").forEach((button) =>
    button.addEventListener("click", () => {
      input.value = button.dataset.suggest;
      input.focus();
    }),
  );
  $("new-chat").addEventListener("click", async () => {
    const { ok, data } = await api("POST", "/api/v1/conversations/", {});
    if (ok) await openConversation(data.id);
  });
  deleteButton.addEventListener("click", async () => {
    if (!currentId || !confirm("Delete this conversation and its AI memory? This cannot be undone.")) return;
    await api("DELETE", `/api/v1/conversations/${currentId}/`);
    startBlank();
    await Promise.all([loadConversations(), refreshSession()]);
  });

  // ---- start ---------------------------------------------------------------
  (async () => {
    const session = await refreshSession();
    if (session?.active && session.active_conversation_id) await openConversation(session.active_conversation_id);
    else startBlank();
    await loadConversations();
  })();
})();
