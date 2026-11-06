const { voiceSession } = require("@crowkis/client");
const { spawnSync } = require("child_process");
const TOK = process.env.CROWKIS_AUTH_TOKEN, kw = { host: "127.0.0.1", port: 7393, tenant: "voice" };
const dk = (a) => spawnSync("docker", [a, "crowkis-f9"]);
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const A = "Our store opens at nine in the morning and closes at six in the evening every day.";
async function turn(s, q) {
  const t = Date.now();
  try { const d = await s.decide(q); const r = d.needsModel || d.action === "infer" ? await s.record(d, A) : null;
    return `ok ${d.action} ${Date.now() - t}ms stored=${r && r.stored}`; }
  catch (e) { return `RAISED ${e.name}: ${String(e.message).slice(0, 80)}`; }
}
(async () => {
  console.log("1 wrong token:", await turn(voiceSession({ authToken: "wrong-token", ...kw }), "What time do you open on weekdays?"));
  const s = voiceSession({ authToken: TOK, ...kw });
  console.log("2a up:", await turn(s, "What time do you close on weekends?"));
  dk("stop"); console.log("2b stopped:", await turn(s, "Do you have parking at the store?"));
  console.log("2b stopped (new session):", await turn(voiceSession({ authToken: TOK, ...kw }), "Is there a cafe nearby the store?"));
  dk("start"); await sleep(8000);
  console.log("2c restarted, same session:", await turn(s, "Do you sell gift cards at the store?"));
  console.log("2c restarted, new session:", await turn(voiceSession({ authToken: TOK, ...kw }), "Can I return a gift card at the store?"));
  dk("pause"); console.log("3 hung server (paused):", await turn(voiceSession({ authToken: TOK, ...kw }), "Do you offer free wifi at the store?")); dk("unpause");
  await sleep(2000); console.log("3b after unpause:", await turn(voiceSession({ authToken: TOK, ...kw }), "Do you offer student discounts at the store?"));
  process.exit(0);
})();
