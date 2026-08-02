"""GTA1.5 tool declarations, Gemini grounding, and OSWorld action rendering."""

from __future__ import annotations

import base64
import json
import re
from io import BytesIO
from typing import Any

from PIL import Image

from gade_cua_evolve.llm import Client, ToolCall


def _function(name: str, description: str, properties: dict[str, Any], required: list[str]) -> dict:
    return {
        "type": "function",
        "name": name,
        "description": description,
        "parameters": {
            "type": "object",
            "properties": properties,
            "required": required,
        },
    }


CUA_TOOLS = [
    _function(
        "click",
        "Click on the element",
        {
            "instruction": {
                "type": "string",
                "description": "Describe the visual element and its function clearly and concisely.",
            },
            "num_clicks": {"type": "integer", "description": "Number of clicks.", "default": 1},
            "button_type": {
                "type": "string",
                "enum": ["left", "middle", "right"],
                "default": "left",
            },
            "hold_keys": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Keys to hold while clicking.",
                "default": [],
            },
        },
        ["instruction"],
    ),
    _function(
        "drag_and_drop",
        "Drag from the starting description to the ending description",
        {
            "starting_description": {"type": "string", "description": "Detailed drag start."},
            "ending_description": {"type": "string", "description": "Detailed drag end."},
            "hold_keys": {
                "type": "array",
                "items": {"type": "string"},
                "default": [],
            },
        },
        ["starting_description", "ending_description"],
    ),
    _function(
        "highlight_text_span",
        "Highlight a text span between a provided starting phrase and ending phrase.",
        {
            "starting_phrase": {"type": "string"},
            "ending_phrase": {"type": "string"},
        },
        ["starting_phrase", "ending_phrase"],
    ),
    _function(
        "hold_and_press",
        "Hold a list of keys and press a list of keys",
        {
            "hold_keys": {"type": "array", "items": {"type": "string"}},
            "press_keys": {"type": "array", "items": {"type": "string"}},
        },
        ["hold_keys", "press_keys"],
    ),
    _function(
        "hotkey",
        "Press a hotkey combination",
        {"keys": {"type": "array", "items": {"type": "string"}}},
        ["keys"],
    ),
    _function(
        "open",
        "Open any application or file by name; do not open it manually.",
        {"app_or_filename": {"type": "string"}},
        ["app_or_filename"],
    ),
    _function(
        "scroll",
        "Scroll the element in the specified direction",
        {
            "instruction": {"type": "string", "description": "Detailed scroll target."},
            "clicks": {"type": "integer", "description": "Positive is up; negative is down."},
            "shift": {"type": "boolean", "default": False},
        },
        ["instruction", "clicks"],
    ),
    _function(
        "set_cell_values",
        "Set individual spreadsheet cell values or formulas. Formula strings start with '='.",
        {
            "cell_values": {
                "type": "object",
                "description": "Mapping of cell references such as A1 to strings or numbers.",
                "additionalProperties": {"type": ["number", "string"]},
                "default": {},
            },
            "app_name": {"type": "string"},
            "sheet_name": {"type": "string"},
        },
        ["cell_values", "app_name", "sheet_name"],
    ),
    _function(
        "switch_applications",
        "Switch to a different application that is already open",
        {"app_code": {"type": "string"}},
        ["app_code"],
    ),
    _function(
        "type",
        "Type text into a specific element",
        {
            "element_description": {
                "type": ["string", "null"],
                "description": "Detailed target; null types into the focused element.",
                "default": None,
            },
            "text": {"type": "string", "default": ""},
            "overwrite": {"type": "boolean", "default": False},
            "enter": {"type": "boolean", "default": False},
        },
        ["text"],
    ),
    _function(
        "wait",
        "Wait for a specified amount of time",
        {"time": {"type": "number", "description": "Seconds to wait."}},
        ["time"],
    ),
    _function(
        "fast_open_terminal",
        "Save the file in focus, close it, and open a terminal.",
        {},
        [],
    ),
]


GROUNDING_SYSTEM_PROMPT = """You are a precise GUI grounding model. Locate the single target requested by
the user in the supplied screenshot. Return a point in the center of that target using normalized
1000x1000 image coordinates: x=0 is the left edge, x=1000 the right edge, y=0 the top edge,
and y=1000 the bottom edge. Return JSON only as {"x": integer, "y": integer}."""

GROUNDING_SCHEMA = {
    "type": "object",
    "properties": {
        "x": {"type": "integer", "minimum": 0, "maximum": 1000},
        "y": {"type": "integer", "minimum": 0, "maximum": 1000},
    },
    "required": ["x", "y"],
    "additionalProperties": False,
}


def _data_url(image: bytes) -> str:
    encoded = base64.b64encode(image).decode("ascii")
    return f"data:image/png;base64,{encoded}"


def _json_object(text: str) -> dict[str, Any]:
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip(), flags=re.IGNORECASE)
    try:
        value = json.loads(cleaned)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", cleaned, re.DOTALL)
        if not match:
            raise ValueError(f"Grounding response is not JSON: {text!r}") from None
        value = json.loads(match.group(0))
    if not isinstance(value, dict):
        raise TypeError("Grounding response must be a JSON object")
    return value


