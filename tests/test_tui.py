import asyncio
from io import BytesIO

from PIL import Image

from gade_cua_evolve.config import RunConfig
from gade_cua_evolve.controller import RunController
from gade_cua_evolve.tui import GadeTUI, screenshot_renderable


def image_bytes() -> bytes:
    output = BytesIO()
    Image.new("RGB", (80, 40), "blue").save(output, "PNG")
    return output.getvalue()


def test_screenshot_thumbnail_uses_terminal_blocks() -> None:
    rendered = screenshot_renderable(image_bytes(), width=10, rows=4)
    assert "▀" in rendered.plain
    assert len(rendered.plain.splitlines()) == 4


def test_tui_accepts_async_human_feedback() -> None:
    async def exercise() -> None:
        app = GadeTUI(RunConfig())
        async with app.run_test(size=(100, 32)) as pilot:
            app.running = True
            app.controller = RunController(interactive=True)
            await pilot.click("#prompt")
            await pilot.press("f", "i", "x", "space", "i", "t", "enter")
            await pilot.pause()
            assert app.controller.drain_feedback() == ["fix it"]

    asyncio.run(exercise())
