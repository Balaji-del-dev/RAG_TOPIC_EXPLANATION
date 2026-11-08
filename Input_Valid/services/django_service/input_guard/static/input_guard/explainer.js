/*
  "How it works" demo: a question travels through the five checkpoints.
  The example buttons replay real results recorded from the checks.
  "Check my question" calls the real API (/api/v1/validate-query).
*/
(() => {
  const examples = JSON.parse(document.getElementById("examples-data").textContent);
  const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  const STEP_DELAY = reduceMotion ? 0 : 420;

  const gates = [...document.querySelectorAll(".gate")];
  const passQuestion = document.getElementById("pass-question");
  const passOut = document.getElementById("pass-out");
  const passOutLabel = document.getElementById("pass-out-label");
  const stamp = document.getElementById("stamp");
  const stampMain = document.getElementById("stamp-main");
  const stampSub = document.getElementById("stamp-sub");
  const laneStatus = document.getElementById("lane-status");
  const tickets = [...document.querySelectorAll(".ticket")];
  const form = document.getElementById("own-form");
  const ownQuestion = document.getElementById("own-question");
  const ownHint = document.getElementById("own-hint");
  const checkButton = form.querySelector(".check-button");

  const LANGUAGES = {
    en: "English", fr: "French", de: "German", es: "Spanish", ta: "Tamil", hi: "Hindi", te: "Telugu",
    kn: "Kannada", ml: "Malayalam", ar: "Arabic", zh: "Chinese", ja: "Japanese", pt: "Portuguese",
    it: "Italian", nl: "Dutch", ru: "Russian", bn: "Bengali", mr: "Marathi", ur: "Urdu",
  };
  const ENTITIES = {
    EMAIL_ADDRESS: ["email address", "email addresses"], PHONE_NUMBER: ["phone number", "phone numbers"],
    PERSON: ["name", "names"], EMPLOYEE_ID: ["employee ID", "employee IDs"], CREDIT_CARD: ["card number", "card numbers"],
    IN_AADHAAR: ["Aadhaar number", "Aadhaar numbers"], IN_PAN: ["PAN number", "PAN numbers"],
    IBAN_CODE: ["bank account number", "bank account numbers"], IP_ADDRESS: ["IP address", "IP addresses"],
    US_SSN: ["SSN", "SSNs"],
  };
  const STATE_OF = { CONTINUE: "cleared", MASK: "masked", REDIRECT: "redirect", REJECT: "stopped", BLOCK: "stopped", ERROR: "failed" };
  const ICON = { cleared: "✓", masked: "✎", redirect: "↩", stopped: "✕", failed: "!", off: "–", notrun: "" };
  const STAMPS = {
    CONTINUE: ["Cleared", "Sent to the AI", "cleared"],
    MASK: ["Cleared", "Personal data hidden", "masked"],
    REDIRECT: ["Sent back", "Not an HR question", "redirect"],
    REJECT: ["Stopped", "Not a valid question", "stopped"],
    BLOCK: ["Stopped", "Never reaches the AI", "stopped"],
    ERROR: ["Check failed", "Stopped to be safe", "failed"],
  };

  const languageName = (code) => LANGUAGES[code] || code;
  const plural = (n, pair) => `${n} ${n === 1 ? pair[0] : pair[1]}`;
  const listing = (items) => items.length < 2 ? items.join("") : `${items.slice(0, -1).join(", ")} and ${items.at(-1)}`;
  const stepState = (step) => (step.skipped ? "off" : STATE_OF[step.decision] || "failed");

  /* A plain sentence for what happened at one checkpoint. */
  function gateNote(numbers, steps, allSteps) {
    const ran = steps.filter((s) => !s.skipped);
    const by = (n) => steps.find((s) => s.step === n);
    const stopping = ran.find((s) => ["stopped", "failed", "redirect"].includes(stepState(s)));

    if (stopping) {
      const d = stopping.details || {};
      if (stopping.decision === "ERROR") return "This checker is not working, so the question was stopped to be safe.";
      switch (stopping.step) {
        case 5: {
          const detected = allSteps.find((s) => s.step === 4)?.details?.language;
          return `Only ${listing((d.allowed_languages || ["en"]).map(languageName))} is allowed here. This looks like ${languageName(detected)}.`;
        }
        case 7: return "Company rules do not allow sharing this.";
        case 8: return "It tries to change the AI's own instructions.";
        case 9: return "It asks the AI to switch off its safety rules (a role-play trick).";
        case 10: {
          const kinds = (d.categories || []).map((c) => c.replace(/^S\d+\s*/, "").toLowerCase());
          return kinds.length ? `It asks for something harmful: ${listing(kinds)}.` : "It asks for something harmful.";
        }
        case 11: return "Not an HR question. The user gets a friendly note about what they can ask.";
        default: return stopping.reason || "The request is not valid.";
      }
    }

    const masked = ran.find((s) => s.decision === "MASK");
    if (masked) {
      const found = Object.entries(masked.details?.entities || {}).map(([type, n]) => plural(n, ENTITIES[type] || ["item", "items"]));
      return `Hid ${listing(found)}. The question goes on with labels instead.`;
    }

    if (!ran.length) return "Off on this server.";

    if (numbers.includes(3)) {
      const d = by(3)?.details || {};
      return d.nfkc_changed_text || d.invisible_chars_removed
        ? "Proper message. Look-alike or hidden letters were turned into normal ones."
        : "Proper message: right shape, right size, no hidden letters.";
    }
    if (numbers.includes(4)) {
      const d = by(4)?.details || {};
      if (d.reliable === false) return "Too short to tell the language, so it is allowed.";
      return `${languageName(d.language)} (${Math.round((d.confidence || 0) * 100)}% sure). Allowed.`;
    }
    if (numbers.includes(6)) {
      return by(7)?.skipped ? "No personal data found. (Company rules check is off here.)" : "No personal data found.";
    }
    if (numbers.includes(8)) {
      const setAside = by(8)?.details?.removed_before_scan || [];
      const harmOff = by(10)?.skipped;
      let note = harmOff ? "No tricks found. (Harm check is off here.)" : "No tricks, nothing harmful.";
      if (setAside.includes("self_correction")) note += " \"Ignore my previous question\" was set aside first.";
      return note;
    }
    if (numbers.includes(11)) {
      const topic = (by(11)?.details?.closest_topic || "").replace(/_/g, " ").replace(" and ", " & ");
      return topic ? `HR question, about ${topic}.` : "HR question.";
    }
    return "Passed.";
  }

  function gateState(steps) {
    const states = steps.map(stepState);
    for (const s of ["failed", "stopped", "redirect", "masked"]) if (states.includes(s)) return s;
    if (states.length && states.every((s) => s === "off")) return "off";
    return "cleared";
  }

  function setGate(gate, state, note) {
    gate.className = `gate is-${state}`;
    gate.querySelector(".gate-note").textContent = note;
    gate.querySelector(".gate-state").textContent = ICON[state] || "";
  }

  /* Show text with <EMAIL_ADDRESS>-style labels highlighted, without using innerHTML. */
  function showWithPlaceholders(element, text) {
    element.replaceChildren();
    for (const part of text.split(/(<[A-Z_]+>)/)) {
      if (!part) continue;
      if (/^<[A-Z_]+>$/.test(part)) {
        const mark = document.createElement("mark");
        mark.className = "placeholder";
        mark.textContent = part;
        element.append(mark);
      } else {
        element.append(document.createTextNode(part));
      }
    }
  }

  function resetLane(question) {
    passQuestion.textContent = question;
    passOutLabel.textContent = "The AI receives";
    passOut.textContent = "Checking…";
    stamp.hidden = true;
    stamp.classList.remove("is-landing");
    gates.forEach((gate) => setGate(gate, "notrun", "Waiting"));
    gates.forEach((gate) => (gate.className = "gate"));
    document.querySelectorAll(".dot").forEach((dot) => (dot.className = "dot"));
  }

  let runId = 0;
  const wait = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

  async function play(question, result) {
    const myRun = ++runId;
    resetLane(question);
    const steps = result.steps || [];

    if (!steps.length) {
      gates.forEach((gate) => setGate(gate, "notrun", "Step details are hidden on this server."));
    }

    let stopped = false;
    for (const gate of gates) {
      if (!steps.length) break;
      const numbers = gate.dataset.checks.split(",").map(Number);
      const gateSteps = steps.filter((s) => numbers.includes(s.step));

      if (stopped || !gateSteps.length) {
        setGate(gate, "notrun", "Not checked. The question was already stopped.");
        continue;
      }
      gate.classList.add("is-active");
      await wait(STEP_DELAY);
      if (myRun !== runId) return;

      const state = gateState(gateSteps);
      setGate(gate, state, gateNote(numbers, gateSteps, steps));
      for (const s of gateSteps) {
        const dot = gate.querySelector(`.dot[data-step="${s.step}"]`);
        if (dot) dot.className = `dot is-${stepState(s)}`;
      }
      if (["stopped", "failed", "redirect"].includes(state)) stopped = true;
    }

    await wait(STEP_DELAY / 2);
    if (myRun !== runId) return;

    const [main, sub, tone] = STAMPS[result.decision] || STAMPS.ERROR;
    stamp.style.setProperty("--tone", `var(--${tone})`);
    stampMain.textContent = main;
    stampSub.textContent = sub;
    stamp.hidden = false;
    if (!reduceMotion) stamp.classList.add("is-landing");

    if (result.allowed) {
      passOutLabel.textContent = "The AI receives";
      showWithPlaceholders(passOut, result.sanitized_query || question);
    } else {
      passOutLabel.textContent = "The user is told";
      passOut.textContent = result.message;
    }
    laneStatus.textContent = `${main}. ${sub}. ${result.message}`;
  }

  function selectTicket(ticket) {
    tickets.forEach((t) => t.setAttribute("aria-pressed", String(t === ticket)));
  }

  tickets.forEach((ticket) => {
    ticket.addEventListener("click", () => {
      const example = examples.find((e) => e.id === ticket.dataset.example);
      selectTicket(ticket);
      play(example.question, example.result);
    });
  });

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const question = ownQuestion.value;
    if (!question.trim()) {
      ownHint.textContent = "Type a question first.";
      ownHint.classList.add("is-error");
      ownQuestion.focus();
      return;
    }
    selectTicket(null);
    ++runId;
    resetLane(question);
    checkButton.disabled = true;
    ownHint.classList.remove("is-error");
    ownHint.textContent = "Checking with the real checks…";
    try {
      const response = await fetch(form.dataset.url, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ query: question }),
      });
      const result = await response.json();
      ownHint.textContent = "Done. These are real results from this server.";
      await play(question, result);
    } catch (error) {
      ownHint.textContent = "Could not reach the checks. Make sure the Django server is running, then try again.";
      ownHint.classList.add("is-error");
      passOut.textContent = "—";
    } finally {
      checkButton.disabled = false;
    }
  });

  /* Start with the first example so the page is never empty. */
  if (tickets.length) tickets[0].click();
})();

