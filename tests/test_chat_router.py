"""Self-check verification test for chat REPL and deterministic command routing."""

# 1. Standard library imports
# (None)

# 2. Third-party imports
# (None)

# 3. Local / internal imports
from nemo.cli.chat import is_action_intent, is_native_command

# 4. Types, Protocols, Schemas
# (None)

# 5. Core logic / classes / functions
def test_deterministic_command_routing():
    """Verify shell commands bypass LLM while natural language routes to AI."""
    # Shell commands: must return True
    assert is_native_command("git status")
    assert is_native_command("dir")
    assert is_native_command("ls -la")
    assert is_native_command("python --version")
    assert is_native_command("pytest tests/")
    assert is_native_command("uv run")
    assert is_native_command("cargo build")
    assert is_native_command("Get-Date")

    # Natural language queries: must return False (route to Nemotron)
    assert not is_native_command("Explain the project architecture.")
    assert not is_native_command("How do I fix the database connection?")
    assert not is_native_command("remember backend is FastAPI")
    assert not is_native_command("task refactor authentication module")


def test_action_intent_routing():
    """Verify operational instructions trigger agent task workflow instead of plain chat."""
    assert is_action_intent("initialize this project")
    assert is_action_intent("init workspace")
    assert is_action_intent("setup react project with tailwind")
    assert is_action_intent("start dev server")
    assert is_action_intent("launch vite app")
    assert is_action_intent("install required packages")

    # Pure conversational queries should not trigger action intent
    assert not is_action_intent("what does this project do?")
    assert not is_action_intent("explain the database design")
    assert not is_action_intent("hello there")


def main():
    print("Running chat REPL deterministic router verification...")
    test_deterministic_command_routing()
    test_action_intent_routing()
    print("✓ Chat REPL deterministic command routing checks passed!")


if __name__ == "__main__":
    main()

# 6. Public exports
__all__ = ["test_deterministic_command_routing", "test_action_intent_routing"]

