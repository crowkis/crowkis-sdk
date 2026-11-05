"use strict";

// Privacy fuzz: generated callers' details must never reach a shared save or a server key.
// The Node twin of python/tests/test_privacy_fuzz.py (same categories and sizes; its own
// seeded generator). Calls with names (three casings), phones (formats, in words), emails, ids,
// addresses, dates of birth, Hinglish, Devanagari, very long and blank turns run through
// voiceSession (decide + record), also with the chat profile. Every
// write to the stand-in server is searched for the detail raw, lowercase, digits-only and
// spelled out. A failure prints the seed, the case index and the leaked detail.
const assert = require("node:assert");
const { test } = require("node:test");
const { voiceSession, _waitForWrites: waitForWrites } = require("./src/channels/voiceSession.js");
const { LLMClassifier, LLMRewriter } = require("./src/understanding/model/understanders.js");
const { TurnFrame } = require("./src/understanding/model/frame.js");
const { ConformanceStore } = require("./test/conformance.js");

const SEED = 20261104;
const MIN_CONTROL_SAVES = 20; // of QUESTIONS.length general questions
const MIN_CONTROL_FRACTION = 0.4; // of the calls of a "stated earlier" category that must save once the detail is out of the answer
const NOTHING = "nothing"; // a category whose calls never save anything, by design

const FIRST = ["Rahul", "Priyanka", "Anjali", "Vikram", "Sunita", "Harpreet", "Deepak", "Meenakshi", "Tarun", "Kavitha"];
const LAST = ["Verma", "Sharma", "Deshpande", "Kulkarni", "Bhattacharya", "Iyer", "Chauhan", "Mehra"];
const DEV_NAMES = ["राहुल", "प्रिया", "अंजलि", "विक्रम", "सुनीता"];
const STREETS = ["Koregaon Park Lane", "Banjara Hills Road", "Salt Lake Avenue", "Indiranagar Cross", "Kalyan Nagar Street"];
const LETTERS = "BCDFGHJKLMNPQRSTVWXZ";
const WORDS = "zero one two three four five six seven eight nine".split(" ");
const DEV_DIGITS = "०१२३४५६७८९";
const MONTHS = "January February March April May June July August September October November December".split(" ");
const KINDS = { name: "person_name", phone: "contact", email: "contact", id: "id_number", address: "address", dob: "date_of_birth" };
const ALL_KINDS = Object.keys(KINDS);
const PHONE_STYLES = ["plain", "space", "dash", "dot", "paren", "plus91", "plus91dash"];
const GENERAL = { kind: "general", subject: "none", confidence: 0.9 };

const QUESTIONS = [
  ["what are your opening hours", "We are open from nine to six, Monday to Saturday."],
  ["what is the refund policy", "Refunds are accepted within seven days of delivery."],
  ["how do I reset my password", "Use the forgot password link on the sign in page."],
  ["do you ship internationally", "Yes, we ship to most countries."],
  ["which payment methods do you accept", "Cards, UPI and net banking are accepted."],
  ["how long does delivery take", "Delivery takes three to five working days."],
  ["do you have a mobile app", "Yes, it is on both major app stores."],
  ["can I change my delivery slot", "Slots can be changed up to a day before."],
  ["where is your head office", "Our head office is in Bengaluru."],
  ["is there a warranty on the products", "Every product has a one year warranty."],
  ["how do I contact support", "Use the help centre or the support line."],
  ["do you offer gift wrapping", "Gift wrapping is available at checkout."],
  ["what is your cancellation policy", "Orders can be cancelled before they ship."],
  ["are your products eco friendly", "Most packaging is recycled and recyclable."],
  ["do you have a loyalty programme", "Yes, members earn points on every purchase."],
  ["how can I track a parcel", "Tracking links are sent when a parcel ships."],
  ["what sizes do you stock", "We stock sizes small to extra large."],
  ["do you take bulk orders", "Bulk orders are welcome, ask our sales team."],
  ["can I pay on delivery", "Cash on delivery is available in many cities."],
  ["is the store open on sundays", "Stores are closed on Sundays."],
  ["how do I leave a review", "Reviews can be left from your order page."],
  ["do you repair damaged items", "We repair items under warranty for free."],
  ["what is the return window", "The return window is thirty days."],
  ["do you have student discounts", "Students get ten percent off with a valid card."],
  ["how do I update the app", "Update it from your phone's app store."],
  ["what languages does support speak", "Support speaks English and Hindi."],
  ["do you sell gift cards", "Gift cards come in several amounts."],
  ["can I pick up from the store", "Store pickup is ready in two hours."],
  ["what is the minimum order value", "There is no minimum order value."],
  ["how do I unsubscribe from emails", "Use the link at the bottom of any email."],
];
const HI_QUESTIONS = [
  ["aapka refund policy kya hai", "Refund saat din ke andar milta hai."],
  ["delivery mein kitna time lagta hai", "Delivery mein teen se paanch din lagte hain."],
  ["आपका रिफंड नियम क्या है", "रिफंड सात दिन के अंदर मिलता है।"],
];
const FILLER = "The weather has been quite warm this week and we have all been busy at work with the new schedule. " +
  "My neighbour was telling me about a shop that opened near the station and sells all kinds of things. ";

