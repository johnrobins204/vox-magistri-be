from dataclasses import dataclass, field

WORLD_GUIDANCE_MODES = ("Clarify", "Expand", "Connect", "Challenge")


@dataclass(frozen=True)
class CampaignContext:
    campaign_name: str
    campaign_summary: str = ""
    characters: list[str] = field(default_factory=list)
    locations: list[str] = field(default_factory=list)
    active_quests: list[str] = field(default_factory=list)
    recent_events: list[str] = field(default_factory=list)


def build_session_prompt(
    context: CampaignContext,
    *,
    objective: str,
    tone: str,
    pacing: str,
    length: str,
    extra_direction: str = "",
) -> str:
    def section(title: str, items: list[str]) -> str:
        body = "\n".join(f"- {item}" for item in items) or "- None recorded"
        return f"{title}:\n{body}"

    return "\n\n".join(
        [
            "You are assisting a dungeon master running D&D 5e (2024).",
            (
                f"Campaign: {context.campaign_name}\n"
                f"Premise: {context.campaign_summary or 'Not recorded'}"
            ),
            section("Characters", context.characters),
            section("Locations", context.locations),
            section("Active quests", context.active_quests),
            section("Recent events", context.recent_events),
            (
                "Write a table-ready session script with scene headings, boxed narration, "
                "NPC motivations, likely player branches, checks with suggested DCs, and "
                "concise DM notes."
            ),
            f"Session objective: {objective}",
            f"Tone: {tone}\nPacing: {pacing}\nLength: {length}",
            f"Additional direction: {extra_direction or 'None'}",
            "Do not decide player actions. Clearly mark secrets that should not be read aloud.",
        ]
    )


def build_world_guidance_prompt(
    *,
    mode: str,
    step_name: str,
    answers: dict[str, str],
    existing_world: str = "",
) -> str:
    mode_instructions = {
        "Clarify": (
            "Ask exactly one focused follow-up question that makes the answer more concrete."
        ),
        "Expand": (
            "Offer exactly three distinct possibilities with different tones or consequences."
        ),
        "Connect": (
            "Identify one useful connection or dependency with the existing world context."
        ),
        "Challenge": (
            "Identify one contradiction, missing consequence, or unresolved tradeoff as a question."
        ),
    }
    answer_lines = "\n".join(
        f"- {key}: {value or 'Not answered'}" for key, value in answers.items()
    ) or "- No answers recorded yet"
    return "\n\n".join(
        [
            "You are a bounded world-building guide for a D&D campaign tool.",
            f"Current fixed step: {step_name}",
            f"Guidance mode: {mode}",
            mode_instructions.get(mode, mode_instructions["Clarify"]),
            "Current answers:",
            answer_lines,
            f"Existing world context: {existing_world or 'None recorded'}",
            "Do not write canonical records. Do not invent facts as settled truth. "
            "Label every idea as a suggestion for the DM to accept, edit, or reject.",
            "Keep the response concise and usable in a questionnaire.",
        ]
    )
