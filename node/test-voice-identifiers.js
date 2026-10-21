"use strict";
// A caller's identifiers never reach another caller (T1, 2026-10-21).
// Mirrors python/tests/test_voice_identifiers.py.
const assert = require("node:assert");
const { test, beforeEach } = require("node:test");
const { voiceSession, _isPersonal: isPersonal, _waitForWrites: waitForWrites, _IPV4: IPV4 } = require("./voice.js");
const { waitForAudioStores } = require("./agent.js");
const { ConformanceStore } = require("./conformance.js");

beforeEach(() => waitForAudioStores());

const session = () => voiceSession({ client: new ConformanceStore() });

async function answer(s, question, reply) {
  const decision = await s.answer(question, async () => reply);
  await waitForWrites();
  await waitForAudioStores();
  return decision;
}

test("a turn with an IPv4 address is personal", async () => {
  for (const turn of ["Is 203.0.113.42 blocked on your side?", "Why can't 203.0.113.42 reach the dashboard?",
    "Unblock 10.0.0.5.", "Whitelist 192.168.1.20 for the API please", "203.0.113.42 kyun block hai?"]) {
    assert.strictEqual(isPersonal(turn), true, turn);
    const decision = await session().decide(turn);
    assert.strictEqual(decision.action, "infer", turn);
    assert.strictEqual(decision.messages, null, `${turn}: the model reads the whole call`);
  }
});

test("the answer to it is never saved", async () => {
  const decision = await answer(session(), "Is 203.0.113.42 blocked on your side?",
    "Yes, 203.0.113.42 is blocked; unblocking takes an hour.");
  assert.strictEqual(decision.stored, false);
});

test("must still work: questions about IP addresses in general", () => {
  for (const turn of ["How do I find my IP address?", "What is an IP address?", "Do you support IPv6?",
    "Is version 2.3 supported?", "Is the new plan 1.5 times faster?"]) {
    assert.strictEqual(isPersonal(turn), false, turn);
  }
});

test("must still work: not an address", () => {
  for (const text of ["1.2.3.4.5", "256.1.1.1", "v1.2.3", "3.14", "203x0x113x42"]) assert.strictEqual(IPV4.test(text), false, text);
  // An address next to a mask, a port, a label or the end of a sentence still counts.
  for (const text of ["10.0.0.1/24", "IP:10.0.0.1", "is it 10.0.0.1, or not", "blocked 10.0.0.1.", "10.0.0.1:8080"]) {
    assert.strictEqual(IPV4.test(text), true, text);
  }
});

async function twoTurns(first, reply, question = "How long do refunds take?") {
  const s = session();
  await answer(s, first, "Okay, noted.");
  return answer(s, question, reply);
}

test("an answer repeating an ID said earlier is kept to the call", async () => {
  for (const [first, reply] of [
    ["Send the refund to GB29NWBK60161331926819.", "Refunds go to GB29NWBK60161331926819 within five days."],
    ["Why was ABCPK4471M rejected?", "Refunds for ABCPK4471M take five days."],
    ["Aadhaar 2345 6789 0123 is not getting verified.", "Refunds linked to 234567890123 take five days."],
    ["Is 203.0.113.42 blocked on your side?", "Refunds take five days; 203.0.113.42 is unaffected."],
    ["My email is priya.sharma@example.com", "Refunds take five days; we'll write to priya.sharma@example.com."],
    ["Order 48213 never arrived.", "Refunds take five days, order 48213 included."]]) {
    const decision = await twoTurns(first, reply);
    assert.strictEqual(decision.stored, false, `${first}: ${decision.notStored}`);
    assert.match(decision.notStored || "", /this caller said/, first);
  }
});

test("a value from a private turn counts too", async () => {
  const s = session();
  s.recordPrivateTurn("My PAN is ABCPK4471M", "Thanks, noted.");
  const decision = await answer(s, "How long do refunds take?", "Refunds for ABCPK4471M take five days.");
  assert.strictEqual(decision.stored, false);
});

test("must still work: an answer without the caller's values is shared", async () => {
  for (const [first, reply] of [
    ["Order 48213 never arrived.", "Refunds take five to seven days."],
    ["Order 48213 never arrived.", "Refunds from 2024 onwards take five days."], // a year is not an ID
    ["Why was ABCPK4471M rejected?", "Refunds take 5 days, or 10 for 12345 orders."],
    ["Thanks a lot!", "Refunds take five days; call 1800 200 300."]]) {
    const decision = await twoTurns(first, reply);
    assert.strictEqual(decision.stored, true, `${first} / ${reply}: ${decision.notStored}`);
  }
});

test("must still work: the question itself may be repeated", async () => {
  // Its number passed the personal rules, so the answer repeating it says nothing private.
  const decision = await answer(session(), "Is the plan 1800 rupees a month?", "Yes, the plan is 1800 rupees a month.");
  assert.strictEqual(decision.stored, true, decision.notStored);
});

test("a short ID matches whole tokens only", async () => {
  // "1800" said earlier is not inside "21,800"; it is caught when repeated as itself.
  assert.strictEqual((await twoTurns("My extension is 1800, call me back.", "The yearly plan is 21,800 rupees.")).stored, true);
  assert.strictEqual((await twoTurns("Send the refund to GB29 NWBK 6016 1331 9268 19.",
    "Refunds of 16,016 rupees take five days.")).stored, true);
  assert.strictEqual((await twoTurns("My extension is 1800, call me back.",
    "Refunds take five days; we will call 1800.")).stored, false);
  assert.strictEqual((await twoTurns("Thanks, my PIN is 4471.", "Refunds take five days, PIN 4471.")).stored, false);
});

test("must still work: a first turn with no identifier", async () => {
  const decision = await answer(session(), "How long do refunds take?", "Refunds take five days.");
  assert.strictEqual(decision.stored, true);
});
