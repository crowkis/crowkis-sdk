"""Privacy fuzz: generated callers' details must never reach a shared save or a server key.

Calls with names (three casings), phones (many formats and in words), emails, ids, addresses,
dates of birth, Hinglish, Devanagari, very long turns and blank turns run through
voice_session (decide + record) and Chat (a scripted understander, like test_chat.py).
Every write the SDK makes to a stand-in server is searched for the detail in its raw,
lowercase, digits-only and spelled-out forms. Generators use fixed seeds; a failure prints
the seed, the case index and the leaked detail. node/test-privacy-fuzz.js is the twin.
"""
import random
import re
import unittest

import crowkis
from conformance import ConformanceStore
from crowkis.channels.chat import Chat
from crowkis.channels.voice_session import _wait_for_writes
from test_chat import GENERAL, Model, Scripted, SegmentedAgent

SEED = 20261104
MIN_CONTROL_SAVES = 20  # of CONTROLS general questions

FIRST = ["Rahul", "Priyanka", "Anjali", "Vikram", "Sunita", "Harpreet", "Deepak", "Meenakshi", "Tarun", "Kavitha"]
LAST = ["Verma", "Sharma", "Deshpande", "Kulkarni", "Bhattacharya", "Iyer", "Chauhan", "Mehra"]
DEV_NAMES = ["राहुल", "प्रिया", "अंजलि", "विक्रम", "सुनीता"]
STREETS = ["Koregaon Park Lane", "Banjara Hills Road", "Salt Lake Avenue", "Indiranagar Cross", "Kalyan Nagar Street"]
LETTERS = "BCDFGHJKLMNPQRSTVWXZ"
WORDS = "zero one two three four five six seven eight nine".split()
DEV_DIGITS = "०१२३४५६७८९"
KINDS = {"name": "person_name", "phone": "contact", "email": "contact", "id": "id_number",
         "address": "address", "dob": "date_of_birth"}

QUESTIONS = [
    ("what are your opening hours", "We are open from nine to six, Monday to Saturday."),
    ("what is the refund policy", "Refunds are accepted within seven days of delivery."),
    ("how do I reset my password", "Use the forgot password link on the sign in page."),
    ("do you ship internationally", "Yes, we ship to most countries."),
    ("which payment methods do you accept", "Cards, UPI and net banking are accepted."),
    ("how long does delivery take", "Delivery takes three to five working days."),
    ("do you have a mobile app", "Yes, it is on both major app stores."),
    ("can I change my delivery slot", "Slots can be changed up to a day before."),
    ("where is your head office", "Our head office is in Bengaluru."),
    ("is there a warranty on the products", "Every product has a one year warranty."),
    ("how do I contact support", "Use the help centre or the support line."),
    ("do you offer gift wrapping", "Gift wrapping is available at checkout."),
    ("what is your cancellation policy", "Orders can be cancelled before they ship."),
    ("are your products eco friendly", "Most packaging is recycled and recyclable."),
    ("do you have a loyalty programme", "Yes, members earn points on every purchase."),
    ("how can I track a parcel", "Tracking links are sent when a parcel ships."),
    ("what sizes do you stock", "We stock sizes small to extra large."),
    ("do you take bulk orders", "Bulk orders are welcome, ask our sales team."),
    ("can I pay on delivery", "Cash on delivery is available in many cities."),
    ("is the store open on sundays", "Stores are closed on Sundays."),
    ("how do I leave a review", "Reviews can be left from your order page."),
    ("do you repair damaged items", "We repair items under warranty for free."),
    ("what is the return window", "The return window is thirty days."),
    ("do you have student discounts", "Students get ten percent off with a valid card."),
    ("how do I update the app", "Update it from your phone's app store."),
    ("what languages does support speak", "Support speaks English and Hindi."),
    ("do you sell gift cards", "Gift cards come in several amounts."),
    ("can I pick up from the store", "Store pickup is ready in two hours."),
    ("what is the minimum order value", "There is no minimum order value."),
    ("how do I unsubscribe from emails", "Use the link at the bottom of any email."),
]
HI_QUESTIONS = [("aapka refund policy kya hai", "Refund saat din ke andar milta hai."),
                ("delivery mein kitna time lagta hai", "Delivery mein teen se paanch din lagte hain."),
                ("आपका रिफंड नियम क्या है", "रिफंड सात दिन के अंदर मिलता है।")]
