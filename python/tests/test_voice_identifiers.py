"""A caller's identifiers never reach another caller (T1, 2026-10-21).

1. A turn carrying an IPv4 address is personal, as an IPv6 address, an IBAN, a PAN or a
   long digit run already was: "Is 203.0.113.42 blocked on your side?" was shared.
2. A shared answer that repeats an ID-like value this caller said earlier in the call
   (a digit run, a code, an email, an IP address) is kept to the call. Through the
   adapters a shareable turn's model only reads the question, so it cannot know such a
   value; this catches an app that sends the model the whole call anyway."""
import unittest

import crowkis
from crowkis.agent import _wait_for_audio_stores
from crowkis.voice import _is_personal, _wait_for_writes

from conformance import ConformanceStore


def _session():
    return crowkis.voice_session(client=ConformanceStore())


def _answer(session, question, reply):
    decision = session.answer(question, lambda m: reply)
    _wait_for_writes()
    _wait_for_audio_stores()
    return decision


class IPv4Tests(unittest.TestCase):
    def test_a_turn_with_an_ipv4_address_is_personal(self):
        for turn in ("Is 203.0.113.42 blocked on your side?",
                     "Why can't 203.0.113.42 reach the dashboard?",
                     "Unblock 10.0.0.5.",
                     "Whitelist 192.168.1.20 for the API please",
                     "203.0.113.42 kyun block hai?"):
            with self.subTest(turn=turn):
                self.assertTrue(_is_personal(turn))
                decision = _session().decide(turn)
                self.assertEqual(decision.action, "infer")
                self.assertIsNone(decision.messages, "the model reads the whole call; nothing is shared")

    def test_the_answer_to_it_is_never_saved(self):
        decision = _answer(_session(), "Is 203.0.113.42 blocked on your side?",
                           "Yes, 203.0.113.42 is blocked; unblocking takes an hour.")
        self.assertFalse(decision.stored)

    def test_must_still_work_questions_about_ip_addresses_in_general(self):
        for turn in ("How do I find my IP address?", "What is an IP address?",
                     "Do you support IPv6?", "Is version 2.3 supported?",
                     "Is the new plan 1.5 times faster?"):
            with self.subTest(turn=turn):
                self.assertFalse(_is_personal(turn))

    def test_must_still_work_not_an_address(self):
        # Five parts, or a part over 255: not an IPv4 address (other rules may still apply).
        from crowkis.voice import _IPV4
        for text in ("1.2.3.4.5", "256.1.1.1", "v1.2.3", "3.14", "203x0x113x42"):
            with self.subTest(text=text):
                self.assertIsNone(_IPV4.search(text))
        # An address next to a mask, a port, a label or the end of a sentence still counts.
        for text in ("10.0.0.1/24", "IP:10.0.0.1", "is it 10.0.0.1, or not", "blocked 10.0.0.1.", "10.0.0.1:8080"):
            with self.subTest(text=text):
                self.assertIsNotNone(_IPV4.search(text))


