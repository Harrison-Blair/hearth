from assistant.core.conversation import Conversation
from assistant.core.events import Turn


def test_add_preserves_order():
    conv = Conversation(max_turns=10)
    conv.add("user", "hi")
    conv.add("assistant", "hello")
    assert conv.history() == [Turn("user", "hi"), Turn("assistant", "hello")]


def test_trim_keeps_last_n():
    conv = Conversation(max_turns=2)
    conv.add("user", "one")
    conv.add("assistant", "two")
    conv.add("user", "three")
    assert conv.history() == [Turn("assistant", "two"), Turn("user", "three")]


def test_history_copy_does_not_leak_mutation():
    conv = Conversation(max_turns=10)
    conv.add("user", "hi")
    snapshot = conv.history()
    snapshot.append(Turn("assistant", "injected"))
    assert conv.history() == [Turn("user", "hi")]