FILLER = ("The weather has been quite warm this week and we have all been busy at work with the new schedule. "
          "My neighbour was telling me about a shop that opened near the station and sells all kinds of things. ")


class Detail:
    def __init__(self, kind, shown, texts=(), digits=(), said=None):
        self.kind, self.shown = kind, shown
        self.texts = [t.lower() for t in texts if len(t) >= 3]
        self.digits = [d for d in digits if len(d) >= 5]
        self.said = said or shown


def _style(rng, text):
    return rng.choice([text, text.lower(), text.upper()])


def make_name(rng):
    first, last = rng.choice(FIRST), rng.choice(LAST)
    return Detail("name", _style(rng, f"{first} {last}"), [f"{first} {last}", first])


PHONE_STYLES = ["plain", "space", "dash", "dot", "paren", "plus91", "plus91dash"]


def make_phone(rng, style=None):
    d = rng.choice("6789") + "".join(rng.choice("0123456789") for _ in range(9))
    style = style or rng.choice(PHONE_STYLES + ["words"])
    shown = {"plain": d, "space": f"{d[:5]} {d[5:]}", "dash": f"{d[:5]}-{d[5:]}", "dot": f"{d[:5]}.{d[5:]}",
             "paren": f"({d[:3]}) {d[3:6]}-{d[6:]}", "plus91": f"+91 {d[:5]} {d[5:]}",
             "plus91dash": f"+91-{d}", "words": " ".join(WORDS[int(c)] for c in d)}[style]
    return Detail("phone", shown, [shown], [d])


def make_email(rng):
    first, last = rng.choice(FIRST).lower(), rng.choice(LAST).lower()
    local = f"{first}.{last}{rng.randint(10, 99)}"
    return Detail("email", _style(rng, f"{local}@example.com"), [f"{local}@example.com", local])


def make_id(rng):
    style = rng.choice(["digits", "alnum", "dashed"])
    digits = "".join(rng.choice("0123456789") for _ in range(rng.randint(5, 8)))
    letters = "".join(rng.choice(LETTERS) for _ in range(2))
    shown = {"digits": digits, "alnum": f"{letters}{digits[:5]}", "dashed": f"{letters}-{digits[:4]}-{rng.choice(LETTERS)}"}[style]
    return Detail("id", shown, [shown], [digits] if style == "digits" else [digits[:5]] if style == "alnum" else [])


def make_address(rng):
    house, pin = rng.randint(2, 480), rng.randint(110000, 799999)
    street = f"{house} {rng.choice(STREETS)}"
    return Detail("address", f"{street}, {pin}", [street], [str(pin)])


def make_dob(rng):
    d, m, y = rng.randint(10, 28), rng.randint(10, 12), rng.randint(1950, 2005)
    month = "January February March April May June July August September October November December".split()[m - 1]
    style = rng.choice(["long", "slash", "iso", "us"])
    shown = {"long": f"{d} {month} {y}", "slash": f"{d}/{m}/{y}", "iso": f"{y}-{m}-{d}", "us": f"{month} {d}, {y}"}[style]
    digits = [f"{d}{m}{y}"] if style == "slash" else [f"{y}{m}{d}"] if style == "iso" else []
    return Detail("dob", shown, [shown], digits)


MAKERS = {"name": make_name, "phone": make_phone, "email": make_email, "id": make_id,
          "address": make_address, "dob": make_dob}
SAY = {"name": ["my name is {}", "this is {} calling", "I am {}"],
       "phone": ["my phone number is {}", "call me back on {}", "you can reach me at {}"],
       "email": ["my email is {}", "send the invoice to {}", "{} is my email"],
       "id": ["where is my order {}", "my account number is {}", "check booking {} for me"],
       "address": ["I live at {}", "deliver it to {}", "my address is {}"],
       "dob": ["my date of birth is {}", "I was born on {}", "my birthday is {}"]}
