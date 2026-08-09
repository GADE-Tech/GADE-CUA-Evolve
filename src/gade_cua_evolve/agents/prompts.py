"""Prompt construction for the Qwen3-VL computer-use agent."""

import json

ACTIONS = [
    "key",
    "type",
    "mouse_move",
    "left_click",
    "left_click_drag",
    "right_click",
    "middle_click",
    "double_click",
    "scroll",
    "wait",
    "terminate",
]


def computer_tool(coordinate_type: str, width: int, height: int) -> dict:
    resolution = f"{width}x{height}" if coordinate_type == "absolute" else "1000x1000"
    description = (
        "Use a mouse and keyboard to interact with a desktop GUI and take screenshots. "
        f"The coordinate resolution is {resolution}. Consult the screenshot before clicking, "
        "click the center of UI elements, and wait when applications need time to load."
    )
    return {
        "type": "function",
        "function": {
            "name_for_human": "computer_use",
            "name": "computer_use",
            "description": description,
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {"type": "string", "enum": ACTIONS},
                    "keys": {"type": "array"},
                    "text": {"type": "string"},
                    "coordinate": {"type": "array"},
                    "pixels": {"type": "number"},
                    "time": {"type": "number"},
                    "status": {"type": "string", "enum": ["success", "failure"]},
                    "duration": {"type": "number"},
                },
                "required": ["action"],
            },
            "args_format": "Format arguments as a JSON object.",
        },
    }


def system_prompt(coordinate_type: str, width: int, height: int) -> str:
    tool = json.dumps(computer_tool(coordinate_type, width, height))
    return f"""# Tools
You may call one function to assist with the user query.
<tools>
{tool}
</tools>
Return exactly:
Action: a short imperative describing the next UI action.
<tool_call>
{{"name": "computer_use", "arguments": {{...}}}}
</tool_call>
Do not output anything else. To finish, call computer_use with action=terminate."""


def instruction_prompt(instruction: str, actions: list[str], feedbacks: list[str] | None = None) -> str:
    previous = "\n".join(f"Step {index + 1}: {action}" for index, action in enumerate(actions))
    feedback = "\n\n".join(feedbacks or [])
    return (
        "Generate the next move from the screenshot, instruction, and previous actions.\n\n"
        f"Instruction: {instruction}\n\nPrevious actions:\n{previous or 'None'}\n\n"
        f"Human/verifier feedback:\n{feedback or 'None'}"
    )
