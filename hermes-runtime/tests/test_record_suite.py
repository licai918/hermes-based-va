"""Record-suite wiring: default OpenRouter record run, suite recorder, .env loader.

These are the glue that turns the per-scenario recorder bridge into a runnable
"record the whole Launch Eval suite live" entrypoint (ADR-0009, ADR-0071, ADR-0121):

- :func:`make_openrouter_record_run` is the production record seam — a ``run_turn``
  that drives one real ``AIAgent`` turn through OpenRouter (here a scripted provider
  is injected so the loop runs with no network), with per-completion model fallback.
- :func:`record_suite` records every scenario in a suite, persisting one transcript
  each for deterministic ``--harness replay``.
- :func:`load_env_file` loads gitignored secrets (the OpenRouter key) without leaking
  them into the repo.
"""

from __future__ import annotations

from pathlib import Path

from eval_runner.fixtures import load_suite
from eval_runner.replay import ReplayAgentHarness

from hermes_runtime.eval_record import make_openrouter_record_run, record_suite
from hermes_runtime.openrouter import OpenRouterConfig
from hermes_runtime.record_eval import load_env_file

EVAL_DIR = Path(__file__).resolve().parents[2] / "eval"


def test_make_openrouter_record_run_drives_the_real_loop_via_injected_provider() -> None:
    # With an injected scripted provider + explicit config, the record run drives a real
    # AIAgent turn (no network) and returns the captured {final_response, messages}.
    config = OpenRouterConfig(
        base_url="http://router.invalid/v1",
        api_key="sk-test",
        model="deepseek/deepseek-v4-pro",
        fallback_model="qwen/qwen3.6-flash",
    )

    captured: dict[str, object] = {}

    class _Completions:
        def create(self, **kwargs: object):
            captured["model"] = kwargs.get("model")
            from openai.types.chat import ChatCompletion
            from openai.types.chat.chat_completion import Choice
            from openai.types.chat.chat_completion_message import ChatCompletionMessage

            return ChatCompletion(
                id="x",
                created=0,
                model="m",
                object="chat.completion",
                choices=[
                    Choice(
                        index=0,
                        finish_reason="stop",
                        message=ChatCompletionMessage(
                            role="assistant", content="Hello from the agent."
                        ),
                    )
                ],
            )

    class _Chat:
        def __init__(self) -> None:
            self.completions = _Completions()

    class _Client:
        def __init__(self, *_a: object, **_k: object) -> None:
            self.chat = _Chat()

    run_turn = make_openrouter_record_run(config=config, openai_factory=_Client)
    turn = run_turn(
        user_message="hi", system_message="be helpful", governed_tool_names=()
    )

    assert turn["final_response"] == "Hello from the agent."
    # The turn was issued against the configured primary model (ADR-0009).
    assert captured["model"] == "deepseek/deepseek-v4-pro"


def test_record_suite_records_every_scenario_in_the_suite(tmp_path: Path) -> None:
    # record_suite records one transcript per scenario; each replays from disk.
    expected = load_suite("text_first_launch", EVAL_DIR)

    def run_turn(*, user_message, system_message, governed_tool_names):
        return {"final_response": "Thanks for reaching out to Toee Tire.", "messages": []}

    recorded = record_suite(
        "text_first_launch",
        eval_dir=EVAL_DIR,
        transcripts_dir=tmp_path,
        run_turn=run_turn,
        system_message="persona",
    )

    assert len(recorded) == len(expected)
    recorded_ids = {entry.scenario_id for entry in recorded}
    assert recorded_ids == {s.scenario_id for s in expected}
    for entry in recorded:
        assert entry.path.is_file()
        # Each persisted transcript replays deterministically.
        replayed = ReplayAgentHarness(tmp_path).run_turn(
            next(s for s in expected if s.scenario_id == entry.scenario_id)
        )
        assert replayed.outbound_text == entry.result.outbound_text


def test_record_suite_can_record_a_scenario_subset(tmp_path: Path) -> None:
    # Re-recording only the scenarios that failed replay keeps the iterate loop cheap.
    def run_turn(*, user_message, system_message, governed_tool_names):
        return {"final_response": "ok", "messages": []}

    recorded = record_suite(
        "text_first_launch",
        eval_dir=EVAL_DIR,
        transcripts_dir=tmp_path,
        run_turn=run_turn,
        scenario_ids=["01", "13"],
    )

    assert {entry.scenario_id for entry in recorded} == {"01", "13"}


def test_load_env_file_sets_only_absent_keys(tmp_path: Path, monkeypatch) -> None:
    env = tmp_path / ".env"
    env.write_text(
        "# secrets\nOPENROUTER_API_KEY=sk-from-file\nOPENROUTER_MODEL=deepseek/deepseek-v4-pro\n",
        encoding="utf-8",
    )
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.setenv("OPENROUTER_MODEL", "preset/in-env")

    loaded = load_env_file(env)

    import os

    # Absent key is loaded from the file...
    assert os.environ["OPENROUTER_API_KEY"] == "sk-from-file"
    # ...but an already-set env var is never overwritten.
    assert os.environ["OPENROUTER_MODEL"] == "preset/in-env"
    assert loaded["OPENROUTER_API_KEY"] == "sk-from-file"


def test_load_env_file_missing_returns_empty(tmp_path: Path) -> None:
    assert load_env_file(tmp_path / "nope.env") == {}