ANSWER = ["Sure, {}. That is noted.", "Thanks, I have {} on file and will help.", "Done for {}. Anything else?"]
HINGLISH = {"name": "mera naam {} hai", "id": "mera order number {} hai", "phone": "mera phone number {} hai",
            "email": "meri email {} hai", "address": "mera pata {} hai", "dob": "meri janam tithi {} hai"}


def make_devanagari(rng, kind):
    if kind == "name":
        name = rng.choice(DEV_NAMES)
        return Detail("name", name, [name], said=f"मेरा नाम {name} है")
    digits = "".join(rng.choice("0123456789") for _ in range(rng.choice([5, 10])))
    dev = "".join(DEV_DIGITS[int(c)] for c in digits)
    label = "ऑर्डर नंबर" if kind == "id" else "फोन नंबर"
    return Detail(kind, dev, [dev], [digits], said=f"मेरा {label} {dev} है")


# -- looking for a detail in what was written --------------------------------------------------

def _stream(blob):
    """The digits in a blob, Devanagari and spelled-out ones included, as one run."""
    blob = blob.lower()
    for i, c in enumerate(DEV_DIGITS):
        blob = blob.replace(c, str(i))
    blob = re.sub(r"[a-z]+", lambda m: str(WORDS.index(m.group())) if m.group() in WORDS else " ", blob)
    return re.sub(r"\D", "", blob)


def leaked(detail, blobs):
    out = []
    for blob in blobs:
        low, stream = blob.lower(), _stream(blob)
        out += [(n, blob) for n in detail.texts if n in low]
        out += [(n, blob) for n in detail.digits if n in stream]
    return out


def store_blobs(store):
    blobs = [f"{q} {r}" for q, r, _ in store.writes]
    blobs += [f"{k} {v}" for k, v in store.tool_writes]
    blobs += [f"{k} {v.decode() if isinstance(v, bytes) else v}" for k, v in store.keys.items()]
    return blobs


def play_voice(turns):
    """One call through voice_session: decide each turn, record the model's answer."""
    store = ConformanceStore()
    session = crowkis.voice_session(client=store, agent_id="fuzz", voice=None)
    try:
        for say, answer in turns:
            decision = session.decide(say)
            if decision.needs_model:
                session.record(decision, answer)
        _wait_for_writes()
    finally:
        session.agent.close()
    return store


def chat_blobs(agent):
    return [f"{key} {answer}" for _, key, answer, _ in agent.saved]


def play_chat(turns):
    """One chat thread. ``turns``: (user text, the frame a good model returns, the model's answer)."""
    agent = SegmentedAgent()
    answers = iter(a for _, _, a in turns)
    chat = Chat(agent, Scripted({t: f for t, f, _ in turns}), system="You are Acme's assistant.")
    history = []
    for text, _, _ in turns:
        history.append({"role": "user", "content": text})
        reply = chat.turn("t", history, answer=Model(lambda m: next(answers)))
        history.append({"role": "assistant", "content": reply.text})
    return agent


def personal_frame(detail):
    return {"kind": "personal", "subject": "self", "confidence": 0.9,
            "entities": [{"text": detail.shown, "type": KINDS[detail.kind]}]}


def general_frame(text):
    return dict(GENERAL, question=text)


# -- cases ------------------------------------------------------------------------------------

def cases(category, n_per_kind, kinds=tuple(MAKERS)):
    """(index, detail) for each kind, from a generator seeded by the category."""
    rng = random.Random(f"{SEED}:{category}")
    for kind in kinds:
        for _ in range(n_per_kind):
            yield MAKERS[kind](rng), rng


def _said(detail, rng):
    return rng.choice(SAY[detail.kind]).format(detail.shown)


def _reply(detail, rng):
    return rng.choice(ANSWER).format(detail.shown)


