import pytest
import itertools
from pathlib import Path

def pytest_addoption(parser):
    """Adds the --prompts command-line option to pytest."""
    parser.addoption(
        "--prompts",
        action="append",
        default=[],
        help="Comma-separated list of prompts (or @path/to/file.txt) to feed the live E2E test",
    )

def _load_prompts(raw: str) -> list[str]:
    """Loads prompts from a string, handling file paths prefixed with @."""
    if raw.startswith("@"):
        try:
            return [p.strip() for p in Path(raw[1:]).read_text().splitlines() if p.strip()]
        except FileNotFoundError:
            pytest.fail(f"Prompt file not found at: {raw[1:]}")
    return [p.strip() for p in raw.split(",") if p.strip()]

def pytest_generate_tests(metafunc: pytest.Metafunc):
    """Dynamically parametrizes tests that use the 'prompt' fixture."""
    if "prompt" in metafunc.fixturenames:
        cli_values = metafunc.config.getoption("--prompts")
        if not cli_values:
            # If no prompts are passed via CLI, use Hello World.
            loaded_prompts = [
                "Create a hello world app"
            ]
        else:
            loaded_prompts = list(itertools.chain.from_iterable(_load_prompts(v) for v in cli_values))
        
        metafunc.parametrize("prompt", loaded_prompts)
