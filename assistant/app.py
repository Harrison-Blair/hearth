"""Daemon entrypoint.

Boots, loads config, resolves audio devices, plays a startup chime, then runs the
full voice pipeline: wake word -> record -> transcribe -> route -> LLM -> speak.
"""

from __future__ import annotations

import asyncio
import logging
import sys

from assistant.audio.devices import DeviceSelection, select_devices
from assistant.audio.earcon import checkin, chime, descending, no_speech
from assistant.audio.recorder import VadRecorder
from assistant.audio.aec import build_aec
from assistant.audio.mic_hub import MicHub
from assistant.audio.sounddevice_io import SoundDeviceIn, SoundDeviceOut
from assistant.calendar.blocklist import EventBlocklist
from assistant.calendar.google_calendar import GoogleCalendar
from assistant.core.arbiter import AudioArbiter
from assistant.core.config import Config, LlmConfig, WebSearchConfig
from assistant.core.control import ControlChannel
from assistant.core.logging import setup_logging
from assistant.core import persona
from assistant.core.orchestrator import Orchestrator
from assistant.core.pipeline import VoicePipeline
from assistant.core.revoice import Revoicer
from assistant.core.selfupdate import restart_in_place
from assistant.core.speech import Speaker
from assistant.core.standdown import StandDown
from assistant.core.state import NullStateEmitter, StateEmitter
from assistant.llm.base import LLMProvider
from assistant.llm.fallback_provider import FallbackLLMProvider
from assistant.llm.ollama_provider import OllamaProvider
from assistant.llm.opencode_zen_provider import OpenCodeZenProvider
from assistant.scheduling.calendar_watcher import CalendarWatcher
from assistant.scheduling.scheduler import ReminderScheduler
from assistant.search.base import SearchProvider
from assistant.search.ddgs_provider import DdgsSearch
from assistant.search.exa import ExaSearch
from assistant.search.multi import MultiSearch
from assistant.search.tavily import TavilySearch
from assistant.search.wikipedia import WikipediaSearch
from assistant.skills.base import SkillRegistry
from assistant.skills.calendar import CalendarSkill
from assistant.skills.clock import ClockSkill
from assistant.skills.general import GeneralSkill
from assistant.skills.reminder import ReminderSkill
from assistant.skills.stand_down import StandDownSkill
from assistant.skills.timer import TimerSkill
from assistant.skills.update import UpdateSkill
from assistant.skills.weather import WeatherSkill
from assistant.skills.web_search import WebSearchSkill
from assistant.storage.calendar_state import CalendarStateStore
from assistant.storage.reminders import ReminderStore
from assistant.stt.faster_whisper_stt import FasterWhisperSTT
from assistant.tts.piper_tts import PiperTTS
from assistant.wake.livekit_detector import LivekitWakeDetector
from assistant.weather.open_meteo import OpenMeteoWeather

log = logging.getLogger("assistant")


def _build_search(cfg: WebSearchConfig) -> tuple[SearchProvider, dict[str, SearchProvider]]:
    """Construct the keyless provider fan-out (unchanged) plus the routed
    keyed-provider map: query_type -> AI-first provider (Tavily for "factual",
    Exa for "semantic"). A route is present only when its API key is configured;
    an empty map means keyless-only behavior, identical to today."""
    factories = {
        "wikipedia": lambda: WikipediaSearch(
            language=cfg.language,
            result_count=cfg.result_count,
            timeout=cfg.timeout,
            max_snippet_chars=cfg.max_snippet_chars,
        ),
        "ddgs": lambda: DdgsSearch(
            region=cfg.region,
            timeout=cfg.timeout,
            max_snippet_chars=cfg.max_snippet_chars,
        ),
    }
    providers: list[SearchProvider] = []
    names: list[str] = []
    for name in cfg.providers:
        factory = factories.get(name)
        if factory is None:
            log.warning("Unknown web search provider %r; skipping", name)
            continue
        providers.append(factory())
        names.append(name)
    if not providers:
        log.warning("No usable web search providers configured; falling back to wikipedia")
        providers, names = [factories["wikipedia"]()], ["wikipedia"]
    log.info(
        "Web search: %s (agentic, max_rounds=%d)", "+".join(names), cfg.max_rounds
    )
    keyless = providers[0] if len(providers) == 1 else MultiSearch(providers, max_results=cfg.max_results)

    routes: dict[str, SearchProvider] = {}
    if cfg.tavily_api_key:
        routes["factual"] = TavilySearch(
            api_key=cfg.tavily_api_key,
            endpoint=cfg.tavily_endpoint,
            timeout=cfg.timeout,
            max_snippet_chars=cfg.max_snippet_chars,
        )
    if cfg.exa_api_key:
        routes["semantic"] = ExaSearch(
            api_key=cfg.exa_api_key,
            timeout=cfg.timeout,
            max_snippet_chars=cfg.max_snippet_chars,
        )
    if not routes:
        log.warning(
            "No web search API keys configured (tavily_api_key/exa_api_key empty); "
            "using keyless search only"
        )
    return keyless, routes