// -- the seeded generator (mulberry32 over a hash of the category) ---------------------------

function makeRng(category) {
  let h = 2166136261;
  for (const c of `${SEED}:${category}`) h = Math.imul(h ^ c.charCodeAt(0), 16777619) >>> 0;
  let a = h;
  const rng = () => {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
  rng.int = (lo, hi) => lo + Math.floor(rng() * (hi - lo + 1));
  rng.pick = (list) => list[Math.floor(rng() * list.length)];
  rng.digits = (n) => Array.from({ length: n }, () => rng.pick("0123456789")).join("");
  return rng;
}

function detail(kind, shown, texts = [], digits = [], said = shown) {
  return {
    kind, shown, said,
    texts: texts.filter((t) => t.length >= 3).map((t) => t.toLowerCase()),
    digits: digits.filter((d) => d.length >= 5),
  };
}
const styled = (rng, text) => rng.pick([text, text.toLowerCase(), text.toUpperCase()]);

const MAKERS = {
  name(rng, cased = false) {
    const [first, last] = [rng.pick(FIRST), rng.pick(LAST)];
    const full = `${first} ${last}`;
    return detail("name", cased ? rng.pick([full, full.toUpperCase()]) : styled(rng, full), [full, first]);
  },
  phone(rng, style = rng.pick([...PHONE_STYLES, "words"])) {
    const d = rng.pick("6789") + rng.digits(9);
    const shown = {
      plain: d, space: `${d.slice(0, 5)} ${d.slice(5)}`, dash: `${d.slice(0, 5)}-${d.slice(5)}`,
      dot: `${d.slice(0, 5)}.${d.slice(5)}`, paren: `(${d.slice(0, 3)}) ${d.slice(3, 6)}-${d.slice(6)}`,
      plus91: `+91 ${d.slice(0, 5)} ${d.slice(5)}`, plus91dash: `+91-${d}`,
      words: [...d].map((c) => WORDS[Number(c)]).join(" "),
    }[style];
    return detail("phone", shown, [shown], [d]);
  },
  email(rng) {
    const local = `${rng.pick(FIRST).toLowerCase()}.${rng.pick(LAST).toLowerCase()}${rng.int(10, 99)}`;
    return detail("email", styled(rng, `${local}@example.com`), [`${local}@example.com`, local]);
  },
  id(rng) {
    const style = rng.pick(["digits", "alnum", "dashed"]);
    const digits = rng.digits(rng.int(5, 8));
    const letters = rng.pick(LETTERS) + rng.pick(LETTERS);
    const shown = { digits, alnum: `${letters}${digits.slice(0, 5)}`, dashed: `${letters}-${digits.slice(0, 4)}-${rng.pick(LETTERS)}` }[style];
    return detail("id", shown, [shown], style === "digits" ? [digits] : style === "alnum" ? [digits.slice(0, 5)] : []);
  },
  address(rng) {
    const street = `${rng.int(2, 480)} ${rng.pick(STREETS)}`;
    const pin = rng.int(110000, 799999);
    return detail("address", `${street}, ${pin}`, [street], [String(pin)]);
  },
  dob(rng) {
    const [d, m, y] = [rng.int(10, 28), rng.int(10, 12), rng.int(1950, 2005)];
    const style = rng.pick(["long", "slash", "iso", "us"]);
    const shown = { long: `${d} ${MONTHS[m - 1]} ${y}`, slash: `${d}/${m}/${y}`, iso: `${y}-${m}-${d}`, us: `${MONTHS[m - 1]} ${d}, ${y}` }[style];
    return detail("dob", shown, [shown], style === "slash" ? [`${d}${m}${y}`] : style === "iso" ? [`${y}${m}${d}`] : []);
  },
};
function makeDevanagari(rng, kind) {
  if (kind === "name") {
    const name = rng.pick(DEV_NAMES);
    return detail("name", name, [name], [], `मेरा नाम ${name} है`);
  }
  const digits = rng.digits(rng.pick([5, 10]));
  const dev = [...digits].map((c) => DEV_DIGITS[Number(c)]).join("");
  return detail(kind, dev, [dev], [digits], `मेरा ${kind === "id" ? "ऑर्डर नंबर" : "फोन नंबर"} ${dev} है`);
}

const SAY = {
  name: ["my name is {}", "this is {} calling", "I am {}", "{} here", "{} this side", "{} speaking", "myself {}", "it's {}",
    "you're speaking with {}", "mera naam hai {}", "my first name is {}", "the name is {}", "hello, {} this side"],
  phone: ["my phone number is {}", "call me back on {}", "you can reach me at {}"],
  email: ["my email is {}", "send the invoice to {}", "{} is my email"],
  id: ["where is my order {}", "my account number is {}", "check booking {} for me"],
  address: ["I live at {}", "deliver it to {}", "my address is {}"],
  dob: ["my date of birth is {}", "I was born on {}", "my birthday is {}"],
};
const ANSWER = ["Sure, {}. That is noted.", "Thanks, I have {} on file and will help.", "Done for {}. Anything else?"];
const HINGLISH = {
  name: "mera naam {} hai", id: "mera order number {} hai", phone: "mera phone number {} hai",
  email: "meri email {} hai", address: "mera pata {} hai", dob: "meri janam tithi {} hai",
};
const fill = (template, value) => template.replace("{}", value);
const addressing = (answer, d) => `${answer.slice(0, -1)}, ${d.shown}.`; // the model addresses or quotes the caller

// -- looking for a detail in what was written ------------------------------------------------

// The digits in a blob, Devanagari and spelled-out ones included, as one run.
function stream(blob) {
  let s = blob.toLowerCase();
  [...DEV_DIGITS].forEach((c, i) => { s = s.split(c).join(String(i)); });
  s = s.replace(/[a-z]+/g, (w) => (WORDS.includes(w) ? String(WORDS.indexOf(w)) : " "));
  return s.replace(/\D/g, "");
}
function leaked(d, blobs) {
  const out = [];
  for (const blob of blobs) {
    const low = blob.toLowerCase();
    const digits = stream(blob);
    for (const n of d.texts) if (low.includes(n)) out.push([n, blob]);
    for (const n of d.digits) if (digits.includes(n)) out.push([n, blob]);
  }
  return out;
}
const asText = (v) => (Buffer.isBuffer(v) ? v.toString("utf8") : String(v));
function storeBlobs(store) {
  return [
    ...store.writes.map(([q, r]) => `${q} ${r}`),
    ...store.toolWrites.map(([k, v]) => `${JSON.stringify(k)} ${asText(v)}`),
    ...[...store.keys].map(([k, v]) => `${k} ${asText(v)}`),
  ];
}

async function playVoice(turns) {
  const store = new ConformanceStore();
  const session = voiceSession({ client: store, agentId: "fuzz" });
  try {
    for (const [say, answer] of turns) {
      const decision = await session.decide(say);
      if (decision.needsModel) await session.record(decision, answer);
    }
    await waitForWrites();
    await store.idle();
  } finally {
    await session.agent.close();
  }
  return store;
}

const personalFrame = (d) => ({ kind: "personal", subject: "self", confidence: 0.9, entities: [{ text: d.shown, type: KINDS[d.kind] }] });
const generalFrame = (text) => ({ ...GENERAL, question: text });

// -- cases ----------------------------------------------------------------------------------

const inQuestion = (rng, d) => [[fill(rng.pick(SAY[d.kind]), d.shown), fill(rng.pick(ANSWER), d.shown)]];
function statedEarlier(rng, d) {
  const [question, answer] = rng.pick(QUESTIONS);
  return [[fill(rng.pick(SAY[d.kind]), d.shown), "Noted."], [question, addressing(answer, d)]];
}
function longText(rng, d) {
  const sentences = Array.from({ length: rng.int(14, 20) }, () => FILLER);
  sentences.splice(rng.int(3, sentences.length - 3), 0, `By the way, ${fill(rng.pick(SAY[d.kind]), d.shown)}. `);
  return [[`${sentences.join("")}What is the refund policy?`, fill(rng.pick(ANSWER), d.shown)]];
}
// The same turns as a chat thread: the frames a good understanding model returns.
const asChat = (build) => (rng, d) => build(rng, d).map(([text, answer]) => {
  const isDetail = text.includes(d.shown) || text.includes(d.said) || d.texts.some((t) => text.toLowerCase().includes(t));
  return [text, isDetail ? personalFrame(d) : generalFrame(text), answer];
});

// Runs every case; fails with one line per leak (seed, case index, the detail, what was written).
// `saves` is for a "stated earlier" category, so it cannot go vacuous: the same calls with the detail left out of
// the model's answer (the control) must save in at least MIN_CONTROL_FRACTION of the cases, or, with NOTHING, must
// save nothing at all (and so must the call itself).
async function check(category, perKind, build, play, blobsOf, { kinds = ALL_KINDS, make, saves } = {}) {
  const rng = makeRng(category);
  const failures = [];
  let total = 0;
  let saved = 0;
  for (const kind of kinds) {
    for (let i = 0; i < perKind; i += 1) {
      const d = make ? make(rng, kind) : MAKERS[kind](rng);
      const turns = build(rng, d);
      const blobs = blobsOf(await play(turns));
      failures.push(...leaked(d, blobs).map(([n, b]) =>
        `seed=${SEED}:${category} case=${total} kind=${kind} detail=${JSON.stringify(n)} written=${JSON.stringify(b.slice(0, 120))}`));
      if (saves !== undefined) {
        const control = turns.map((t) => [...t.slice(0, -1), t[t.length - 1].split(`, ${d.shown}`).join("")]);
        const controlBlobs = blobsOf(await play(control));
        if (controlBlobs.length) saved += 1;
        if (saves === NOTHING) failures.push(...[...blobs, ...controlBlobs].map((b) => `seed=${SEED}:${category} case=${total} wrote ${JSON.stringify(b.slice(0, 80))}`));
      }
      total += 1;
    }
  }
  assert.deepStrictEqual(failures, [], `${failures.length} leaks in ${total} cases:\n${failures.slice(0, 10).join("\n")}`);
  if (saves !== undefined && saves !== NOTHING) {
    assert.ok(saved >= saves * total, `${category}: only ${saved} of ${total} control calls saved anything, so the leak search may be vacuous`);
  }
  return total;
}
const NO_NAME = ["phone", "email", "id", "address", "dob"];
const digitsPhone = (rng, kind) => (kind === "phone" ? MAKERS.phone(rng, rng.pick(PHONE_STYLES)) : MAKERS[kind](rng));

// voice

test("voice: detail in the question", async () => {
  assert.strictEqual(await check("v-in", 12, inQuestion, playVoice, storeBlobs), 72);
});
test("voice: detail stated earlier, then a general question", async () => {
  assert.strictEqual(await check("v-earlier", 12, statedEarlier, playVoice, storeBlobs, { kinds: NO_NAME, make: digitsPhone, saves: MIN_CONTROL_FRACTION }), 60);
});
test("voice: name stated earlier, then repeated by the model", async () => {
  assert.strictEqual(await check("v-name", 30, statedEarlier, playVoice, storeBlobs, { kinds: ["name"], saves: MIN_CONTROL_FRACTION }), 30);
});
test("voice: phone in words stated earlier, then repeated by the model", async () => {
  const words = (rng) => MAKERS.phone(rng, "words");
  assert.strictEqual(await check("v-words", 12, statedEarlier, playVoice, storeBlobs, { kinds: ["phone"], make: words, saves: MIN_CONTROL_FRACTION }), 12);
});
test("voice: Hinglish", async () => {
  const build = (rng, d) => {
    const [question, answer] = rng.pick(HI_QUESTIONS);
    const said = fill(HINGLISH[d.kind], d.shown);
    return rng() < 0.5 ? [[said, `Theek hai ${d.shown}.`]] : [[said, "Theek hai."], [question, addressing(answer, d)]];
  };
  assert.strictEqual(await check("v-hi", 6, build, playVoice, storeBlobs, { kinds: NO_NAME, make: digitsPhone }), 30);
});
test("voice: Hinglish name stated earlier", async () => {
  const build = (rng, d) => {
    const [question, answer] = rng.pick(HI_QUESTIONS);
    return [[fill(HINGLISH.name, d.shown), "Theek hai."], [question, addressing(answer, d)]];
  };
  await check("v-hi-name", 10, build, playVoice, storeBlobs, { kinds: ["name"], saves: MIN_CONTROL_FRACTION });
});
test("voice: Devanagari", async () => {
  const build = (rng, d) => {
    const [question, answer] = rng.pick(HI_QUESTIONS);
    return rng() < 0.5 ? [[d.said, `ठीक है ${d.shown}।`]] : [[d.said, "ठीक है।"], [question, addressing(answer, d)]];
  };
  assert.strictEqual(await check("v-dev", 15, build, playVoice, storeBlobs, { kinds: ["phone", "id"], make: makeDevanagari }), 30);
});
test("voice: Devanagari name stated earlier", async () => {
  // Known limit (open items L3 / VD7): Devanagari text always taints the call, so nothing is saved at all, whatever
  // the model says. That is the guarantee: the call, and the same call without the name in the answer, write nothing.
  const build = (rng, d) => {
    const [question, answer] = rng.pick(HI_QUESTIONS);
    return [[d.said, "ठीक है।"], [question, addressing(answer, d)]];
  };
  assert.strictEqual(await check("v-dev-name", 10, build, playVoice, storeBlobs, { kinds: ["name"], make: makeDevanagari, saves: NOTHING }), 10);
});
test("voice: long text with a buried detail", async () => {
  assert.strictEqual(await check("v-long", 5, longText, playVoice, storeBlobs), 30);
});
test("voice: blank turns are safe and write nothing", async () => {
  for (const say of ["", " ", "\n\t ", "     "]) {
    const store = await playVoice([[say, "Okay."], [say, ""]]);
    assert.deepStrictEqual(store.writes.filter((w) => !w[0].trim()), [], JSON.stringify(say));
  }
});
test("voice: controls, general questions are saved", async () => {
  let saved = 0;
  for (const q of QUESTIONS) saved += (await playVoice([q])).writes.length > 0 ? 1 : 0;
  assert.ok(saved >= MIN_CONTROL_SAVES, `only ${saved} of ${QUESTIONS.length} general answers were saved`);
});

// chat

// A weak understanding model: the turn with the detail gets frameOf(text), with no entities.
const asWeakChat = (build, frameOf) => (rng, d) => build(rng, d).map(([text, answer]) => {
  const isDetail = text.includes(d.shown) || text.includes(d.said) || d.texts.some((t) => text.toLowerCase().includes(t));
  return [text, isDetail ? frameOf(text) : generalFrame(text), answer];
});
// chat on the voice front end: voiceSession({ channel: "chat" }), with no LLM or a stub one that returns the turn's frame

async function playChatOnVoice(turns, llm) {
  const store = new ConformanceStore();
  const options = {};
  if (llm) {
    const frames = Object.fromEntries(turns.map(([t, f]) => [t, f]));
    const stub = { understand: (turn) => TurnFrame.fromDict(frames[turn]) };
    options.classifier = new LLMClassifier(stub);
    options.rewriter = new LLMRewriter(stub);
  }
  const session = voiceSession({ client: store, agentId: "fuzz", channel: "chat", ...options });
  try {
    for (const [text, , answer] of turns) {
      const decision = await session.decide(text);
      if (decision.needsModel) await session.record(decision, answer);
    }
    await waitForWrites();
    await store.idle();
  } finally {
    await session.agent.close();
  }
  return store;
}

async function modes(category, perKind, build, options) {
  for (const llm of [false, true]) {
    await check(`${category}-${llm}`, perKind, build, (turns) => playChatOnVoice(turns, llm), storeBlobs, options);
  }
}

test("chat on voice: detail in the question", async () => {
  await modes("cv-in", 12, asChat(inQuestion));
});
test("chat on voice: detail stated earlier, then a general question", async () => {
  await modes("cv-earlier", 12, asChat(statedEarlier), { kinds: NO_NAME, saves: MIN_CONTROL_FRACTION });
});
test("chat on voice: name stated earlier, then repeated by the model", async () => {
  await modes("cv-name", 30, asChat(statedEarlier), { kinds: ["name"], saves: MIN_CONTROL_FRACTION });
});
test("chat on voice: a weak understander, detail stated earlier", async () => {
  const noEntities = () => ({ kind: "personal", subject: "self", confidence: 0.9 });
  for (const [label, frameOf] of [["personal", noEntities], ["general", generalFrame]]) {
    await modes(`cv-weak-${label}`, 12, asWeakChat(statedEarlier, frameOf), { kinds: [...NO_NAME, "name"], saves: MIN_CONTROL_FRACTION });
  }
});
test("chat on voice: Hinglish and Devanagari", async () => {
  const build = (rng, d) => {
    const [question, answer] = rng.pick(HI_QUESTIONS);
    const said = d.said.includes("मेरा") ? d.said : fill(HINGLISH[d.kind], d.shown);
    return [[said, "Theek hai."], [question, addressing(answer, d)]];
  };
  const make = (rng, kind) => (rng() < 0.5 && (kind === "phone" || kind === "id") ? makeDevanagari(rng, kind) : MAKERS[kind](rng));
  await modes("cv-hi", 10, asChat(build), { kinds: ["phone", "email", "id"], make });
});
test("chat on voice: long text with a buried detail", async () => {
  await modes("cv-long", 5, asChat(longText));
});
test("chat on voice: blank turns are safe and write nothing", async () => {
  for (const say of ["", " ", "\n\t "]) {
    for (const llm of [false, true]) {
      const store = await playChatOnVoice([[say, { kind: "unclear", subject: "none", confidence: 0.5 }, "Okay."]], llm);
      assert.deepStrictEqual(store.writes.filter((w) => !w[0].trim()), [], JSON.stringify(say));
    }
  }
});
test("chat on voice: controls, general questions are saved", async () => {
  for (const llm of [false, true]) {
    let saved = 0;
    for (const [q, a] of QUESTIONS) saved += (await playChatOnVoice([[q, generalFrame(q), a]], llm)).writes.length > 0 ? 1 : 0;
    assert.ok(saved >= MIN_CONTROL_SAVES, `llm=${llm}: only ${saved} of ${QUESTIONS.length} general answers were saved`);
  }
});
