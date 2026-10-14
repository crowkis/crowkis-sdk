"""Emergencies, Hinglish place names, name structures and diagnoses (second re-review,
14 Oct 2026). The detectors work on the shape of a turn, so most turns here are new
sentences, not the review's examples. Same cases as node/test-voice-crisis-and-structures.js.
"""

import logging
import unittest

from crowkis.voice import _is_personal

from test_voice_stress_bugs import ANSWER, call, user


class CrisisAndStructureTests(unittest.TestCase):

    def assertKeptPrivate(self, said, *before):
        store, _, decisions, _ = call(*before, said)
        self.assertFalse(decisions[-1].cacheable, (before, said))
        self.assertTrue(all(said not in query for query, _, _ in store.writes), (said, store.writes))

    def assertShared(self, said, *before):
        store, _, decisions, _ = call(*before, said)
        self.assertTrue(decisions[-1].cacheable, said)
        self.assertIn((said, ANSWER, False), store.writes, said)

    def assertFollowsTheEmergency(self, turns):
        store, _, decisions, seen = call(*turns)
        self.assertIsNone(decisions[-1].messages, turns)
        self.assertFalse(decisions[-1].cacheable, turns)
        self.assertEqual(seen[-1][0], user(turns[0]), turns)
        self.assertTrue(all(t not in q for t in turns for q, _, _ in store.writes), (turns, store.writes))

    def test_an_emergency_in_any_of_the_callers_languages_is_private(self):
        for said in (
            # self-harm and suicide
            "i don't want to live anymore", "i cut myself again last night", "quiero morir ya",
            "no quiero vivir mas", "não quero mais viver", "je veux mourir", "main marna chahta hoon",
            "jeena nahi chahti ab", "my brother is suicidal", "she keeps hurting herself and harming herself",
            # poisoning and swallowing
            "mere bete ne kerosene pee liya", "my toddler drank bleach", "mi hijo tragó una pila",
            "meu filho bebeu cloro", "he took a whole strip of tablets", "she overdosed on sleeping pills",
            # injury and assault
            "bhai ka accident ho gaya", "my dad fell down the stairs", "mi madre se cayó y está sangrando",
            "papa ko chot lagi hai, khoon nikal raha hai", "my wife got burned on the stove",
            "i was mugged outside the station", "meu pai sofreu um acidente",
            # collapse, heart, stroke
            "papa behosh ho gaye", "my grandmother collapsed in the kitchen", "mi abuelo se desmayó",
            "mon père s'est évanoui", "he has chest pain and is sweating", "i think she is having a stroke",
            "dil ka daura pada hai", "he is not breathing properly",
        ):
            with self.subTest(said=said):
                self.assertTrue(_is_personal(said), said)
                self.assertKeptPrivate(said)

    def test_the_next_short_turns_after_an_emergency_follow_it(self):
        for turns in (
            ("mere bete ne kerosene pee liya", "ab kya karein"),
            ("bhai ka accident ho gaya", "kaunsa hospital paas mein hai"),
            ("mi hijo tragó una pila", "y ahora"),
            ("meu pai desmaiou", "e agora"),
            ("mon fils a avalé une pile", "et maintenant"),
            ("i don't want to live anymore", "is anyone there"),
            ("my dad fell down the stairs", "which hospital is closest", "what now"),
        ):
            with self.subTest(turns=turns):
                self.assertFollowsTheEmergency(turns)

    def test_generic_questions_with_emergency_words_stay_shared(self):
        for said in (
            "Does the travel plan cover accidents?",
            "Do you sell batteries for the remote?",
            "Is there a first aid kit at the venue?",
            "Do you have a live chat on the website?",
            "Is the hospital cafeteria open on Sundays?",
            "What is the price of the burn cream?",
        ):
            with self.subTest(said=said):
                self.assertShared(said)

    def test_hinglish_places_festivals_and_brands_are_not_people(self):
        for said in (
            "Durga Puja mein Kolkata mein delivery hoti hai?",
            "Chhath Puja pe Patna mein store khula hai?",
            "Karwa Chauth gift hampers available hain?",
            "Ganesh Chaturthi pe Mumbai mein offer hai kya?",
            "Hero Splendor on EMI milega?",
            "Royal Enfield ka service center Pune mein kahan hai?",
        ):
            with self.subTest(said=said):
                self.assertShared(said)

    def test_names_said_through_a_structure_in_lower_case_are_private(self):
        for said in (
            "booking sunita ke naam pe hai", "order vikas ke naam se hua tha", "anjali ka order kab aayega",
            "deepak ki booking confirm hai kya", "aqui é o joão", "sou a mariana, preciso de ajuda",
            "aqui é a ana falando", "can ramesh collect the parcel tomorrow", "could neha pick up my order",
            "nasci em 1987", "nací en 1990", "je suis amélie", "me llamo lucía",
        ):
            with self.subTest(said=said):
                self.assertTrue(_is_personal(said), said)
                self.assertKeptPrivate(said)

    def test_a_first_person_diagnosis_is_private_whatever_it_is_called(self):
        for said in (
            "i have lupus, can i fly", "i have crohns, is the meal plan ok", "tengo fibromialgia, puedo viajar",
            "tenho artrite, posso levar a bengala", "i was diagnosed with sarcoidosis last year",
            "i suffer from vertigo, which seat is best", "j'ai une endométriose",
        ):
            with self.subTest(said=said):
                self.assertTrue(_is_personal(said), said)
                self.assertKeptPrivate(said)
        for said in ("i have a question about the premium plan", "i have another question about delivery"):
            with self.subTest(said=said):
                self.assertFalse(_is_personal(said), said)


if __name__ == "__main__":
    logging.basicConfig()
    unittest.main()