def in_question(rng, detail):
    return [(_said(detail, rng), _reply(detail, rng))], None


def stated_earlier(rng, detail):
    question, answer = rng.choice(QUESTIONS)
    answer = answer[:-1] + f", {detail.shown}."  # the model addresses or quotes the caller
    return [(_said(detail, rng), "Noted."), (question, answer)], None


def long_text(rng, detail):
    sentences = [FILLER] * rng.randint(14, 20)
    sentences.insert(rng.randint(3, len(sentences) - 3), f"By the way, {_said(detail, rng)}. ")
    return [("".join(sentences) + "What is the refund policy?", _reply(detail, rng))], None


def digits_phone(rng, kind):
    """A detail maker without the spelled-out phone, which has its own test."""
    return make_phone(rng, rng.choice(PHONE_STYLES)) if kind == "phone" else MAKERS[kind](rng)


class Fuzz(unittest.TestCase):
    def check(self, category, n_per_kind, build, play, blobs_of, kinds=tuple(MAKERS), make=None):
        """Run every case; fail with one line per leak (seed, case index, the detail, what was written)."""
        failures, total = [], 0
        rng = random.Random(f"{SEED}:{category}")
        for index, (kind, i) in enumerate((k, i) for k in kinds for i in range(n_per_kind)):
            detail = make(rng, kind) if make else MAKERS[kind](rng)
            turns, _ = build(rng, detail)
            blobs = blobs_of(play(turns, detail))
            total += 1
            failures += [f"seed={SEED}:{category} case={index} kind={kind} detail={n!r} written={b[:120]!r}"
                         for n, b in leaked(detail, blobs)]
        self.assertGreaterEqual(total, 1)
        self.assertEqual(failures, [], f"{len(failures)} leaks in {total} cases:\n" + "\n".join(failures[:10]))
        return total

    # voice

    def voice(self, turns, detail):
        return play_voice(turns)

    def test_voice_detail_in_the_question(self):
        self.assertEqual(self.check("v-in", 12, in_question, self.voice, store_blobs), 72)

    def test_voice_detail_stated_earlier(self):
        self.assertEqual(self.check("v-earlier", 12, stated_earlier, self.voice, store_blobs,
                                    kinds=("phone", "email", "id", "address", "dob"), make=digits_phone), 60)

    def test_voice_phone_in_words_stated_earlier(self):
        words = lambda rng, kind: make_phone(rng, "words")
        self.assertEqual(self.check("v-words", 12, stated_earlier, self.voice, store_blobs, kinds=("phone",), make=words), 12)

    def test_voice_name_stated_earlier_then_repeated_by_the_model(self):
        self.assertEqual(self.check("v-name", 30, stated_earlier, self.voice, store_blobs, kinds=("name",)), 30)

    def test_voice_hinglish(self):
        def build(rng, detail):
            question, answer = rng.choice(HI_QUESTIONS)
            said = HINGLISH[detail.kind].format(detail.shown)
            if rng.random() < 0.5:
                return [(said, f"Theek hai {detail.shown}.")], None
            return [(said, "Theek hai."), (question, answer[:-1] + f", {detail.shown}.")], None
        self.assertEqual(self.check("v-hi", 6, build, self.voice, store_blobs, kinds=("phone", "email", "id", "address", "dob"),
                                    make=digits_phone), 30)

    def test_voice_hinglish_name_stated_earlier(self):
        def build(rng, detail):
            question, answer = rng.choice(HI_QUESTIONS)
            return [(HINGLISH["name"].format(detail.shown), "Theek hai."), (question, answer[:-1] + f", {detail.shown}.")], None
        self.check("v-hi-name", 10, build, self.voice, store_blobs, kinds=("name",))

    def test_voice_devanagari(self):
        def build(rng, detail):
            question, answer = rng.choice(HI_QUESTIONS)
            if rng.random() < 0.5:
                return [(detail.said, f"ठीक है {detail.shown}।")], None
            return [(detail.said, "ठीक है।"), (question, answer[:-1] + f", {detail.shown}.")], None
        self.assertEqual(self.check("v-dev", 15, build, self.voice, store_blobs, kinds=("phone", "id"),
                                    make=make_devanagari), 30)

    def test_voice_devanagari_name(self):
        def build(rng, detail):
            question, answer = rng.choice(HI_QUESTIONS)
            return [(detail.said, "ठीक है।"), (question, answer[:-1] + f", {detail.shown}.")], None
        self.check("v-dev-name", 10, build, self.voice, store_blobs, kinds=("name",), make=make_devanagari)

    def test_voice_long_text_with_a_buried_detail(self):
        self.assertEqual(self.check("v-long", 5, long_text, self.voice, store_blobs), 30)

    def test_voice_blank_turns_are_safe_and_write_nothing(self):
        for say in ["", " ", "\n\t ", "     "]:
            with self.subTest(say=repr(say)):
                store = play_voice([(say, "Okay."), (say, "")])
                self.assertEqual([w for w in store.writes if not w[0].strip()], [])

    def test_voice_controls_general_questions_are_saved(self):
        saved = sum(bool(play_voice([q]).writes) for q in QUESTIONS)
        self.assertGreaterEqual(saved, MIN_CONTROL_SAVES, f"only {saved} of {len(QUESTIONS)} general answers were saved")

    # chat

    def chat(self, turns, detail):
        return play_chat(turns)

    @staticmethod
    def as_chat(build):
        """The same turns as a chat thread: the frames a good understanding model returns."""
        def wrapped(rng, detail):
            turns, _ = build(rng, detail)
            out = []
            for text, answer in turns:
                is_detail = detail.shown in text or (detail.said in text) or any(t in text.lower() for t in detail.texts)
                out.append((text, personal_frame(detail) if is_detail else general_frame(text), answer))
            return out, None
        return wrapped

    def test_chat_detail_in_the_question(self):
        self.assertEqual(self.check("c-in", 12, self.as_chat(in_question), self.chat, chat_blobs), 72)

    def test_chat_detail_stated_earlier(self):
        self.assertEqual(self.check("c-earlier", 12, self.as_chat(stated_earlier), self.chat, chat_blobs,
                                    kinds=("phone", "email", "id", "address", "dob")), 60)

    def test_chat_name_stated_earlier_then_repeated_by_the_model(self):
        self.assertEqual(self.check("c-name", 30, self.as_chat(stated_earlier), self.chat, chat_blobs, kinds=("name",)), 30)

    def test_chat_hinglish_and_devanagari(self):
        def build(rng, detail):
            question, answer = rng.choice(HI_QUESTIONS)
            said = detail.said if "मेरा" in detail.said else HINGLISH[detail.kind].format(detail.shown)
            return [(said, "Theek hai."), (question, answer[:-1] + f", {detail.shown}.")], None
        def make(rng, kind):
            return make_devanagari(rng, kind) if rng.random() < 0.5 and kind in ("phone", "id") else MAKERS[kind](rng)
        self.assertEqual(self.check("c-hi", 10, self.as_chat(build), self.chat, chat_blobs,
                                    kinds=("phone", "email", "id"), make=make), 30)

    def test_chat_long_text_with_a_buried_detail(self):
        self.assertEqual(self.check("c-long", 5, self.as_chat(long_text), self.chat, chat_blobs), 30)

    def test_chat_blank_turns_are_safe_and_save_nothing(self):
        for say in ["", " ", "\n\t "]:
            with self.subTest(say=repr(say)):
                agent = play_chat([(say, {"kind": "unclear", "subject": "none", "confidence": 0.5}, "Okay.")])
                self.assertEqual(agent.saved, [])

    def test_chat_controls_general_questions_are_saved(self):
        saved = sum(bool(play_chat([(q, general_frame(q), a)]).saved) for q, a in QUESTIONS)
        self.assertGreaterEqual(saved, MIN_CONTROL_SAVES, f"only {saved} of {len(QUESTIONS)} general answers were saved")


if __name__ == "__main__":
    unittest.main()
