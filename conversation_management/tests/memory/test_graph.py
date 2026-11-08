"""The whole memory graph: InMemorySaver checkpointer + fake LLM."""

from langchain_core.messages import HumanMessage

from conversation_memory import MemorySettings, build_conversation_graph
from conversation_memory.checkpointer import create_memory_checkpointer


def ask(graph, thread: str, question: str) -> dict:
    return graph.invoke(
        {"question": question, "messages": [HumanMessage(content=question)]},
        config={"configurable": {"thread_id": thread}},
    )


def test_follow_up_is_detected_and_rewritten(fake_llm):
    graph = build_conversation_graph(checkpointer=create_memory_checkpointer(), llm=fake_llm("How many sick days do part-time staff get?"))
    first = ask(graph, "t1", "How many sick days do I get?")
    assert not first["is_follow_up"] and first["resolution"] == "unchanged"

    second = ask(graph, "t1", "And for part-time staff?")
    assert second["is_follow_up"]
    assert second["standalone_question"] == "How many sick days do part-time staff get?"
    assert second["resolution"] == "llm"
    assert "part-time staff get?" in second["answer"]  # the answer step receives the standalone question


def test_each_conversation_has_its_own_memory(fake_llm):
    graph = build_conversation_graph(checkpointer=create_memory_checkpointer(), llm=None)
    ask(graph, "alice-thread", "How many sick days do I get?")
    other = ask(graph, "bob-thread", "And for part-time staff?")
    assert not other["is_follow_up"]  # bob's thread has no history
    assert len(graph.get_state({"configurable": {"thread_id": "bob-thread"}}).values["messages"]) == 2


def test_memory_is_compacted_when_over_budget(fake_llm):
    llm = fake_llm("Employee asked about leave policies.")
    settings = MemorySettings(max_context_tokens=80, keep_recent_messages=2)
    graph = build_conversation_graph(checkpointer=create_memory_checkpointer(), llm=llm, settings=settings)
    for question in [
        "How many annual leave days do employees get each year in the Chennai office?",
        "What is the policy for carrying forward unused annual leave to the next year?",
        "How do I apply for maternity leave and which documents does HR need from me?",
    ]:
        result = ask(graph, "t", question)

    assert result["summarized"] and result["summary_method"] == "llm"
    state = graph.get_state({"configurable": {"thread_id": "t"}}).values
    assert state["summary"] == "Employee asked about leave policies."
    assert len(state["messages"]) <= 3  # 2 kept + the new answer; older ones removed
    assert result["context_tokens"] <= 80


def test_without_llm_everything_still_works():
    graph = build_conversation_graph(checkpointer=create_memory_checkpointer(), llm=None)
    ask(graph, "t", "How many sick days do I get?")
    result = ask(graph, "t", "And for part-time staff?")
    assert result["resolution"] == "fallback"
    assert result["standalone_question"] == "How many sick days do I get? And for part-time staff?"