class GeminiGrounder:
    """Ground referring expressions to Gemini's normalized 1000x1000 points."""

    def __init__(self, llm: Client, model: str | None = None, max_tokens: int = 512) -> None:
        self.llm = llm
        self.model = model
        self.max_tokens = max_tokens

    def locate(self, screenshot: bytes, description: str) -> tuple[float, float]:
        response = self.llm.complete(
            [
                {"role": "system", "content": GROUNDING_SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": [
                        {"type": "image_url", "image_url": {"url": _data_url(screenshot)}},
                        {"type": "text", "text": description},
                    ],
                },
            ],
            model=self.model or getattr(self.llm, "model", None),
            max_tokens=self.max_tokens,
            temperature=0.0,
            response_schema=GROUNDING_SCHEMA,
        )
        point = _json_object(response.text)
        x = min(1000.0, max(0.0, float(point["x"])))
        y = min(1000.0, max(0.0, float(point["y"])))
        return x / 1000.0, y / 1000.0


SET_CELL_VALUES_CODE = """import uno
import subprocess

def cell_ref_to_indices(cell_ref):
    letters = ''.join(filter(str.isalpha, cell_ref))
    digits = ''.join(filter(str.isdigit, cell_ref))
    col = sum((ord(c.upper()) - 64) * (26 ** i) for i, c in enumerate(reversed(letters))) - 1
    return col, int(digits) - 1

subprocess.run(['soffice', '--accept=socket,host=localhost,port=2002;urp;StarOffice.Service'])
local_context = uno.getComponentContext()
resolver = local_context.ServiceManager.createInstanceWithContext(
    'com.sun.star.bridge.UnoUrlResolver', local_context)
context = resolver.resolve(
    'uno:socket,host=localhost,port=2002;urp;StarOffice.ComponentContext')
desktop = context.ServiceManager.createInstanceWithContext(
    'com.sun.star.frame.Desktop', context)
spreadsheets = [component for component in desktop.Components
                if component.supportsService('com.sun.star.sheet.SpreadsheetDocument')]
if not spreadsheets:
    raise ValueError('No open spreadsheet found')
selected = next((doc for doc in spreadsheets if doc.Title == APP_NAME), spreadsheets[0])
sheet = selected.Sheets.getByName(SHEET_NAME)
for ref, value in CELL_VALUES.items():
    col, row = cell_ref_to_indices(ref)
    cell = sheet.getCellByPosition(col, row)
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        cell.Value = value
    elif isinstance(value, str) and value.startswith('='):
        cell.Formula = value
    else:
        cell.String = str(value)
"""