class RepeatedIdentifierTests(unittest.TestCase):
    """The model here is given a reply that repeats the caller's value, as a model that
    was sent the whole call might."""

    def _two_turns(self, first, reply, question="How long do refunds take?"):
        session = _session()
        _answer(session, first, "Okay, noted.")
        return _answer(session, question, reply)

    def test_an_answer_repeating_an_id_said_earlier_is_kept_to_the_call(self):
        for first, reply in (
                ("Send the refund to GB29NWBK60161331926819.", "Refunds go to GB29NWBK60161331926819 within five days."),
                ("Why was ABCPK4471M rejected?", "Refunds for ABCPK4471M take five days."),
                ("Aadhaar 2345 6789 0123 is not getting verified.", "Refunds linked to 234567890123 take five days."),
                ("Is 203.0.113.42 blocked on your side?", "Refunds take five days; 203.0.113.42 is unaffected."),
                ("My email is priya.sharma@example.com", "Refunds take five days; we'll write to priya.sharma@example.com."),
                ("Order 48213 never arrived.", "Refunds take five days, order 48213 included.")):
            with self.subTest(first=first):
                decision = self._two_turns(first, reply)
                self.assertFalse(decision.stored, decision.not_stored)
                self.assertIn("this caller said", decision.not_stored or "")

    def test_a_value_from_a_private_turn_counts_too(self):
        session = _session()
        session.record_private_turn("My PAN is ABCPK4471M", "Thanks, noted.")
        decision = _answer(session, "How long do refunds take?", "Refunds for ABCPK4471M take five days.")
        self.assertFalse(decision.stored)

    def test_must_still_work_an_answer_without_the_callers_values_is_shared(self):
        for first, reply in (
                ("Order 48213 never arrived.", "Refunds take five to seven days."),
                ("Order 48213 never arrived.", "Refunds from 2024 onwards take five days."),  # a year is not an ID
                ("Why was ABCPK4471M rejected?", "Refunds take 5 days, or 10 for 12345 orders."),
                ("Thanks a lot!", "Refunds take five days; call 1800 200 300.")):
            with self.subTest(first=first, reply=reply):
                decision = self._two_turns(first, reply)
                self.assertTrue(decision.stored, decision.not_stored)

    def test_must_still_work_the_question_itself_may_be_repeated(self):
        # Its number passed the personal rules, so the answer repeating it says nothing
        # private (review of the first version, which checked the current question too).
        decision = _answer(_session(), "Is the plan 1800 rupees a month?", "Yes, the plan is 1800 rupees a month.")
        self.assertTrue(decision.stored, decision.not_stored)

    def test_a_short_id_matches_whole_tokens_only(self):
        # "1800" said earlier is not inside "21,800"; it is caught when repeated as itself.
        self.assertTrue(self._two_turns("My extension is 1800, call me back.",
                                        "The yearly plan is 21,800 rupees.").stored)
        self.assertTrue(self._two_turns("Send the refund to GB29 NWBK 6016 1331 9268 19.",
                                        "Refunds of 16,016 rupees take five days.").stored)
        self.assertFalse(self._two_turns("My extension is 1800, call me back.",
                                         "Refunds take five days; we will call 1800.").stored)
        self.assertFalse(self._two_turns("Thanks, my PIN is 4471.", "Refunds take five days, PIN 4471.").stored)

    def test_must_still_work_a_first_turn_with_no_identifier(self):
        decision = _answer(_session(), "How long do refunds take?", "Refunds take five days.")
        self.assertTrue(decision.stored)


class PlaceholderTests(unittest.TestCase):
    """A cached answer the server scrubbed ("Write to pii_email_k3fa9 ...") is never
    spoken: it would read a placeholder aloud. The model answers instead (T1)."""

    def _decide(self, stored_answer, asked="How do I ask for a refund?"):
        store = ConformanceStore(seed={asked: stored_answer})
        return crowkis.voice_session(client=store).decide(asked)

    def test_a_cached_answer_with_a_pii_placeholder_is_not_spoken(self):
        for stored in ("Write to pii_email_k3fa9 and we refund you in five days.",
                       "Call pii_phone_a1b2c3 to get a refund.",
                       "Refunds go to PII_IBAN_9f8e7d within a week."):
            with self.subTest(stored=stored):
                decision = self._decide(stored)
                self.assertEqual(decision.action, "infer", decision.reason)
                self.assertIn("placeholder", decision.reason)

    def test_must_still_work_an_answer_about_pii_is_spoken(self):
        for stored in ("Our PII policy says we never keep your card number.",
                       "Refunds take five days; see pii_policy on our site."):
            with self.subTest(stored=stored):
                self.assertEqual(self._decide(stored).action, "serve")


if __name__ == "__main__":
    unittest.main()
