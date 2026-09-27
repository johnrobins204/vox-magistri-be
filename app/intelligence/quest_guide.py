from dataclasses import dataclass


@dataclass(frozen=True)
class QuestGuide:
    """Boundary for future bounded quest guidance."""

    modes: tuple[str, ...] = ("Clarify", "Expand", "Connect", "Challenge")
