"""Textual front end for playful, human-steered VM sessions."""

from __future__ import annotations

import queue
from dataclasses import asdict
from io import BytesIO

from PIL import Image
from rich.style import Style
from rich.text import Text
from textual import work
from textual.app import App, ComposeResult
from textual.containers import Horizontal
from textual.widgets import Button, Footer, Header, Input, RichLog, Static

from gade_cua_evolve.config import RunConfig, TaskSpec
from gade_cua_evolve.controller import RunController
from gade_cua_evolve.registry import build_components
from gade_cua_evolve.trajectory import TrajectoryRecorder


def screenshot_renderable(data: bytes, width: int = 60, rows: int = 22) -> Text:
    """Render an image with true-color upper-half block characters."""
    with Image.open(BytesIO(data)) as source:
        image = source.convert("RGB")
    image.thumbnail((width, rows * 2))
    canvas = Image.new("RGB", (width, rows * 2), "black")
    left = (width - image.width) // 2
    canvas.paste(image, (left, 0))
    output = Text()
    for y in range(0, canvas.height, 2):
        for x in range(canvas.width):
            top = canvas.getpixel((x, y))
            bottom = canvas.getpixel((x, min(y + 1, canvas.height - 1)))
            output.append("▀", Style(color=f"rgb{top}", bgcolor=f"rgb{bottom}"))
        output.append("\n")
    return output


class GadeTUI(App[None]):
    TITLE = "GADE CUA"
    SUB_TITLE = "Playful desktop agent session"
    CSS = """
    Screen { layout: vertical; }
    #body { height: 1fr; }
    #preview { width: 2fr; border: round $accent; padding: 0 1; overflow: auto; }
    #chat { width: 3fr; border: round $primary; }
    #prompt { dock: bottom; }
    #completion { height: auto; display: none; }
    Button { margin: 0 1; }
    """

    def __init__(
        self,
        config: RunConfig,
        *,
        arm_enabled: bool = False,
        initial_task: TaskSpec | None = None,
    ) -> None:
        super().__init__()
        self.config = config
        self.arm_enabled = arm_enabled
        self.initial_task = initial_task
        self.controller: RunController | None = None
        self.recorder: TrajectoryRecorder | None = None
        self.current_task: TaskSpec | None = None
        self.running = False

    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal(id="body"):
            yield Static("Enter a task to start a disposable VM session.", id="preview")
            yield RichLog(id="chat", wrap=True, markup=True, max_lines=1000)
        with Horizontal(id="completion"):
            yield Button("Accept & close", id="accept", variant="success")
            yield Button("Continue", id="continue")
            yield Button("Evaluate & close", id="evaluate", variant="primary")
            yield Button("Stop", id="stop", variant="error")
        yield Input(
            placeholder="Describe a desktop task, or /pause /resume /stop while it runs…",
            id="prompt",
        )
        yield Footer()

    def on_mount(self) -> None:
        self.set_interval(0.1, self._poll_events)
        if self.initial_task:
            self.query_one("#prompt", Input).value = self.initial_task.instruction
            self.call_after_refresh(self._start_task, self.initial_task)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        value = event.value.strip()
        event.input.value = ""
        if not value:
            return
        if self.running:
            self._handle_running_input(value)
            return
        self._start_task(TaskSpec(instruction=value))

    def _handle_running_input(self, value: str) -> None:
        assert self.controller is not None
        command = value.lower()
        if command == "/pause":
            self.controller.pause()
        elif command == "/resume":
            self.controller.resume()
        elif command == "/stop":
            self.controller.cancel()
            self.controller.decide_completion("stop")
        else:
            self.controller.add_feedback(value)
            self.query_one("#chat", RichLog).write(f"[bold cyan]You:[/] {value}")

    def _start_task(self, task: TaskSpec) -> None:
        if self.running:
            return
        self.current_task = task
        self.controller = RunController(interactive=True)
        self.recorder = TrajectoryRecorder(self.config.loop.output_dir, task, self.config)
        self.running = True
        self.query_one("#chat", RichLog).clear()
        self.query_one("#chat", RichLog).write(f"[bold cyan]You:[/] {task.instruction}")
        self.query_one("#completion").styles.display = "none"
        self._run_session(task)

    @work(thread=True, exclusive=True)
    def _run_session(self, task: TaskSpec) -> None:
        assert self.controller is not None and self.recorder is not None
        try:
            _, _, loop = build_components(
                self.config,
                self.recorder,
                controller=self.controller,
                arm_enabled=self.arm_enabled,
            )
            result = loop.run(task)
            self.controller.emit("session_result", "Session finished", result=asdict(result))
        except Exception as exc:  # noqa: BLE001 - surface worker errors in the UI
            self.controller.emit("session_error", f"{type(exc).__name__}: {exc}")

    def _poll_events(self) -> None:
        if not self.controller:
            return
        chat = self.query_one("#chat", RichLog)
        while True:
            try:
                event = self.controller.events.get_nowait()
            except queue.Empty:
                break
            if event.kind == "agent_step":
                chat.write(f"[bold magenta]Agent:[/] {event.message}")
            elif event.kind == "action":
                chat.write(f"[dim]Action:[/] {event.message}")
                screenshot = event.payload.get("screenshot")
                if isinstance(screenshot, bytes):
                    preview = screenshot_renderable(screenshot)
                    if self.recorder:
                        preview.append(f"\n{self.recorder.directory}")
                    self.query_one("#preview", Static).update(preview)
            elif event.kind == "arm_verdict":
                chat.write(f"[yellow]ARM:[/] {event.message}")
            elif event.kind == "native_score":
                chat.write(f"[bold green]{event.message}[/]")
            elif event.kind in {"paused", "resumed", "cancelled"}:
                chat.write(f"[dim]{event.message}[/]")
            elif event.kind == "completion_requested":
                self.query_one("#completion").styles.display = "block"
                evaluate = self.query_one("#evaluate", Button)
                evaluate.disabled = not bool(self.current_task and self.current_task.has_native_evaluator)
                chat.write("[bold]Agent is ready. Accept, continue, evaluate, or stop.[/]")
            elif event.kind == "session_result":
                self.running = False
                self.query_one("#completion").styles.display = "none"
                result = event.payload.get("result", {})
                chat.write(
                    f"[bold green]Finished:[/] {result.get('status')} "
                    f"score={result.get('score')} output={result.get('output_dir')}"
                )
            elif event.kind == "session_error":
                self.running = False
                self.query_one("#completion").styles.display = "none"
                chat.write(f"[bold red]Error:[/] {event.message}")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if not self.controller:
            return
        decisions = {
            "accept": "accept",
            "continue": "continue",
            "evaluate": "evaluate",
            "stop": "stop",
        }
        decision = decisions.get(event.button.id or "")
        if decision:
            self.query_one("#completion").styles.display = "none"
            self.controller.decide_completion(decision)  # type: ignore[arg-type]


def run_tui(config: RunConfig, *, arm_enabled: bool = False, task: TaskSpec | None = None) -> None:
    GadeTUI(config, arm_enabled=arm_enabled, initial_task=task).run()
