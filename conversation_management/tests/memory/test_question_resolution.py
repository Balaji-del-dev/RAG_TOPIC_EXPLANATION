"""7. Previous question resolution."""

from langchain_core.messages import AIMessage, HumanMessage

from conversation_memory.question_resolution import resolve_question
from tests.conftest import BrokenLLM

HISTORY = [HumanMessage(content="How many sick days do I get?"), AIMessage(content="You get 12 sick days a year.")]


def test_llm_rewrites_the_follow_up(fake_llm):
    llm = fake_llm("How many sick days do part-time staff get?")
    result = resolve_question("And for part-time staff?", HISTORY, "", llm)
    assert result.question == "How many sick days do part-time staff get?"
    assert result.method == "llm"


def test_prefix_and_quotes_are_cleaned(fake_llm):
    llm = fake_llm('Standalone question: "How many sick days do part-time staff get?"\nExtra line')
    assert resolve_question("And for part-time staff?", HISTORY, "", llm).question == "How many sick days do part-time staff get?"


def test_an_answer_instead_of_a_question_is_rejected(fake_llm):
    llm = fake_llm("Part-time staff get 6 sick days a year.")  # the LLM answered instead of rewriting
    result = resolve_question("And for part-time staff?", HISTORY, "", llm)
    assert result.method == "fallback"
    assert result.question == "How many sick days do I get? And for part-time staff?"


def test_llm_down_falls_back_to_joining_questions():
    result = resolve_question("And for part-time staff?", HISTORY, "", BrokenLLM())
    assert result.method == "fallback"
    assert "sick days" in result.question and "part-time" in result.question


def test_no_llm_configured_falls_back():
    assert resolve_question("And for part-time staff?", HISTORY, "", None).method == "fallback"


def test_nothing_to_resolve_against():
    result = resolve_question("And for part-time staff?", [], "", None)
    assert result.method == "unchanged" and result.question == "And for part-time staff?"


def test_an_echo_is_not_a_rewrite(fake_llm):
    # what qwen2.5:1.5b did once: returned the follow-up unchanged
    result = resolve_question("And for part-time staff?", HISTORY, "", fake_llm("and for part-time staff ?"))
    assert result.method == "fallback"
    assert result.question == "How many sick days do I get? And for part-time staff?"


def test_examples_are_sent_as_chat_turns():
    from conversation_memory.question_resolution import EXAMPLES, _example_turns

    turns = _example_turns()
    assert len(turns) == 2 * len(EXAMPLES)
    assert isinstance(turns[0], HumanMessage) and isinstance(turns[1], AIMessage)
