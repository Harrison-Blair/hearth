"""FTHR-009 (PLM-003 FC-9b): "nothing unflavored reaches TTS" invariant.

A spy TTS (`FakeTTS`) plus a tagging stub Revoicer (`TaggingRevoicer`, whose
output carries a `<<REVOICED>>` marker) drive every speech path the pipeline
has. Each test asserts every string handed to the spy TTS is either:

  - revoicer-tagged (it went through the Revoicer seam), or
  - produced under `voiced=True` (already persona-flavored at its source), or
  - a `canned()` registry variant (LLM-free error/fallback line, voiced at
    its call site).

MAINTENANCE POINT: the four path classes below are the exhaustive list this
invariant covers today. A new speech path added to the pipeline must add a
case here.

  1. deterministic skill result (voiced=False)               -> revoiced
  2. persona-marked LLM skill result (voiced=True)            -> bypasses
  3. verify pre/post-stage filler via on_say (voiced=True)     -> bypasses
  4. pipeline error / can't-help / reply-error canned() lines  -> bypasses,
     canned() member

`test_speak_defaults_to_unvoiced` separately pins `_speak`'s default
parameter, so a future bare `_speak("...")` literal lands in the Revoicer
(flavored automatically) rather than bypassing it silently.
"""

from assistant.core.arbiter import AudioArbiter
from assistant.core.config import VerifyConfig
from assistant.core.orchestrator import Orchestrator
from tests.test_orchestrator_verify import EchoSkill, FallbackSkill, ScriptedLLM, _echo_call, _reg, _verdict
from tests.test_pipeline import (
    FakeAudioIn,
    FakeDetector,
    FakeOut,
    FakeSkill,
    FakeSTT,
    FakeTTS,
    NoResultOrchestrator,
    RaisingReplySkill,
    RaisingSkill,
    _pipeline,
)


class TaggingRevoicer:
    """Spy Revoicer: tags every string it restyles with a marker, so a test can
    tell a revoiced string apart from one that reached TTS untouched."""

    TAG = "<<REVOICED>>"

    def __init__(self):
        self.calls: list[str] = []

    async def revoice(self, text: str) -> str:
        self.calls.append(text)
        return f"{self.TAG}{text}"

    @classmethod
    def is_tagged(cls, text: str) -> bool:
        return text.startswith(cls.TAG)


# --- Path 1/4: deterministic skill result -----------------------------------


async def test_deterministic_skill_reply_is_revoiced_before_tts():
    # A plain deterministic skill result (Clock/Timer/Reminder in production) is
    # unvoiced -> must be restyled by the Revoicer before TTS ever sees it.
    skill = FakeSkill(speech="it is noon", voiced=False)
    tts = FakeTTS()
    revoicer = TaggingRevoicer()
    pipeline = _pipeline(
        FakeAudioIn(3), FakeDetector(), skill, tts, FakeOut(), AudioArbiter(),
        revoicer=revoicer,
    )

    await pipeline.run()

    assert tts.spoke == ["<<REVOICED>>it is noon"]
    assert TaggingRevoicer.is_tagged(tts.spoke[0])
    assert revoicer.calls == ["it is noon"]


# --- Path 2/4: persona-marked LLM skill result -------------------------------


async def test_persona_marked_llm_reply_bypasses_revoicer():
    # An LLM-answered reply that already carries the persona voice
    # (SkillResult.voiced=True, e.g. GeneralSkill's chat() answer) must reach
    # TTS untouched by the Revoicer -- restyling an already-styled reply would
    # double-flavor it.
    skill = FakeSkill(speech="a persona flavored answer", voiced=True)
    tts = FakeTTS()
    revoicer = TaggingRevoicer()
    pipeline = _pipeline(
        FakeAudioIn(3), FakeDetector(), skill, tts, FakeOut(), AudioArbiter(),
        revoicer=revoicer,
    )

    await pipeline.run()

    assert tts.spoke == ["a persona flavored answer"]  # byte-identical, no tag
    assert not TaggingRevoicer.is_tagged(tts.spoke[0])
    assert revoicer.calls == []  # never sent through the revoicer


# --- Path 3/4: verify feedback via on_say ------------------------------------