def _build_llm(cfg: LlmConfig) -> LLMProvider:
    """Construct the configured LLM provider, wrapping in a fallback when one is
    named. Unknown provider names fall back to Ollama with a warning so the daemon
    still boots."""
    primary = _build_one_llm(cfg, cfg.provider, cfg.model)
    if not cfg.fallback or cfg.fallback == cfg.provider:
        return primary
    fb_model = cfg.fallback_model or cfg.model
    fallback = _build_one_llm(cfg, cfg.fallback, fb_model)
    return FallbackLLMProvider(primary, fallback)


def _build_one_llm(cfg: LlmConfig, provider: str, model: str) -> LLMProvider:
    if provider == "opencode-zen":
        if not cfg.api_key:
            log.warning(
                "OpenCode Zen provider selected but llm.api_key is empty; set "
                "ASSISTANT_LLM__API_KEY. Requests will fail with 401."
            )
        return OpenCodeZenProvider(
            model=model,
            api_key=cfg.api_key,
            base_url=cfg.base_url,
            timeout=cfg.timeout,
            health_timeout=cfg.health_timeout,
            max_retries=cfg.max_retries,
        )
    if provider != "ollama":
        log.warning("Unknown llm.provider %r; defaulting to ollama", provider)
    return OllamaProvider(
        model,
        cfg.host,
        cfg.timeout,
        cfg.health_timeout,
        cfg.num_ctx,
        cfg.think,
    )


def _config_dump(config: Config) -> dict:
    """Effective config for the boot trace record, with personal identifiers masked."""
    dump = config.model_dump()
    for key in ("personal_calendar_id", "calcifer_calendar_id"):
        if dump["calendar"].get(key):
            dump["calendar"][key] = "***"
    if dump["llm"].get("api_key"):
        dump["llm"]["api_key"] = "***"
    return dump


def main() -> None:
    config = Config()
    setup_logging(
        config.logging.level,
        log_dir=config.logging.dir if config.logging.file_enabled else None,
        file_level=config.logging.file_level,
        rotate_max_bytes=config.logging.rotate_max_bytes,
        rotate_backups=config.logging.rotate_backups,
        runs_to_keep=config.logging.runs_to_keep,
    )

    llm_endpoint = (
        config.llm.base_url if config.llm.provider == "opencode-zen" else config.llm.host
    )
    log.info("Personal assistant booting (v%s)", __import__("assistant").__version__)
    log.info(
        "Config: wake=%r models=%s | stt=%s | llm=%s/%s@%s | tts=%s",
        ", ".join(config.wake.phrases()),
        config.wake.model_refs(),
        config.stt.model,
        config.llm.provider,
        config.llm.model,
        llm_endpoint,
        config.tts.model_path or config.tts.voice,
        extra={"data": {"kind": "boot.config", "config": _config_dump(config)}},
    )

    try:
        devices = select_devices(config.audio)
    except Exception as exc:  # noqa: BLE001 - surface device problems clearly at boot
        log.error("Audio device selection failed: %s", exc)
        return

    try:
        asyncio.run(_run(config, devices))
    except KeyboardInterrupt:
        log.info("Shutting down.")


