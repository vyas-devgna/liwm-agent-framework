"""The zero-memory gate, including the direction it is allowed to be wrong in."""

import unittest

import helpers  # noqa: F401  -- puts src/ on sys.path

from liwm.gate import gate_decision, needs_memory


class TestSelfContained(unittest.TestCase):
    SKIP = [
        "what is 17% of 340",
        "what is 2 + 2",
        "convert 5 km to miles",
        "how many bytes in 4 gb",
        "what is the capital of France",
        "who is Ada Lovelace",
        "base64 encode this string please",
        "give me a sha256 of that literal",
    ]

    def test_self_contained_requests_get_no_memory(self):
        for task in self.SKIP:
            with self.subTest(task=task):
                decision = gate_decision(task)
                self.assertFalse(decision["needs_memory"], decision["reason"])
                self.assertTrue(decision["self_contained_signals"])


class TestNeedsMemory(unittest.TestCase):
    NEED = [
        "write the release notes",
        "draft an email to the team",
        "use the usual package manager",
        "same as last time please",
        "should I use pnpm or npm",
        "which library is better for this",
        "continue where we left off",
        "you said earlier that this was fine",
        "refactor this function",
        "review my approach",
        "ship this to production",
        "name this variable",
        "compare the three options for the cache layer",
        "postgres versus sqlite here",
        "what are the alternatives",
    ]

    def test_requests_that_depend_on_history_retrieve(self):
        for task in self.NEED:
            with self.subTest(task=task):
                self.assertTrue(needs_memory(task), task)


class TestSituatedQuestions(unittest.TestCase):
    """A question about a thing in front of the agent is not general knowledge.

    "What is wrong with this function" parses exactly like "what is a monad",
    and the first version of this gate skipped memory for both. That is the
    expensive direction to be wrong in: the answer quietly gets worse and
    nothing in the transcript says why.
    """

    SITUATED = [
        "what is the best way to structure this module",
        "what is wrong with this function",
        "who is responsible for this file",
        "what is causing the test to fail",
        "what is the type of this variable",
        "what is our deploy process",
        "how should we handle retries",
        "what is the right approach here",
        "what changed in these lines",
    ]

    GENERAL = [
        "what is a monad",
        "what is the capital of France",
        "what is the syntax for a python decorator",
        "convert 5 km to miles",
        "what is 17% of 340",
    ]

    def test_situated_questions_retrieve(self):
        for task in self.SITUATED:
            with self.subTest(task=task):
                self.assertTrue(needs_memory(task), task)

    def test_general_knowledge_still_skips(self):
        """The correction must not swallow the cases the gate exists for."""
        for task in self.GENERAL:
            with self.subTest(task=task):
                self.assertFalse(needs_memory(task), task)


class TestConservatism(unittest.TestCase):
    """The gate's errors are asymmetric and it is built to fail toward retrieval."""

    def test_no_task_hint_retrieves(self):
        decision = gate_decision(None)
        self.assertTrue(decision["needs_memory"])
        self.assertEqual(decision["reason"], "no_task_hint")

    def test_empty_string_retrieves(self):
        self.assertTrue(needs_memory(""))

    def test_unrecognised_request_retrieves(self):
        self.assertTrue(needs_memory("frobnicate the widget cluster"))

    def test_need_beats_self_containment(self):
        """A calculation about prior work is still about prior work."""
        decision = gate_decision("what is 2 + 2, same as last time")
        self.assertTrue(decision["needs_memory"])
        self.assertTrue(decision["self_contained_signals"])
        self.assertIn("unresolved_reference", decision["signals"])

    def test_a_scoped_request_is_situated(self):
        self.assertTrue(needs_memory("what is 2 + 2", project_id="acme"))
        self.assertTrue(needs_memory("what is 2 + 2", domain="finance"))

    def test_one_word_fragments_are_not_self_contained(self):
        self.assertTrue(needs_memory("hex?"))


class TestOverride(unittest.TestCase):
    def test_override_is_recorded_as_an_override(self):
        for force, expected in (("on", True), ("off", False)):
            decision = gate_decision("what is 2 + 2", force=force)
            self.assertEqual(decision["needs_memory"], expected)
            self.assertTrue(decision["overridden"])
            self.assertEqual(decision["reason"], "explicit_override")

    def test_rules_are_not_credited_for_an_override(self):
        decision = gate_decision("write the release notes", force="off")
        self.assertFalse(decision["needs_memory"])
        self.assertEqual(decision["signals"], [])


if __name__ == "__main__":
    unittest.main()