async def test_verify_filler_bypasses_revoicer_final_reply_is_revoiced():
    # A verify pre-reject speaks a filler mid-turn through `on_say` -- the real
    # pipeline's `_speak` bound method, threaded into the real Orchestrator's
    # verify loop exactly as app.py wires it. The filler is already
    # persona-flavored at its source (Orchestrator._speak_filler passes
    # voiced=True) and must bypass the Revoicer; the eventual (unvoiced) skill
    # reply must not.
    echo = EchoSkill()
    reg = _reg(echo, default=FallbackSkill())
    llm = ScriptedLLM(
        tool_responses=[_echo_call(), _echo_call()],  # decide0, re-decide1
        complete_responses=[
            _verdict("reject", feedback="let me double check that"),  # pre0
            _verdict("approve"),  # pre1
            _verdict("approve"),  # post1
        ],
    )
    orchestrator = Orchestrator(llm, reg, tool_mode="native", verify=VerifyConfig())
    tts = FakeTTS()
    revoicer = TaggingRevoicer()
    pipeline = _pipeline(
        FakeAudioIn(3), FakeDetector(), FakeSkill(), tts, FakeOut(), AudioArbiter(),
        orchestrator=orchestrator, revoicer=revoicer,
    )

    await pipeline.run()

    assert tts.spoke == ["let me double check that", "<<REVOICED>>echoed"]
    assert not TaggingRevoicer.is_tagged(tts.spoke[0])  # filler bypassed the revoicer
    assert TaggingRevoicer.is_tagged(tts.spoke[1])  # final reply was revoiced
    assert revoicer.calls == ["echoed"]  # the filler never reached the revoicer


# --- Path 4/4: pipeline error / can't-help / reply-error canned() lines -----


async def test_skill_exception_canned_error_bypasses_revoicer():
    tts = FakeTTS()
    revoicer = TaggingRevoicer()
    pipeline = _pipeline(
        FakeAudioIn(3), FakeDetector(), RaisingSkill(), tts, FakeOut(), AudioArbiter(),
        revoicer=revoicer,
    )

    await pipeline.run()

    assert tts.spoke == ["Sorry, something went wrong."]
    assert not TaggingRevoicer.is_tagged(tts.spoke[0])
    assert revoicer.calls == []


async def test_cant_help_canned_bypasses_revoicer():
    tts = FakeTTS()
    revoicer = TaggingRevoicer()
    pipeline = _pipeline(
        FakeAudioIn(3), FakeDetector(), FakeSkill(), tts, FakeOut(), AudioArbiter(),
        orchestrator=NoResultOrchestrator(), revoicer=revoicer,
    )

    await pipeline.run()

    assert tts.spoke == ["Sorry, I can't help with that yet."]
    assert not TaggingRevoicer.is_tagged(tts.spoke[0])
    assert revoicer.calls == []


async def test_reply_error_generic_canned_bypasses_revoicer():
    # The unvoiced "confirm?" prompt is revoiced; the canned error line that
    # follows the reply-handler crash is voiced at its source and must not be.
    skill = RaisingReplySkill()
    stt = FakeSTT(transcripts=["turn off for 20 minutes", "confirm"])
    tts = FakeTTS()
    revoicer = TaggingRevoicer()
    pipeline = _pipeline(
        FakeAudioIn(6), FakeDetector(), skill, tts, FakeOut(), AudioArbiter(),
        stt=stt, conversation_enabled=False, revoicer=revoicer,
    )

    await pipeline.run()

    assert tts.spoke == ["<<REVOICED>>confirm?", "Sorry, something went wrong."]
    assert revoicer.calls == ["confirm?"]


# --- `_speak` default-unvoiced pin -------------------------------------------


async def test_speak_defaults_to_unvoiced():
    # Pin: a future bare `_speak("...")` call site (a literal that forgets the
    # voiced kwarg) must land in the Revoicer by default, not bypass it.
    revoicer = TaggingRevoicer()
    pipeline = _pipeline(
        FakeAudioIn(0), FakeDetector(fires=0), FakeSkill(), FakeTTS(), FakeOut(),
        AudioArbiter(), revoicer=revoicer,
    )

    await pipeline._speak("bare call")

    assert revoicer.calls == ["bare call"]