async def _run(config: Config, devices: DeviceSelection) -> None:
    if not config.tts.model_path:
        log.error("No TTS model configured (tts.model_path); cannot speak. Aborting.")
        return

    # Voice out. When AEC is enabled, everything the speaker plays is also fed
    # to the canceller as the echo reference for the mic (see audio/aec.py);
    # build_aec degrades to None (passthrough) when the native lib is missing.
    aec = None
    if config.aec.enabled:
        aec = build_aec(
            sample_rate=config.audio.sample_rate,
            frame_ms=config.aec.frame_ms,
            filter_length_ms=config.aec.filter_length_ms,
            extra_delay_ms=config.aec.extra_delay_ms,
        )
    tts = PiperTTS(config.tts.model_path, config.tts.length_scale)
    out = SoundDeviceOut(
        devices.output.index, tts.sample_rate, volume=config.audio.output_volume,
        far_sink=aec,
    )
    arbiter = AudioArbiter()
    # Shared "stand down" state: the skill engages it, the pipeline/scheduler/
    # watcher go silent while it's active, the TUI's RESUME verb clears it.
    standdown = StandDown()

    # LLM + routing + skills.
    llm = _build_llm(config.llm)
    llm_healthy = await llm.health()
    if not llm_healthy:
        if config.llm.provider == "opencode-zen":
            log.warning(
                "OpenCode Zen not ready (base_url=%s, model=%s); answers will fail "
                "until it's reachable. Verify ASSISTANT_LLM__API_KEY and network.",
                config.llm.base_url,
                config.llm.model,
            )
        else:
            log.warning(
                "Ollama not ready (host=%s, model=%s); answers will fail until it's up. "
                "Run `ollama serve` and `ollama pull %s`.",
                config.llm.host,
                config.llm.model,
                config.llm.model,
            )
    store = ReminderStore(config.storage.db_path)
    search, search_routes = _build_search(config.web_search)
    weather = OpenMeteoWeather(
        forecast_endpoint=config.weather.forecast_endpoint,
        geocoding_endpoint=config.weather.geocoding_endpoint,
        temperature_unit=config.weather.temperature_unit,
        wind_speed_unit=config.weather.wind_speed_unit,
        precipitation_unit=config.weather.precipitation_unit,
        timezone=config.weather.timezone,
        forecast_days=config.weather.forecast_days,
        timeout=config.weather.timeout,
    )
    persona_suffix = persona.suffix(
        enabled=config.persona.enabled, strength=config.persona.strength
    )
    # Restyles a not-already-persona'd skill reply live at the pipeline's speak
    # choke point (core/revoice.py). Seeded from the boot health check above, so
    # a down LLM never adds revoice latency to the first replies.
    revoicer = Revoicer(
        llm,
        persona.persona_segment(config.persona.strength),
        enabled=config.persona.enabled and config.persona.revoice_enabled,
        timeout_s=config.persona.revoice_timeout_s,
        healthy=llm_healthy,
    )
    registry = SkillRegistry()
    registry.register(ClockSkill())
    registry.register(ReminderSkill(store, llm))
    registry.register(TimerSkill(store))
    registry.register(StandDownSkill(standdown))
    registry.register(UpdateSkill(persona_enabled=config.persona.enabled))
    registry.register(WebSearchSkill(
        search,
        llm,
        count=config.web_search.result_count,
        max_rounds=config.web_search.max_rounds,
        speaker=Speaker(tts, out),
        progress_updates=config.web_search.progress_updates,
        persona_suffix=persona_suffix,
        routes=search_routes,
    ))
    registry.register(WeatherSkill(
        weather,
        llm,
        home_lat=config.weather.latitude,
        home_lon=config.weather.longitude,
        home_name=config.weather.location_name,
        persona_suffix=persona_suffix,
    ))
    calendar_provider = None
    calendar_watcher = None
    calendar_state = None
    if config.calendar.enabled:
        calendar_ids = [
            config.calendar.personal_calendar_id,
            config.calendar.calcifer_calendar_id,
        ]
        calendar_provider = GoogleCalendar(
            config.calendar.credentials_path,
            timeout=config.calendar.timeout,
            health_calendar_ids=calendar_ids,
        )
        # Warn, don't bar: the skill and watcher degrade per-call with a spoken
        # failure, matching the Ollama health check above.
        if not await calendar_provider.health():
            log.warning(
                "Google Calendar not reachable (creds=%s); calendar commands will "
                "fail with a spoken message until it's fixed",
                config.calendar.credentials_path,
            )
        calendar_state = CalendarStateStore(config.storage.db_path)
        calendar_blocklist = EventBlocklist(
            calendar_state,
            config_patterns=config.calendar.blocked_titles,
            hidden_tag=config.calendar.hidden_tag,
        )
        calendar_watcher = CalendarWatcher(
            calendar_provider,
            calendar_state,
            tts,
            out,
            arbiter,
            blocklist=calendar_blocklist,
            calendar_ids=calendar_ids,
            poll_seconds=config.calendar.watcher_poll_seconds,
            lead_minutes=config.calendar.watcher_lead_minutes,
            enabled=config.calendar.watcher_enabled,
            standdown=standdown,
            revoicer=revoicer,
        )
        registry.register(CalendarSkill(
            calendar_provider,
            llm,
            store,
            calendar_watcher,
            blocklist=calendar_blocklist,
            personal_id=config.calendar.personal_calendar_id,
            calcifer_id=config.calendar.calcifer_calendar_id,
        ))
    registry.register(
        GeneralSkill(
            llm, config.llm.system_prompt, persona_suffix=persona_suffix,
            persona_enabled=config.persona.enabled,
        ),
        default=True,
    )
    orchestrator = Orchestrator(
        llm,
        registry,
        tool_mode=config.agent.tool_mode,
        max_tool_rounds=config.agent.max_tool_rounds,
        system_prompt=config.llm.system_prompt,
        turn_timeout_s=config.agent.turn_timeout_s,
        delegate_direct_answers=config.persona.enabled,
        verify=config.verify,
        persona_suffix=persona_suffix,
    )

    # Startup chime.
    log.info("Playing startup chime")
    await out.play(chime(tts.sample_rate))

    # Voice in: wake -> record -> transcribe.
    detector = LivekitWakeDetector(
        config.wake.model_refs(),
        config.wake.threshold,
        score_interval=config.wake.score_interval,
        trigger_frames=config.wake.trigger_frames,
    )
    stt = FasterWhisperSTT(
        config.stt.model,
        config.stt.compute_type,
        config.stt.language,
        config.stt.beam_size,
        vad_filter=config.stt.vad_filter,
        condition_on_previous_text=config.stt.condition_on_previous_text,
        initial_prompt=config.stt.initial_prompt,
        device=config.stt.device,
        cpu_threads=config.stt.cpu_threads,
        no_speech_threshold=config.stt.no_speech_threshold,
        log_prob_threshold=config.stt.log_prob_threshold,
    )
    # The hub fans the mic out: the pipeline's stream stays the single consumer,
    # while a tap lets wake scoring continue during playback (barge-in). With
    # AEC on, every frame is echo-cancelled before the recorder and the tap.
    audio_in = MicHub(
        SoundDeviceIn(
            devices.input.index,
            sample_rate=config.audio.sample_rate,
            block_size=config.audio.block_size,
            channels=config.audio.channels,
        ),
        processor=aec.process if aec is not None else None,
    )
    recorder = VadRecorder(
        sample_rate=config.audio.sample_rate,
        aggressiveness=config.recorder.aggressiveness,
        silence_ms=config.recorder.silence_ms,
        max_ms=config.recorder.max_ms,
        start_timeout_ms=config.recorder.start_timeout_ms,
        min_speech_ms=config.recorder.min_speech_ms,
    )

    # Spoken wake acknowledgements, synthesized once and cached as PCM so they play
    # with earcon-latency (no per-turn TTS). One is picked at random per wake:
    # confident wakes draw from ack_phrases, low-score wakes from unsure_ack_phrases.
    async def _synth_acks(phrases: list[str]) -> list[bytes]:
        acks: list[bytes] = []
        for phrase in phrases:
            try:
                acks.append(await tts.synthesize(phrase))
            except Exception as exc:  # noqa: BLE001 - skip a bad phrase, never block boot
                log.warning("Could not synthesize wake acknowledgement %r: %s", phrase, exc)
        return acks

    wake_acks = await _synth_acks(config.tts.ack_phrases)
    unsure_wake_acks = await _synth_acks(config.tts.unsure_ack_phrases)
    pipeline = VoicePipeline(
        audio_in,
        detector,
        recorder,
        stt,
        orchestrator,
        tts,
        out,
        arbiter,
        preroll_frames=config.recorder.preroll_frames,
        sample_rate=config.audio.sample_rate,
        no_speech_earcon=no_speech(tts.sample_rate),
        wake_earcons=wake_acks,
        unsure_wake_earcons=unsure_wake_acks,
        wake_confident_threshold=config.wake.confident_threshold,
        end_earcon=descending(tts.sample_rate),
        normalize=config.audio.normalize,
        normalize_target_peak=config.audio.normalize_target_peak,
        normalize_rms_floor=config.audio.normalize_rms_floor,
        min_transcribe_rms=config.audio.min_transcribe_rms,
        hallucination_phrases=config.stt.hallucination_phrases,
        hallucination_max_rms=config.stt.hallucination_max_rms,
        conversation_enabled=config.conversation.enabled,
        followup_window_ms=config.conversation.followup_window_ms,
        max_history_turns=config.conversation.max_history_turns,
        llm=llm,
        decision_enabled=config.conversation.decision_enabled,
        decision_timeout_s=config.conversation.decision_timeout_s,
        decision_prompt=config.conversation.decision_prompt,
        decline_phrases=config.conversation.decline_phrases,
        confirm_earcon=checkin(tts.sample_rate),
        end_phrases=config.conversation.end_phrases,
        ack_delay_s=config.tts.ack_delay_s,
        # State feed to the monitor TUI, which reads our stdout. Suppressed on an
        # interactive terminal (standalone), where it would just be log noise.
        state_emitter=NullStateEmitter() if sys.stdout.isatty() else StateEmitter(),
        standdown=standdown,
        barge_in_enabled=config.barge_in.enabled,
        barge_in_threshold=config.barge_in.threshold,
        barge_in_trigger_frames=config.barge_in.trigger_frames,
        barge_in_announcements=config.barge_in.announcements,
        restart_in_place=restart_in_place,
        revoicer=revoicer,
        persona_enabled=config.persona.enabled,
    )
    scheduler = ReminderScheduler(
        store, tts, out, arbiter, poll_seconds=config.scheduling.poll_seconds,
        standdown=standdown, revoicer=revoicer,
    )
    # Optional control channel: line commands on stdin (typed commands, live
    # volume) from the monitor TUI when the daemon runs as its child.
    control = ControlChannel(pipeline, out, Speaker(tts, out), arbiter, standdown)

    # Pipeline (wake -> reply), scheduler (proactive reminders), calendar watcher
    # (proactive event announcements, when enabled), and control channel share the
    # one event loop, audio output, and arbiter; all run until interrupted.
    tasks = [pipeline.run(), scheduler.run(), control.run()]
    if calendar_watcher is not None:
        tasks.append(calendar_watcher.run())
    try:
        await asyncio.gather(*tasks)
    finally:
        store.close()
        if calendar_state is not None:
            calendar_state.close()
        await llm.aclose()
        await search.aclose()
        for route_provider in search_routes.values():
            await route_provider.aclose()
        await weather.aclose()
        if calendar_provider is not None:
            await calendar_provider.aclose()


if __name__ == "__main__":
    main()
