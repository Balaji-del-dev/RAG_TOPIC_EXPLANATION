/*
  "How it works" page:
  1. Scenario player: replays real recorded results and shows, for each step,
     what the 10 parts did and what the two kinds of memory hold.
  2. Part explorer: one lesson at a time (#part-N links work).
*/
(() => {
  const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  const $ = (id) => document.getElementById(id);
  const el = (tag, cls, ...children) => {
    const node = document.createElement(tag);
    if (cls) node.className = cls;
    children.forEach((child) => node.append(child));
    return node;
  };
  const cap = (name) => name.charAt(0).toUpperCase() + name.slice(1);

  // ---------------------------------------------------------------- player
  const scenarios = JSON.parse($("scenarios-data").textContent);
  const tabs = [...document.querySelectorAll(".scenario-tab")];
  const thread = $("thread");
  const steps = [...document.querySelectorAll(".step")];
  const nextButton = $("next-step");
  let scenario = null;
  let shown = 0;
  let playing = null;
  let lastTurn = null;

  const ok = (note) => ({ state: "ok", icon: "✓", note });
  const changed = (note) => ({ state: "changed", icon: "↻", note });
  const summary = (note) => ({ state: "summary", icon: "✎", note });
  const stopped = (note) => ({ state: "stopped", icon: "✕", note });
  const skip = (note) => ({ state: "skip", icon: "–", note });
  const idle = (note = "Not involved") => ({ state: "idle", icon: "", note });

  function stepsForTurn(e) {
    const m = e.memory;
    const who = cap(e.who);
    const s = {};
    s[1] = e.new_conversation ? ok("New conversation, new random uuid4 ID") : ok("Valid uuid4 ID");
    s[2] = e.session_started
      ? changed("No session in Redis: a new one starts")
      : ok("Session found in Redis: continue its active conversation");
    s[3] = e.new_conversation ? skip("Nothing earlier yet") : ok(`${e.transcript_messages - 2} earlier messages in this conversation`);
    s[4] = ok(`Question saved as #${e.user_sequence} (before the AI ran), answer as #${e.answer_sequence}`);
    s[5] = ok(e.new_conversation ? `${who} created it, so ${who} owns it` : `Belongs to ${who}`);
    s[6] = (m.summarized ? summary : ok)(`${m.context_tokens} / ${e.budget} tokens${m.summarized ? " after summarising" : ""}`);
    if (!m.is_follow_up) s[7] = skip("Not needed: the question stands alone");
    else if (m.resolution === "llm") s[7] = changed(`Rewritten: “${m.standalone_question}”`);
    else if (m.resolution === "fallback") s[7] = changed("Joined with the previous question (LLM unavailable)");
    else s[7] = ok("LLM confirmed it is already complete");
    s[8] = m.is_follow_up ? changed(`Yes: ${m.follow_up_reasons.join("; ")}`) : ok(`No: ${m.follow_up_reasons[0] || "it stands alone"}`);
    s[9] = m.summarized ? summary(`Older messages folded into the summary (${m.summary_method})`) : skip("Not needed: within the budget");
    s[10] = ok(`Session timer reset to ${e.session_minutes} min; conversation ${e.conversation_status}`);
    return s;
  }

  function stepsForRequest(e) {
    const s = {};
    for (let n = 1; n <= 10; n++) s[n] = idle();
    if (e.step !== 1) s[1] = ok("Valid uuid4 ID");
    if (e.step === 10 || e.step === 3) s[5] = ok(`Belongs to ${cap(e.who)}`);
    s[e.step] = e.status >= 400 ? stopped(`${e.status}: ${e.note}`) : ok(e.note);
    return s;
  }

  function stepsForEvent() {
    const s = {};
    for (let n = 1; n <= 10; n++) s[n] = idle("Nothing happens");
    if (scenario.id === "session") {
      s[2] = stopped("The session key is gone from Redis");
      s[10] = changed("Redis TTL ran out after 30 idle minutes");
    } else {
      s[10] = changed("Idle for longer than the conversation limit");
    }
    return s;
  }

  function showSteps(map, label) {
    $("inside-for").textContent = label ? `· ${label}` : "";
    steps.forEach((row) => {
      const info = map[row.dataset.step] || idle();
      row.className = `step is-${info.state}`;
      row.querySelector(".step-note").textContent = info.note;
      row.querySelector(".step-state").textContent = info.icon;
    });
  }

  function blocks(container, count, ai) {
    container.replaceChildren();
    container.className = `blocks${ai ? " ai" : ""}`;
    for (let i = 0; i < count; i++) container.append(el("i", i % 2 === 1 ? "answer" : ""));
  }

  function showMemory(e) {
    if (!e) return ($("memory-box").hidden = true);
    const m = e.memory;
    $("memory-box").hidden = false;
    blocks($("transcript-blocks"), e.transcript_messages, false);
    blocks($("memory-blocks"), e.messages_in_memory, true);
    $("transcript-count").textContent = `${e.transcript_messages} messages`;
    $("memory-count").textContent = `${e.messages_in_memory} messages`;
    const meter = $("token-meter");
    meter.style.width = `${Math.min(100, (m.context_tokens / e.budget) * 100)}%`;
    meter.className = m.context_tokens > e.budget * 0.8 ? "high" : "";
    $("token-count").textContent = `${m.context_tokens} / ${e.budget}`;
    const note = $("summary-note");
    note.hidden = !m.summary;
    note.replaceChildren(el("b", "", "Running summary"), m.summary || "");
  }

  function select(node, entry) {
    thread.querySelectorAll(".is-current").forEach((n) => n.classList.remove("is-current"));
    node.classList.add("is-current");
    if (entry.type === "turn") {
      lastTurn = entry;
      showSteps(stepsForTurn(entry), `“${entry.text}”`);
      showMemory(entry);
    } else if (entry.type === "request") {
      showSteps(stepsForRequest(entry), entry.label);
      showMemory(lastTurn);
    } else {
      showSteps(stepsForEvent(), "time passes");
      showMemory(lastTurn);
    }
  }

  function renderEntry(entry) {
    let anchor;
    if (entry.type === "turn") {
      anchor = el("li", "entry bubble user", el("small", "", `#${entry.user_sequence} ${cap(entry.who)}`), entry.text);
      thread.append(anchor);
      const m = entry.memory;
      if (m.is_follow_up && m.standalone_question !== entry.text) {
        thread.append(el("li", "rewrite", el("b", "", "Follow-up → searched as: "), `“${m.standalone_question}”`));
      }
      thread.append(el("li", "bubble answer", el("small", "", `#${entry.answer_sequence} assistant`), entry.answer));
    } else if (entry.type === "request") {
      anchor = el("li", `entry request ${entry.status >= 400 ? "bad" : "good"}`,
        el("span", "code", String(entry.status)), el("span", "who", cap(entry.who)), entry.label,
        el("span", "detail", entry.detail));
      thread.append(anchor);
    } else {
      anchor = el("li", "entry event", `⏱ ${entry.text}`);
      thread.append(anchor);
    }
    anchor.tabIndex = 0;
    anchor.addEventListener("click", () => select(anchor, entry));
    anchor.addEventListener("keydown", (event) => { if (event.key === "Enter") select(anchor, entry); });
    select(anchor, entry);
    thread.scrollTop = thread.scrollHeight;
  }

  function updateProgress() {
    const total = scenario.entries.length;
    $("progress").textContent = `Step ${shown} of ${total}`;
    nextButton.disabled = shown >= total;
    nextButton.textContent = shown >= total ? "Done" : shown === 0 ? "Start ▸" : "Next step ▸";
  }

  function next() {
    if (!scenario || shown >= scenario.entries.length) return;
    if (shown === 0) thread.replaceChildren();
    renderEntry(scenario.entries[shown]);
    shown += 1;
    updateProgress();
  }

  function stopPlaying() {
    if (playing) clearInterval(playing);
    playing = null;
  }

  function load(id) {
    stopPlaying();
    scenario = scenarios.find((s) => s.id === id) || scenarios[0];
    tabs.forEach((tab) => tab.setAttribute("aria-selected", String(tab.dataset.scenario === scenario.id)));
    $("scenario-intro").textContent = scenario.intro;
    shown = 0;
    lastTurn = null;
    thread.replaceChildren(el("li", "placeholder", "Press Start to replay this conversation step by step, or Play all."));
    showSteps({}, "");
    showMemory(null);
    updateProgress();
  }

  tabs.forEach((tab) => tab.addEventListener("click", () => load(tab.dataset.scenario)));
  nextButton.addEventListener("click", () => { stopPlaying(); next(); });
  $("restart").addEventListener("click", () => load(scenario.id));
  $("play-all").addEventListener("click", () => {
    stopPlaying();
    if (shown >= scenario.entries.length) load(scenario.id);
    if (reduceMotion) { while (shown < scenario.entries.length) next(); return; }
    next();
    playing = setInterval(() => (shown >= scenario.entries.length ? stopPlaying() : next()), 1100);
  });

  load(scenarios[0].id);
  next();  // show the first step so the page is never empty

  // -------------------------------------------------------------- explorer
  const explorer = $("explorer");
  const lessons = [...explorer.querySelectorAll(".lesson")];
  const links = [...explorer.querySelectorAll(".explorer-link")];
  const nav = explorer.querySelector(".explorer-nav");
  explorer.classList.add("is-interactive");

  function open(number, fromUser) {
    const lesson = lessons.find((l) => l.dataset.part === String(number)) || lessons[0];
    lessons.forEach((l) => l.classList.toggle("is-current", l === lesson));
    links.forEach((a) => a.setAttribute("aria-current", String(a.dataset.openPart === lesson.dataset.part)));
    const active = links.find((a) => a.dataset.openPart === lesson.dataset.part);
    if (active && nav.scrollWidth > nav.clientWidth) nav.scrollTo({ left: active.offsetLeft - 12 });
    if (!fromUser) return;
    history.replaceState(null, "", `#part-${lesson.dataset.part}`);
    const top = explorer.getBoundingClientRect().top;
    if (top < 0 || top > window.innerHeight * 0.6) explorer.scrollIntoView({ behavior: reduceMotion ? "auto" : "smooth", block: "start" });
    lesson.querySelector("h3").focus({ preventScroll: true });
  }

  document.addEventListener("click", (event) => {
    const link = event.target.closest("[data-open-part]");
    if (!link) return;
    event.preventDefault();
    open(link.dataset.openPart, true);
  });
  const fromHash = /^#part-(\d+)$/.exec(window.location.hash);
  open(fromHash ? fromHash[1] : 1, false);
})();
