from pathlib import Path

import pytest
import yaml

from app.services.scope_gate import ScopeGate, ScopeVerdict, evaluate_scope_gate


SHIPPED_CASES = Path(__file__).parent.parent / "app" / "evals" / "scope_gate_cases.yaml"


class StubLLM:
    def __init__(self, result) -> None:
        self.result = result
        self.messages: list = []

    async def chat_json(self, messages, schema, **kwargs):
        self.messages = messages
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


@pytest.mark.parametrize("question", [
    "What are the winning lottery numbers?",
    "Give me a recipe for banana bread",
    "Who won the NFL game last night?",
    "tell me a joke",
])
async def test_fake_classifier_declines_blatant_off_topic_questions(question: str) -> None:
    verdict = await ScopeGate(None, True).classify(question)
    assert verdict.declined


@pytest.mark.parametrize("question", [
    "Which acquisition pathway applies to commercial cloud hosting?",
    "What vendors have recent Space Force contracts under Cloud One?",
    "What does the lottery contract solicitation require?",  # domain words win over an off-topic word
    "cloud one recompete?",
])
async def test_fake_classifier_lets_acquisition_questions_through(question: str) -> None:
    assert not (await ScopeGate(None, True).classify(question)).declined


async def test_llm_classifier_sends_the_question_as_user_content_only() -> None:
    llm = StubLLM({"verdict": "in_scope", "reason": "about acquisition"})
    verdict = await ScopeGate(llm, False).classify("What is the PSM role?")
    assert verdict == ScopeVerdict(verdict="in_scope", reason="about acquisition")
    assert [m["role"] for m in llm.messages] == ["system", "user"]
    assert llm.messages[1]["content"] == "What is the PSM role?"


@pytest.mark.parametrize("bad", [RuntimeError("down"), {"verdict": "maybe", "reason": "x"}, {}])
async def test_llm_errors_and_malformed_output_fail_open(bad) -> None:
    verdict = await ScopeGate(StubLLM(bad), False).classify("anything")
    assert verdict.verdict == "unclear" and not verdict.declined


def test_only_out_of_scope_declines() -> None:
    assert ScopeVerdict(verdict="out_of_scope", reason="x").declined
    assert not ScopeVerdict(verdict="unclear", reason="x").declined
    assert not ScopeVerdict(verdict="in_scope", reason="x").declined


def test_shipped_eval_cases_are_well_formed() -> None:
    cases = yaml.safe_load(SHIPPED_CASES.read_text())["cases"]
    ids = [case["id"] for case in cases]
    assert len(ids) == len(set(ids))
    assert {case["expected"] for case in cases} == {"in_scope", "out_of_scope"}
    assert all(case["question"].strip() for case in cases)


async def test_fake_classifier_never_refuses_a_shipped_in_scope_case() -> None:
    # Guards the demo in fake/test mode; the real Qwen classifier is scored with `eval-scope`.
    report = await evaluate_scope_gate(ScopeGate(None, True), SHIPPED_CASES)
    assert report["false_refusals"] == []
    assert report["false_refusal_rate"] == 0


async def test_evaluator_reports_false_refusals_and_misses(tmp_path: Path) -> None:
    cases = tmp_path / "cases.yaml"
    cases.write_text(yaml.safe_dump({"cases": [
        {"id": "ok-in", "question": "q1", "expected": "in_scope"},
        {"id": "bad-in", "question": "q2", "expected": "in_scope"},
        {"id": "ok-out", "question": "q3", "expected": "out_of_scope"},
        {"id": "bad-out", "question": "q4", "expected": "out_of_scope"},
    ]}))

    class Scripted(ScopeGate):
        async def classify(self, question: str) -> ScopeVerdict:
            verdict = {"q1": "unclear", "q2": "out_of_scope", "q3": "out_of_scope", "q4": "in_scope"}[question]
            return ScopeVerdict(verdict=verdict, reason="scripted")

    report = await evaluate_scope_gate(Scripted(None, True), cases)
    assert report["false_refusals"] == ["bad-in"]
    assert report["missed_off_topic"] == ["bad-out"]
    assert report["false_refusal_rate"] == 0.5
    assert report["decline_rate"] == 0.5
    assert report["case_count"] == 4
