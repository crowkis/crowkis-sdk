"""v4 P2: TurnPairing alone (numbering, sharing offered per turn, barge-in, a late answer)."""
import unittest

from crowkis.runtime import TurnPairing


class TurnPairingTests(unittest.TestCase):
    def test_an_answer_to_the_latest_turn_carries_what_decide_offered(self):
        pairing = TurnPairing()
        turn = pairing.begin()
        pairing.start(0)
        pairing.offer(turn, True)
        self.assertEqual(pairing.settle(turn), (turn, True))
        self.assertFalse(pairing.open)

    def test_an_answer_to_an_older_turn_is_dropped(self):
        pairing = TurnPairing()
        old = pairing.begin()
        pairing.offer(old, True)
        pairing.begin()
        self.assertIsNone(pairing.settle(old))

    def test_a_newer_turns_offer_is_never_overwritten_by_an_older_one(self):
        pairing = TurnPairing()
        old = pairing.begin()
        new = pairing.begin()
        pairing.offer(new, False)
        pairing.offer(old, True)
        self.assertEqual(pairing.settle(new), (new, False))

    def test_a_barge_in_trims_the_open_turn_and_drops_its_answer(self):
        pairing = TurnPairing()
        turn = pairing.begin()
        pairing.start(3)
        trimmed = []
        self.assertTrue(pairing.cancel(trimmed.append))
        self.assertEqual(trimmed, [3])
        self.assertFalse(pairing.cancel(trimmed.append))
        self.assertTrue(pairing.moved_on(turn))
        self.assertIsNone(pairing.settle(turn))


if __name__ == "__main__":
    unittest.main()
