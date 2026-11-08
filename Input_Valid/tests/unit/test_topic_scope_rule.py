"""Step 11: the scope rule (decide_topic) without models."""

from input_security.scope.topic_scope import TopicScore, decide_topic


def test_close_to_an_allowed_example():
    assert decide_topic(TopicScore("leave_policy", 0.82, 0.10), 0.40)


def test_below_minimum_similarity():
    assert not decide_topic(TopicScore("leave_policy", 0.30, 0.05), 0.40)


def test_closer_to_off_topic_example():
    assert not decide_topic(TopicScore("benefits", 0.45, 0.70), 0.40)