/*
  Check explorer: one lesson at a time. Opened from the side list, Previous / Next,
  or a check chip in the demo lane. #check-8 links work. Without JavaScript every
  lesson is simply shown one after another.
*/
(() => {
  const explorer = document.getElementById("explorer");
  if (!explorer) return;
  const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  const nav = explorer.querySelector(".explorer-nav");
  const lessons = [...explorer.querySelectorAll(".lesson")];
  const links = [...nav.querySelectorAll(".explorer-link")];
  explorer.classList.add("is-interactive");

  function open(number, { fromUser = false } = {}) {
    const lesson = lessons.find((l) => l.dataset.check === String(number)) || lessons[0];
    lessons.forEach((l) => l.classList.toggle("is-current", l === lesson));
    links.forEach((a) => a.setAttribute("aria-current", String(a.dataset.openCheck === lesson.dataset.check)));

    // keep the chosen check visible in the side list (horizontal on phones)
    const active = links.find((a) => a.dataset.openCheck === lesson.dataset.check);
    if (active && nav.scrollWidth > nav.clientWidth) nav.scrollTo({ left: active.offsetLeft - 12, behavior: "auto" });

    if (!fromUser) return;
    history.replaceState(null, "", `#check-${lesson.dataset.check}`);
    const top = explorer.getBoundingClientRect().top;
    if (top < 0 || top > window.innerHeight * 0.6) {
      explorer.scrollIntoView({ behavior: reduceMotion ? "auto" : "smooth", block: "start" });
    }
    lesson.querySelector("h3").focus({ preventScroll: true });
  }

  document.addEventListener("click", (event) => {
    const link = event.target.closest("[data-open-check]");
    if (!link) return;
    event.preventDefault();
    open(link.dataset.openCheck, { fromUser: true });
  });

  const fromHash = /^#check-(\d+)$/.exec(window.location.hash);
  open(fromHash ? fromHash[1] : 1);
})();