class GTA15ActionRenderer:
    """Turn GTA1.5 function calls into OSWorld pyautogui action strings."""

    def __init__(self, grounder: GeminiGrounder, platform: str = "ubuntu") -> None:
        self.grounder = grounder
        self.platform = "linux" if platform == "ubuntu" else platform

    def execute(self, call: ToolCall, screenshot: bytes) -> tuple[str, str]:
        try:
            method = getattr(self, f"_render_{call.name}")
        except AttributeError:
            return "WAIT", f"Error: unknown tool {call.name!r}"
        try:
            return method(dict(call.arguments), screenshot), "Action (tool call) was executed."
        except Exception as exc:  # noqa: BLE001 - feed all renderer errors back to the agent
            return "WAIT", f"Error: {type(exc).__name__}: {exc}"

    @staticmethod
    def _pixel(point: tuple[float, float], screenshot: bytes) -> tuple[int, int]:
        width, height = Image.open(BytesIO(screenshot)).size
        return round(point[0] * width), round(point[1] * height)

    def _ground(self, screenshot: bytes, description: str) -> tuple[int, int]:
        return self._pixel(self.grounder.locate(screenshot, description), screenshot)

    def _render_click(self, args: dict[str, Any], screenshot: bytes) -> str:
        x, y = self._ground(screenshot, str(args["instruction"]))
        keys = args.get("hold_keys", [])
        command = "import pyautogui; "
        command += "".join(f"pyautogui.keyDown({key!r}); " for key in keys)
        command += (
            f"pyautogui.click({x}, {y}, clicks={int(args.get('num_clicks', 1))}, "
            f"button={args.get('button_type', 'left')!r}); "
        )
        return command + "".join(f"pyautogui.keyUp({key!r}); " for key in keys)

    def _render_type(self, args: dict[str, Any], screenshot: bytes) -> str:
        command = "import pyautogui; "
        description = args.get("element_description")
        if description:
            x, y = self._ground(screenshot, str(description))
            command += f"pyautogui.click({x}, {y}); "
        if args.get("overwrite"):
            command += "pyautogui.hotkey('ctrl', 'a'); pyautogui.press('backspace'); "
        command += f"pyautogui.write({str(args.get('text', ''))!r}); "
        if args.get("enter"):
            command += "pyautogui.press('enter'); "
        return command

    def _render_scroll(self, args: dict[str, Any], screenshot: bytes) -> str:
        x, y = self._ground(screenshot, str(args["instruction"]))
        function = "hscroll" if args.get("shift") else "vscroll"
        return (
            f"import pyautogui; import time; pyautogui.moveTo({x}, {y}); "
            f"time.sleep(0.5); pyautogui.{function}({int(args['clicks'])})"
        )

    def _render_drag_and_drop(self, args: dict[str, Any], screenshot: bytes) -> str:
        x1, y1 = self._ground(screenshot, str(args["starting_description"]))
        x2, y2 = self._ground(screenshot, str(args["ending_description"]))
        keys = args.get("hold_keys", [])
        command = f"import pyautogui; pyautogui.moveTo({x1}, {y1}); "
        command += "".join(f"pyautogui.keyDown({key!r}); " for key in keys)
        command += f"pyautogui.dragTo({x2}, {y2}, duration=1.0); pyautogui.mouseUp(); "
        return command + "".join(f"pyautogui.keyUp({key!r}); " for key in keys)

    def _render_highlight_text_span(self, args: dict[str, Any], screenshot: bytes) -> str:
        start = f"the beginning edge of the exact text phrase: {args['starting_phrase']}"
        end = f"the ending edge of the exact text phrase: {args['ending_phrase']}"
        x1, y1 = self._ground(screenshot, start)
        x2, y2 = self._ground(screenshot, end)
        return (
            f"import pyautogui; pyautogui.moveTo({x1}, {y1}); "
            f"pyautogui.dragTo({x2}, {y2}, duration=1.0); pyautogui.mouseUp()"
        )

    @staticmethod
    def _render_hotkey(args: dict[str, Any], screenshot: bytes) -> str:
        del screenshot
        keys = ", ".join(repr(key) for key in args["keys"])
        return f"import pyautogui; pyautogui.hotkey({keys})"

    @staticmethod
    def _render_hold_and_press(args: dict[str, Any], screenshot: bytes) -> str:
        del screenshot
        command = "import pyautogui; "
        command += "".join(f"pyautogui.keyDown({key!r}); " for key in args["hold_keys"])
        command += f"pyautogui.press({args['press_keys']!r}); "
        return command + "".join(f"pyautogui.keyUp({key!r}); " for key in args["hold_keys"])

    def _render_switch_applications(self, args: dict[str, Any], screenshot: bytes) -> str:
        del screenshot
        app = str(args["app_code"])
        if self.platform == "darwin":
            return (
                "import pyautogui; import time; pyautogui.hotkey('command', 'space'); "
                f"pyautogui.write({app!r}); pyautogui.press('enter'); time.sleep(1)"
            )
        if self.platform == "windows":
            return (
                "import pyautogui; import time; pyautogui.hotkey('win', 'd'); "
                f"pyautogui.write({app!r}); pyautogui.press('enter'); time.sleep(1)"
            )
        return (
            "import subprocess, difflib, pyautogui, time; pyautogui.press('escape'); "
            "lines=subprocess.check_output(['wmctrl','-lx']).decode().splitlines(); "
            "titles=[line.split(None,4)[2] for line in lines]; "
            f"matches=difflib.get_close_matches({app!r},titles,n=1,cutoff=0.1); "
            "window_id=next(line.split()[0] for line in lines if matches and matches[0] in line); "
            "subprocess.run(['wmctrl','-ia',window_id]); "
            "subprocess.run(['wmctrl','-ir',window_id,'-b','add,maximized_vert,maximized_horz'])"
        )

    @staticmethod
    def _render_open(args: dict[str, Any], screenshot: bytes) -> str:
        del screenshot
        value = str(args["app_or_filename"])
        return (
            "import pyautogui; import time; pyautogui.press('win'); time.sleep(0.5); "
            f"pyautogui.write({value!r}); time.sleep(1); pyautogui.press('enter'); time.sleep(0.5)"
        )

    @staticmethod
    def _render_wait(args: dict[str, Any], screenshot: bytes) -> str:
        del screenshot
        return f"import time; time.sleep({float(args['time'])})"

    @staticmethod
    def _render_fast_open_terminal(args: dict[str, Any], screenshot: bytes) -> str:
        del args, screenshot
        return (
            "import pyautogui; import time; pyautogui.hotkey('ctrl','s'); time.sleep(0.5); "
            "pyautogui.hotkey('alt','f4'); time.sleep(0.5); pyautogui.hotkey('ctrl','alt','t')"
        )

    @staticmethod
    def _render_set_cell_values(args: dict[str, Any], screenshot: bytes) -> str:
        del screenshot
        prefix = (
            f"CELL_VALUES={args['cell_values']!r}\n"
            f"APP_NAME={str(args['app_name'])!r}\n"
            f"SHEET_NAME={str(args['sheet_name'])!r}\n"
        )
        return prefix + SET_CELL_VALUES_CODE
