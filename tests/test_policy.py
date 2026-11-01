import unittest

from controller.v1.policy import design_batch, implementation_batch, should_ask
from controller.v1.types import Fork, Kind, Mode, Option


def fork(kind: Kind, **kwargs) -> Fork:
    return Fork(
        id=kwargs.pop("id", kind.value),
        topic=kwargs.pop("topic", kind.value),
        question="Which way?",
        kind=kind,
        options=(Option("a", "A"), Option("b", "B")),
        **kwargs,
    )


class PolicyTest(unittest.TestCase):
    def test_llm_mode_never_asks(self):
        self.assertFalse(should_ask(fork(Kind.ARCHITECTURE), Mode.LLM))

    def test_design_mode_asks_architecture_and_skips_placement(self):
        self.assertTrue(should_ask(fork(Kind.ARCHITECTURE), Mode.DESIGN))
        self.assertFalse(should_ask(fork(Kind.IMPLEMENTATION), Mode.DESIGN))

    def test_design_mode_skips_settled_and_non_pruning_forks(self):
        self.assertFalse(should_ask(fork(Kind.PRODUCT, settled_by="D001"), Mode.DESIGN))
        self.assertFalse(should_ask(fork(Kind.PRODUCT, prunes=False), Mode.DESIGN))

    def test_detailed_mode_asks_placement(self):
        self.assertTrue(should_ask(fork(Kind.IMPLEMENTATION), Mode.DETAILED))

    def test_design_batch_caps_at_three(self):
        forks = [fork(Kind.ARCHITECTURE, id=f"d{i}", topic=f"t{i}") for i in range(5)]
        self.assertEqual(len(design_batch(forks, Mode.DESIGN)), 3)

    def test_placement_batch_follows_the_design_answer(self):
        design = fork(Kind.ARCHITECTURE, id="deletion", topic="deletion")
        stay = fork(
            Kind.IMPLEMENTATION,
            id="where-hard",
            depends_on="deletion",
            requires_option="hard-delete",
        )
        drop = fork(
            Kind.IMPLEMENTATION,
            id="where-soft",
            depends_on="deletion",
            requires_option="soft-delete",
        )
        batch = implementation_batch([design, stay, drop], Mode.DETAILED, {"deletion": "hard-delete"})
        self.assertEqual([item.id for item in batch], ["where-hard"])


if __name__ == "__main__":
    unittest.main()
