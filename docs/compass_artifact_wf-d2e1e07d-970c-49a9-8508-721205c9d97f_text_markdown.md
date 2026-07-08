# Architecting a Self-Hosted, Privacy-Preserving Personal Assistant LLM Agent (2025–2026)

## TL;DR
- **Build a single long-running agent process, not a multi-agent swarm.** For a single-user assistant on consumer hardware, a disciplined single-agent ReAct loop — with a hard per-tool call cap, a thin planner/reflection layer only for genuinely multi-step tasks, and a deterministic fast-path for routine commands — is the highest-confidence architecture. Multi-agent orchestration's documented wins are concentrated in enterprise/incident-response settings and cost extra tokens and latency you cannot spare locally.
- **Split the stack across three tiers over a clean protocol boundary.** Edge device (wake word + audio I/O) → home inference server (STT, LLM, TTS, memory/RAG) → knowledge base (Obsidian Markdown vault indexed with hybrid retrieval). Home Assistant's Wyoming protocol is the best-proven abstraction boundary; the model layer should be a Qwen3-class 14B for reliable tool-calling at roughly 22 tok/s on a 16GB AMD card.
- **Memory and voice are where projects fail, not model quality.** Adopt a hybrid memory design (raw-episode store + extracted profile facts + RAG over the vault), keep responses terse for voice, and budget end-to-end voice latency explicitly (~1–2 s achievable locally on GPU; ~8 s on a Pi CPU). Treat prompt injection through personal data and tool outputs as the primary security risk and sandbox all tool execution.

## Key Findings
1. **Single-agent loops dominate production reality; multi-agent gains are context-specific.** ReAct remains the default and, per practitioner consensus, the majority of production agents are ReAct loops. Multi-agent orchestration shows dramatic reliability gains in specific studies (e.g., incident response) but adds token cost, latency, and coordination complexity that rarely pay off for a single-user assistant.
2. **Tool-calling reliability is model-gated and drops sharply below ~7–9B params.** Qwen3/Qwen3.5 are the most reliable local tool-callers per the Berkeley Function Calling Leaderboard (BFCL) and practitioner reports; there is a clear capability cliff below the 7–9B mark. gpt-oss-20b is a strong speed/reliability pick on 16GB.
3. **The agent-memory field has professionalized into a distinct layer** with its own benchmarks (LongMemEval, LoCoMo) and frameworks (Mem0, Zep/Graphiti, Letta/MemGPT). No single winner: choose by persistence model. For a local vault-centric assistant, a hybrid of RAG-over-Markdown plus a lightweight fact/profile store is the pragmatic core.
4. **Hybrid retrieval + reranking is the consensus RAG upgrade** (retrieve ~20–50 candidates via vector+BM25, rerank with a cross-encoder to top-5), improving answer quality meaningfully over naive top-k.
5. **AMD ROCm is now genuinely usable for inference** (ROCm 7.2, released January 2026), with llama.cpp and vLLM the safest paths; Ollama's AMD support is improving but historically inconsistent. A 16GB RX 7800 XT runs Qwen2.5-14B Q4_K_M at ~22–23 tok/s.
6. **Home Assistant's Assist/Wyoming stack is the reference architecture** for local voice, with the key lesson being service decomposition over a protocol boundary and a deterministic intent fast-path before invoking the LLM.
7. **Prompt injection via untrusted content (notes, emails, tool outputs) is the dominant security failure mode** — the #1 entry in the OWASP LLM Top 10 — with multiple 2025 real-world MCP incidents. Sandboxing, least-privilege tools, and human-in-the-loop confirmation are mandatory.

## Details

### Pillar 1 — Agent Orchestration & Control Flow

**The design space.** Practitioners converge on four single-agent patterns and a family of multi-agent topologies:
- **ReAct (Reason+Act):** interleaved Thought → Action → Observation loop (Yao et al., 2022). One LLM call per step; transparent, debuggable, the default. Fails via the "verifier stall" — re-calling the same tool with reworded args — which is why a **per-tool call cap** (not just a global step cap) is essential (DEV Community / gabrielanhaia, 2026).
- **Plan-and-Execute:** an explicit upfront plan then execution; gives "lookahead" that reduces myopia on long tasks at the cost of more prompts and a re-planning trigger to tune.
- **ReWOO:** decouples reasoning from observations to cut token use.
- **Reflection/Reflexion:** a self-critique pass; improves accuracy on high-stakes outputs but roughly doubles token consumption per cycle and stalls with vague quality criteria.

**Multi-agent orchestration** (orchestrator-worker, hierarchical, sequential, event-driven) shows strong results in specific studies. Drammeh et al., "Multi-Agent LLM Orchestration…for Incident Response" (arXiv:2511.15755, v2 Jan 2026), report that their MyAntFarm.ai framework achieved a "100% actionable recommendation rate versus 1.7% for single-agent approaches, an 80 times improvement in action specificity and 140 times improvement in solution correctness," with "zero quality variance across all trials" at ~40 s latency for both architectures — but the same literature stresses governance overhead, higher total token use, and coordination failure modes. For a single-user personal assistant, this is over-engineering: the reliability wins are largely reproducible with a single agent plus good tools and evals.

**Recommended control flow for a personal assistant:**
1. **Deterministic fast-path first.** Route routine commands (timers, lights, "what time is it") to a deterministic intent parser before touching the LLM. Home Assistant's `prefer_local_intents: true` embodies this; a practitioner post-mortem calls it "the most important setting most guides skip over" (Joe Karlsson, 2025).
2. **Single ReAct agent** as the reasoning core for open-ended queries and tool use, with hard caps: global step cap + per-tool call cap + wall-clock timeout.
3. **Optional thin planner** only for tasks the model itself flags as multi-step; a Reasoner-Planner supervising a ReAct executor (arXiv 2512.03560) is a documented pattern if needed.
4. **Long-running process, not request-response.** The assistant should be a persistent service holding session state, a memory connection, and warm model handles — not a cold Lambda-style invocation.

**Tool interface.** MCP (Model Context Protocol) is the emerging standard for exposing tools; it also introduces a large attack surface (see Pillar 5). Keep tool schemas tight and validate all tool inputs before execution — "LLMs will confidently call tools with wrong parameters."

**Ranked options (criteria: maturity, constrained-hardware fit, maintainability, community health; confidence in parentheses):**
1. **Single ReAct loop + deterministic fast-path + call caps** — best all-round for this use case. (High confidence)
2. **ReAct + thin planner/reflection for flagged multi-step tasks** — add only when evals show single-loop failures. (Medium-high)
3. **Multi-agent orchestration** — defer; revisit only if the assistant grows distinct heavy sub-domains. (Medium, and against for now)

### Pillar 2 — Memory & RAG

**The distinction that matters:** short-term conversational memory (context window), long-term episodic/semantic memory (across sessions), and RAG over a static-ish personal corpus (the Obsidian vault) are three different problems. A robust assistant needs all three, wired together.

**Framework landscape (scores are self-reported by vendors/projects unless noted — treat as directional):**
- **Mem0** — hybrid vector+graph+key-value with automatic extraction; the largest community, having surpassed 59,500 GitHub stars (Apache 2.0) as of mid-2026, with 13M+ Python downloads and a $24M raise (including a $20M Series A led by Basis Set Ventures, Oct 2025, per TechCrunch). Its Sept-2025 algorithm paper self-reports 94.8 on LongMemEval and 91.6 on LoCoMo. Best for low-friction personalization; graph memory requires the paid tier, OSS gives the vector layer.
- **Zep / Graphiti** — temporal knowledge graph with fact-validity windows; strong on "what was true when" queries. The Zep/Graphiti paper (arXiv 2501.13956) reports that "on GPT-4o, Zep scores 63.8% and Mem0 scores 49.0%," a 14.8-point gap; note a separate contested LoCoMo exchange (Zep 84% → Mem0 corrected to 58.44% → Zep counter-claimed 75.14%), which underscores why you must run your own evals. Graphiti is open; full Zep is increasingly SaaS.
- **Letta (formerly MemGPT)** — OS-inspired tiered memory (core=RAM, recall=cache, archival=disk) that the agent self-manages via tools; fully self-hostable with 13,000+ GitHub stars under Apache-2.0. Powerful but agent-reasoning errors can corrupt memory, and every memory op costs inference tokens.
- **MemMachine, MIRIX, MemPalace** — newer research/OSS systems; MemPalace notably local-first and verbatim (self-reported strong LongMemEval).

**LongMemEval and LoCoMo** are the standard benchmarks (both focus on chat history, not task execution — a stated limitation). Vendor-reported scores disagree; the cross-cutting practitioner advice is to **run evals on your own workload** and **keep the raw event stream in your own store** (Postgres/SQLite/files) so the framework is just an index you can re-ingest — avoiding lock-in.

**The Obsidian-vault–specific pattern.** Two schools of thought, and they genuinely disagree:
- **RAG school:** index the vault with a local embedding model (e.g., nomic-embed-text), hybrid vector+BM25 search, cross-encoder rerank, optionally expand along `[[wikilinks]]` (GraphRAG). Implemented by ObsidianRAG, obsidian-local-llm-hub, and others. Best for large vaults and fuzzy semantic recall.
- **"LLM Wiki" school (Karpathy pattern):** have the agent maintain a curated, interlinked Markdown wiki and let a capable model read files directly, no vector DB. Reportedly handles ~100 articles / 400K words without RAG. Best for smaller corpora and agents with filesystem access; degrades as corpus grows.

For a developer with an Obsidian vault, the pragmatic answer is **hybrid**: RAG for retrieval at scale + a small curated set of "always-loaded" profile/preference notes + agent write-back (capture new facts into an inbox folder for human review, as Nooscope does). A recurring design lesson: keep LLM-generated content in a separate space from your canonical personal notes ("contamination mitigation," attributed to Obsidian co-creator Steph Ango).

**Memory writes, decay, retrieval quality, privacy:**
- *Writes:* passive extraction (Mem0) is predictable and token-cheap; agentic self-editing (Letta) is adaptive but non-deterministic. Pin a cheap model for extraction and batch writes.
- *Decay/forgetting:* use consolidation (dedup/clustering) and adaptive token-target forgetting; the human-inspired memory literature (arXiv 2605.08538) ablates these.
- *Retrieval quality:* hybrid + rerank is the single biggest lever (below).
- *Privacy:* everything local; the whole point of a local vault is that it's local — routing it through cloud embeddings/LLMs is "a concession," not a feature (Rodney Dyer, Nooscope).

**RAG best-practice pipeline (stable fundamentals, still current):** contextual chunking → embed → store → hybrid retrieve top-20–50 → cross-encoder rerank → top-5 to LLM. This reportedly improves RAGAS metrics by 15–30%. Bi-encoder retrieval is fast but coarse; cross-encoder reranking is "the difference between 'topically similar' and 'actually answers the question.'"

**Comparison matrix (memory/RAG approaches):**

| Approach | Persistence model | Temporal reasoning | Local/self-host | Write cost | Best for | Key weakness |
|---|---|---|---|---|---|---|
| Context-window only | None (per session) | N/A | Yes | Free | Trivial cases | Forgets everything |
| RAG over vault (hybrid+rerank) | External corpus | Weak | Yes | Low | Personal knowledge queries | No cross-session personalization by itself |
| Mem0 | Vector+graph+KV, auto-extract | Moderate | Partial (graph=paid) | Low | Stable user facts | Graph gated; cloud-first UX |
| Zep/Graphiti | Temporal KG | Strong (validity windows) | Graphiti yes | High (LLM writes) | "As-of" facts, changing state | Write complexity, latency 50–150 ms |
| Letta/MemGPT | OS tiered (core/recall/archival) | Moderate | Yes (Apache 2.0) | High (agent tokens) | Long-running self-managed agents | Reasoning errors corrupt memory |
| LLM Wiki (Karpathy) | Curated Markdown | Manual | Yes | Medium (agent authoring) | Small vaults, filesystem agents | Doesn't scale past ~100s of docs |

**Ranked options (confidence):**
1. **RAG-over-vault (hybrid+rerank) + small profile-fact store + human-reviewed write-back** — best fit, fully local, low lock-in. (High)
2. **Add Letta** if you want the agent to self-manage a working set across days. (Medium)
3. **Add Zep/Graphiti** only if temporal "what-was-true-when" queries matter. (Medium)

### Pillar 3 — Local Inference on ~16GB VRAM (incl. AMD/ROCm)

**Model families competitive for agentic tool-use (last 12 months):**
- **Qwen3 / Qwen3.5 family** — the default for local tool-calling. Qwen3-32B scored ~69% BFCL v3 (FC); Qwen3-8B ~66%. Practitioners repeatedly cite Qwen as "the most reliable tool-callers I've used locally." A capability cliff appears below ~7–9B (Qwen3.5 4B drops to ~50% BFCL-V4, 2B to ~44%).
- **gpt-oss-20b** — OpenAI open-weight; ~13.7GB VRAM at ~42 tok/s on 16GB per one independent test; strong reasoning/tool-calling; MoE (~11.3GB MXFP4) fits 16GB.
- **Mistral Small 3.1 24B / Devstral** — capable but push the limits of 16GB.
- **Gemma 3/4** — good general models; Gemma tool-calling is prompt-based and less reliable than Qwen per BFCL.

**Quantization trade-offs:** Q4_K_M is the consensus sweet spot for 16GB — roughly halves memory vs FP16 with small quality loss (one source cites <2.8% for Gemma-class at Q4_K_M). Q5/Q6 rarely justify the VRAM on 16GB. Below Q4 quality degrades faster.

**Context-window management:** KV cache is the hidden VRAM cost; long context tightens the budget and slows generation (one test: gpt-oss-20b dropped 42→28.9 tok/s from short to ~49K tokens). Use the smallest context that solves the task; a 14B Q4_K_M leaves comfortable room at 8–32K on 16GB.

**Serving stacks:**
- **llama.cpp (HIP/ROCm)** — the safest, most portable AMD path; native GGUF; AMD upstreamed major RDNA/CDNA optimizations (a wavefront-size fix hardcoded at 32 that ignored AMD's 64-wide wavefronts) in July 2025.
- **vLLM (ROCm)** — production-grade, first-class ROCm support since v0.6.0; best throughput/batching but heavier setup.
- **Ollama** — easiest DX; AMD/ROCm support "has become solid" on Linux per some 2026 reports but was "inconsistent" with CPU fallback in others — verify against Ollama's AMD compatibility list.
- **LM Studio** — easy desktop; on AMD prefer its Vulkan backend on Windows.

**AMD/ROCm state (mid-2026):** ROCm 7.2 was released January 2026; starting with 7.2.2 (highlighted at CES 2026) AMD ships "one release package for both platforms," adding official RDNA4 support. Linux (Ubuntu 24.04) is strongly recommended; Windows is "second-class." NVIDIA still leads raw inference by ~15–30% at equivalent price, but AMD wins on VRAM-per-dollar. Caveats: FlashAttention ROCm ports lag; custom CUDA kernels in research code need hipify/forks.

**Measured 16GB AMD throughput (from independent benchmarks; card/quant/stack labeled):**

| Card (16GB) | Model / quant | Stack | Gen tok/s | Source |
|---|---|---|---|---|
| RX 7800 XT | Qwen2.5-14B Q4_K_M | llama.cpp (LocalScore) | ~22–23 | LocalScore community |
| RX 6800 XT | Qwen2.5-14B Q4_K_M | llama.cpp (LocalScore) | ~21 | LocalScore community |
| RX 6800 (16GB) | Qwen2.5-14B Q4_K_M | llama.cpp (LocalScore) | ~15 | LocalScore community |
| RX 7800 XT | Llama-2-7B Q4_0 | llama.cpp ROCm | ~101 (tg128) | llama.cpp Discussion #15021 |
| RX 7900 GRE | Llama-2-7B Q4_0 | llama.cpp ROCm | ~96 (tg128) | llama.cpp Discussion #15021 |

*Note:* RX 7900 GRE has no published measured 14B figure; by memory-bandwidth class it should land in the low-20s tok/s. LocalScore does not label ROCm vs Vulkan; a separate llama.cpp issue reports ROCm generation slower than Vulkan on RDNA3 — so real ROCm 14B numbers may sit at or slightly below these. Small-model 7B numbers (~100 tok/s) are an upper bound; real 14B agentic speeds are roughly 3–4× slower.

**Lightweight adaptation (optional):** LoRA/QLoRA fine-tuning of a small Qwen (e.g., 8B) is feasible on 16–24GB and can meaningfully improve tool-call formatting/persona consistency; the tool-calling literature shows RL/SFT boosting small-model multi-turn accuracy substantially (e.g., FunReason-MT on Qwen3-4B from 15.75%→56.5%). Treat as an optimization after the base system works, not a prerequisite.

**Ranked options (confidence):**
1. **Qwen3/3.5 14B-class at Q4_K_M on llama.cpp (ROCm), 8–16K context** — best reliability/speed/fit balance. (High)
2. **gpt-oss-20b** for faster, reasoning-heavy workloads if it fits your VRAM after KV cache. (Medium-high)
3. **vLLM** if you later need throughput/concurrency; **Ollama** for fastest prototyping. (Medium)

### Pillar 4 — Fully-Local Voice Pipeline

**Canonical stage flow:** mic → **VAD** (only stream when speech detected) → **wake word** → **STT** → **agent/LLM** → **TTS** → speaker, wired over a protocol so each stage is swappable.

**End-to-end architecture (representative self-hosted assistant):**

```
┌─────────────────────────┐        LAN / Wyoming (TCP)        ┌──────────────────────────────────────┐
│  EDGE DEVICE (Pi/SBC)   │  ───────────────────────────────► │        HOME INFERENCE SERVER          │
│  • Mic + speaker        │                                    │        (16GB AMD GPU, ROCm)           │
│  • VAD (stream gate)    │                                    │  ┌────────────────────────────────┐   │
│  • Wake word (micro-    │  audio stream after wake word ───► │  │ faster-whisper STT (GPU)       │   │
│    WakeWord on-device,  │                                    │  └───────────────┬────────────────┘   │
│    or openWakeWord on   │                                    │                  ▼                    │
│    server)              │  ◄─── streamed TTS audio chunks    │  ┌────────────────────────────────┐   │
└─────────────────────────┘                                    │  │ Deterministic intent fast-path │   │
                                                                │  │  (routine commands)            │   │
                                                                │  └───────────────┬────────────────┘   │
                                                                │        (fallthrough) ▼                │
                                                                │  ┌────────────────────────────────┐   │
                                                                │  │ Qwen3 14B ReAct agent           │   │
                                                                │  │  • tools (call caps, sandbox)   │◄──┼──┐
                                                                │  │  • memory: profile facts        │   │  │
                                                                │  └───────────────┬────────────────┘   │  │
                                                                │                  ▼                    │  │
                                                                │  ┌────────────────────────────────┐   │  │
                                                                │  │ Piper TTS (streaming) ─────────┼───┼──► (to edge)
                                                                │  └────────────────────────────────┘   │  │
                                                                └───────────────────────────────────────┘  │
                                                                          ▲  hybrid RAG (vector+BM25+rerank)│
                                                                          │                                 │
                                                                ┌─────────┴─────────────────────────────────┴─┐
                                                                │   KNOWLEDGE BASE: Obsidian Markdown vault    │
                                                                │   • embeddings (nomic-embed-text) + BM25     │
                                                                │   • cross-encoder reranker                   │
                                                                │   • inbox/ folder for approval-gated writes  │
                                                                └──────────────────────────────────────────────┘
```

**Component choices (open-source, proven):**
- **Wake word:** openWakeWord (MIT, CPU, custom words via Piper-generated training clips) is the best open option; microWakeWord for on-device (ESP32-S3); Porcupine (proprietary, free personal tier) has lower false positives. HA runs openWakeWord on the server so low-power satellites just stream audio.
- **STT:** faster-whisper (CTranslate2; ~4× faster on GPU than PyTorch Whisper) is the workhorse; whisper small (244M) is the assistant sweet spot. HA's Speech-to-Phrase is a fast closed-vocabulary alternative for pure command control (<1 s on a Pi 4). Guard against Whisper hallucinating on silence with an energy threshold / `--no-speech-threshold`.
- **TTS:** Piper (VITS→ONNX, Rhasspy team; active fork OHF-Voice/piper1-gpl) runs real-time even on a Pi; en_US-lessac-medium is a good default.

**Latency budget.** Natural human turn-taking gap is ~200 ms; production voice agents target <700–800 ms end-to-end, but a fully-local personal assistant realistically targets ~1–2 s on a GPU server (one guide reports ~1–2 s on an RTX 3060; ~5–8 s on a Pi 5). The dominant costs are **turn-taking/VAD** and **LLM time-to-first-token**, not STT/TTS. Streaming every stage (partial STT transcripts, token-streamed LLM, chunked TTS) is what makes it feel responsive; HA had to overhaul TTS for streaming precisely because LLM responses were verbose. Measured per-stage on an NPU SBC (RK3576): Whisper 0.626 s, Piper 0.474 s, Qwen2.5-1.5B 2.82 s.

**Latency-budget breakdown (representative local GPU-server pipeline, illustrative):**

| Stage | Typical local budget | Notes |
|---|---|---|
| Network (edge↔server, LAN) | 5–30 ms | Keep on same LAN |
| VAD + turn-taking | 150–300 ms | Biggest tunable; bad endpointing dominates perceived lag |
| Wake word | ~0 (runs continuously) | Server-side in HA model |
| STT (streaming) | 50–150 ms after speech end | Runs in parallel with speech |
| LLM TTFT | 200–500 ms (local 14B) | Model + prompt size dependent; the main lever |
| TTS time-to-first-audio | 100–475 ms | Piper ~0.47 s synth on SBC; faster on GPU |
| **End-to-end (perceived)** | **~1–2 s local GPU; up to ~8 s Pi CPU** | Streaming hides much of it |

**Edge vs server split.** Best-proven pattern (HA + Wyoming): the edge device does audio capture + optionally on-device wake word (microWakeWord); the server does STT, LLM, TTS, and memory. Wyoming is "a hard abstraction boundary" that hides hardware/model details — the RK3576 project keeps RKNN/NPU specifics sealed behind Wyoming-compatible TCP services so HA "treats them like any other local provider."

**Documented failure modes (voice):** Whisper hallucinating on silence; verbose reasoning models "narrating their thought process for five minutes straight" (a qwen3 think-mode disaster) — fix with tight system prompts, output sanitization, and disabling thinking mode; openWakeWord false positives/negatives with background noise/TV ("TV on in the other room? Expect some missed wake words"); a real HA regression (2025.5.x) where local TTS failed to announce after 10 min idle. Small models need help staying concise — voice has far less tolerance for rambling than text chat.

**Ranked options (confidence):**
1. **openWakeWord + faster-whisper (GPU) + Piper, wired via Wyoming, deterministic intent fast-path, LLM only for open queries** — the reference, most-maintained stack. (High)
2. **Speech-to-Phrase instead of Whisper** if you only need command-and-control and want sub-second on a Pi. (High for that scope)
3. **Full-duplex speech-to-speech models (e.g., Moshi)** for lower-latency conversational feel — but you lose the swappable-any-LLM/tool-use flexibility. (Medium, emerging)

### Cross-Cutting Workflows & Operational Practices

- **Evaluation before architecture.** "If you can't measure whether the agent succeeded, no pattern will save you." Build a small eval dataset from real interactions first; most agent failures are tool failures, not reasoning failures.
- **Observability.** Instrument with an OpenTelemetry-native tracer. Options: **Langfuse** (MIT, self-hostable, strong prompt management + evals), **Laminar** (Apache 2.0, agent-first, one-command self-host), **Arize Phoenix** (OTel/OpenInference), **LangSmith** (best if committed to LangChain/LangGraph; self-host is enterprise-only). For a privacy-first local build, prefer a self-hostable OSS tracer (Langfuse or Laminar).
- **Prompt & tool versioning.** Treat prompts as first-class versioned assets (Langfuse/LangSmith prompt management); version tool schemas alongside code. Use dataset-driven offline eval in CI to catch regressions before promoting a prompt/model change.
- **Regression testing.** Turn real failures into eval cases; run repeatable experiments; only promote versioned changes that beat baseline. LongMemEval/LoCoMo for memory; BFCL-style AST checks for tool-call formatting.
- **Sandboxing tool execution.** Run tools in isolated containers with least-privilege; disable "auto-run"/"always allow"; require human-in-the-loop confirmation for consequential actions (the MCP spec itself says there SHOULD be a human able to deny invocations).
- **Safe access to personal data.** Validate/sanitize inputs; apply semantic filtering to flag instruction-like patterns in retrieved notes/emails/tool outputs before they enter context; scope file access to specific directories.

### Notable Open-Source Projects & Lessons Learned

- **Home Assistant Assist + Wyoming** — the reference for local voice. Lessons: decompose services over a protocol; deterministic intent fast-path before LLM (`prefer_local_intents`); TTS must stream; AI is opt-in and privacy is not — a stated Open Home Foundation guideline. Voice Chapter 11 (Oct 2025, Mike Hansen) added dual wake-word/pipeline support (e.g., a local Speech-to-Phrase+Piper pipeline on one wake word, an LLM pipeline on another).
- **Leon** (17K+ GitHub stars, MIT) — long-running open-source personal assistant, rebuilding for 2.0 around tools, layered memory, context, and agentic execution with "smart / controlled / agent" modes and SKILL.md workflows; supports local and remote providers. Illustrates the hybrid classifier+LLM approach for speed/accuracy.
- **RK3576 local voice backend** (Hanzo Huang) — reproducible NPU edge stack (Whisper/Piper/openWakeWord/Qwen2.5-1.5B in Docker via Wyoming) with concrete per-stage latencies; demonstrates the protocol-boundary discipline.
- **RC-Home-Assistant-Low-VRAM** (RoyalCities) — GPU-accelerated HA voice stack tuned for low VRAM with persistent memory and follow-up conversation.
- **Obsidian-vault RAG projects** — ObsidianRAG (LangGraph, hybrid vector+BM25, cross-encoder rerank, GraphRAG wikilink expansion), obsidian-local-llm-hub (RAG + MCP + skills, approval-gated writes), Nooscope (local-first MCP sidecar with capture/log-thought write-back). Lesson: keep the index local and travel-with-the-vault; make writes approval-gated.
- **Karpathy "LLM Wiki" pattern** and derivatives (obsidian-wiki, SwarmVault) — the no-vector-DB alternative for smaller corpora.

### Risks, Open Problems & Failure Modes

- **Prompt injection is the #1 risk** — LLM01:2025 Prompt Injection, the top entry in the OWASP Top 10 for LLM Applications 2025 (OWASP GenAI Security Project), holding the #1 spot for the second consecutive edition. Real 2025 MCP incidents: the Supabase Cursor agent exfiltrating integration tokens via support tickets (privileged access + untrusted input + external channel); GitHub MCP issue-injection leaking private repos; CVE-2025-53773 (Copilot, CVSS 9.6) arbitrary command execution; CVE-2025-49596 (MCP Inspector, CVSS 9.4) unauthenticated RCE; and CVE-2025-6514 (CVSS 9.6), disclosed by JFrog Security Research July 2025, affecting mcp-remote versions 0.0.5–0.1.15 (patched in 0.1.16) — a package "downloaded more than 437,000 times" and the first documented real-world RCE against an MCP client. Mitigations: sandboxing, least-privilege, human-in-the-loop, input/output filtering, vetting third-party MCP packages.
- **Tool poisoning & rug-pulls** — malicious/mutable tool descriptions (MCPoison/CVE-2025-54136, CurXecute/CVE-2025-54135). Most MCP clients don't validate server metadata.
- **Memory corruption** — agentic self-editing memory can persist wrong facts; keep a raw immutable event log.
- **Small-model failure modes** — tool-call cliff below ~7–9B; overthinking/verbosity; hallucination on silence (voice).
- **AMD/ROCm friction** — version churn, FlashAttention lag, backend ambiguity (ROCm vs Vulkan performance inversions on RDNA3), Windows immaturity.
- **Benchmark caveats** — LongMemEval/LoCoMo test chat history, not task execution; vendor memory scores disagree (see the Zep/Mem0 LoCoMo dispute); BFCL v4 had reproducibility issues (some teams reverted to v3). Treat all leaderboard numbers as directional and run your own evals.
- **Open problems** — reliable long-horizon planning on small local models; memory decay/consolidation policies; robust turn-taking; injection-resistant retrieval over personal data.

## Recommendations

**Stage 1 — Minimal viable assistant (weeks 1–2).** Stand up llama.cpp (ROCm) serving Qwen3/3.5 14B Q4_K_M at 8–16K context on the 16GB AMD server. Build a single ReAct loop with 3–5 hand-written tools, hard call caps, and a deterministic fast-path for routine commands. Wire text I/O first (debug without the microphone). Add hybrid RAG over the Obsidian vault (nomic-embed-text + BM25 + cross-encoder rerank, top-20→top-5). *Benchmark to advance:* the agent completes a defined suite of personal-knowledge queries and tool calls with ≥90% correct tool formatting on your own eval set.

**Stage 2 — Voice + memory (weeks 3–5).** Add the Wyoming voice pipeline (openWakeWord + faster-whisper small + Piper) on the edge/server split; enforce terse responses and disable model "thinking" for voice. Add a small profile-fact store + approval-gated write-back into a vault inbox. Instrument everything with self-hosted Langfuse. *Benchmark:* end-to-end voice latency ≤2 s median on GPU; memory recall correct on a personal LongMemEval-style mini-set.

**Stage 3 — Hardening & operations (weeks 6+).** Sandbox all tool execution in containers with least-privilege; require confirmation for consequential actions; add semantic filtering on retrieved content. Build a CI regression suite (tool-call AST checks + memory evals + prompt-version comparisons). *Benchmark:* injection red-team suite (malicious note/tool-output) fails to exfiltrate or execute; no regression on eval set before promoting any prompt/model change.

**Thresholds that change the plan:**
- If tool-call accuracy is unacceptable on 14B → try gpt-oss-20b, or LoRA-tune tool formatting, before considering multi-agent.
- If single-loop fails on multi-step tasks in evals → add a thin planner/reflection layer (not a swarm).
- If temporal "what-was-true-when" queries matter → add Zep/Graphiti.
- If VRAM/context pressure dominates → drop to a smaller model or more aggressive quant; do not treat 16GB as 24GB.
- If ROCm friction consumes your time → llama.cpp/vLLM over Ollama; Linux over Windows.

## Caveats
- **Measured vs claimed:** BFCL scores, LongMemEval/LoCoMo numbers, and many throughput figures are self-reported by vendors/projects or community submitters; independent, methodology-visible benchmarks are labeled as such. AMD 16GB 14B throughput comes from community LocalScore/llama.cpp data whose backend (ROCm vs Vulkan) is not always labeled.
- **Version-sensitivity:** Model names and versions move fast (Qwen3→3.5→3.6, Gemma 3→4, ROCm 6.x→7.2, gpt-oss). Figures are dated where possible; re-verify at build time.
- **No independent data for some questions:** There is no published measured 14B/20B agentic throughput for the RX 7900 GRE (16GB) specifically, and no standardized task-execution memory benchmark (LongMemEval/LoCoMo test chat recall). These gaps are stated rather than estimated.
- **Scope:** Cloud assistants (ChatGPT/Alexa/Google), smart-home device ecosystems, full fine-tuning runs, and multi-user deployments are out of scope; the 16GB AMD + Pi + Obsidian setup is illustrative, and findings generalize across stacks.

## References
- Yao et al., "ReAct: Synergizing Reasoning and Acting in Language Models," arXiv, 2022. https://arxiv.org/abs/2210.03629
- gabrielanhaia, "ReAct, Plan-and-Execute, or Reflection? The Three Agent Patterns Every Engineer Needs in 2026," DEV Community, 2026. https://dev.to/gabrielanhaia/react-plan-and-execute-or-reflection-the-three-agent-patterns-every-engineer-needs-in-2026-355p
- The AI Engineer, "ReAct vs Plan-and-Execute vs ReWOO vs Reflexion," Substack, 2026. https://theaiengineer.substack.com/p/the-4-single-agent-patterns
- MachineLearningMastery, "7 Must-Know Agentic AI Design Patterns," 2026. https://machinelearningmastery.com/7-must-know-agentic-ai-design-patterns/
- Drammeh, "Multi-Agent LLM Orchestration Achieves Deterministic, High-Quality Decision Support for Incident Response," arXiv:2511.15755, 2026. https://arxiv.org/abs/2511.15755
- "Reason-Plan-ReAct: A Reasoner-Planner Supervising a ReAct Executor for Complex Enterprise Tasks," arXiv:2512.03560, 2026. https://arxiv.org/html/2512.03560v1
- Patil et al., "The Berkeley Function Calling Leaderboard (BFCL)," ICML/PMLR, 2025. https://proceedings.mlr.press/v267/patil25a.html
- Berkeley Function Calling Leaderboard (BFCL) V4, Gorilla, 2026. https://gorilla.cs.berkeley.edu/leaderboard.html
- "LoopTool: Closing the Data-Training Loop for Robust LLM Tool Calls," arXiv:2511.09148, 2025. https://arxiv.org/pdf/2511.09148
- XDA Developers, "The biggest local LLM on your machine is useless if it can't call a single tool," 2026. https://www.xda-developers.com/biggest-local-llm-machine-useless-cant-call-single-tool-how-many-parameters/
- Particula Tech, "Agent Memory Frameworks Tested: Mem0 vs Zep vs Letta," 2026. https://particula.tech/blog/agent-memory-frameworks-tested-mem0-zep-letta-cognee-2026
- Vectorize, "Mem0 vs Letta (MemGPT): AI Agent Memory Compared (2026)." https://vectorize.io/articles/mem0-vs-letta
- MCP.Directory, "Best AI Agent Memory 2026: Mem0 vs Letta vs Zep vs Cognee." https://mcp.directory/blog/mem0-vs-letta-vs-zep-vs-cognee-2026
- Rasmussen et al., "Zep: A Temporal Knowledge Graph Architecture for Agent Memory," arXiv:2501.13956, 2025. https://arxiv.org/abs/2501.13956
- "Human-Inspired Memory Architecture for LLM Agents," arXiv:2605.08538, 2026. https://arxiv.org/html/2605.08538v1
- Wang & Chen, "MIRIX: Multi-Agent Memory System for LLM-Based Agents," arXiv:2507.07957, 2025. https://arxiv.org/pdf/2507.07957
- ModemGuides, "How to Build a Local LLM Knowledge Base With Obsidian (2026)." https://www.modemguides.com/blogs/ai-infrastructure/local-llm-knowledge-base-obsidian-setup-guide
- Vasallo94, "ObsidianRAG," GitHub. https://github.com/Vasallo94/ObsidianRAG
- takeshy, "obsidian-local-llm-hub," GitHub. https://github.com/takeshy/obsidian-local-llm-hub
- Rodney Dyer, "Your Vault, Your Vectors — Building a Local-First MCP Server for Your PKM." https://www.rodneydyer.com/your-vault-your-vectors-building-a-local-first-mcp-server-for-obsidian/
- MindStudio, "What Is Andrej Karpathy's LLM Wiki?" https://www.mindstudio.ai/blog/andrej-karpathy-llm-wiki-knowledge-base-claude-code
- StackAI, "RAG Best Practices for Enterprise AI: Chunking, Embeddings, Reranking, Hybrid Search." https://www.stackai.com/insights/retrieval-augmented-generation-(rag)-best-practices-for-enterprise-ai-chunking-embeddings-reranking-and-hybrid-search-optimization
- "Searching for Best Practices in Retrieval-Augmented Generation," arXiv:2407.01219, 2024. https://arxiv.org/pdf/2407.01219
- LocalLLM.in, "Best Local LLMs for 16GB VRAM: Practical Performance Testing 2026." https://localllm.in/blog/best-local-llms-16gb-vram
- Micro Center, "Run AI Locally: The Best LLMs for 8GB, 16GB, 32GB Memory and Beyond." https://www.microcenter.com/site/mc-news/article/best-local-llms-8gb-16gb-32gb-memory-guide.aspx
- Rost Glukhov, "Comparing LLMs performance on Ollama on 16GB VRAM GPU." https://www.glukhov.org/llm-performance/benchmarks/choosing-best-llm-for-ollama-on-16gb-vram-gpu/
- Local AI Master, "AMD ROCm Local LLM Setup (2026)." https://localaimaster.com/blog/amd-rocm-local-llm-setup
- Kunal Ganglani, "AMD ROCm Supported GPUs in 2026: RX 7900 XTX, PyTorch, Windows." https://www.kunalganglani.com/blog/rocm-consumer-gpu-cuda-alternative-2026
- PromptQuorum, "Best AMD GPUs for Local LLMs 2026." https://www.promptquorum.com/local-llms/best-amd-gpus-local-llm
- AMD ROCm Blogs, "Llama.cpp Meets Instinct: A New Era of Open-Source AI Acceleration," Sept 2025. https://rocm.blogs.amd.com/ecosystems-and-partners/llama-cpp/README.html
- llama.cpp, "Performance of llama.cpp on AMD ROCm (HIP)," GitHub Discussion #15021. https://github.com/ggml-org/llama.cpp/discussions/15021
- LocalScore. https://localscore.ai
- Home Assistant Developer Docs, "Assist pipelines." https://developers.home-assistant.io/docs/voice/pipelines/
- Home Assistant, "The Home Assistant approach to wake words." https://www.home-assistant.io/voice_control/about_wake_word/
- Home Assistant, "Set up a fully local voice assistant." https://www.home-assistant.io/voice_control/voice_remote_local_assistant/
- Mike Hansen, "Voice Chapter 11: multilingual assistants are here," Home Assistant, Oct 2025. https://www.home-assistant.io/blog/2025/10/22/voice-chapter-11/
- Joe Karlsson, "I Built a Fully Local Voice Assistant for Home Assistant (With GPU, No Cloud Required)," 2025. https://www.joekarlsson.com/blog/local-voice-ai-home-assistant-gpu/
- SumGuy's Ramblings, "Local Voice Assistant: Whisper + Piper + Home Assistant." https://sumguy.com/local-voice-assistant-whisper-piper-ha/
- Local AI Master, "Build a Local Voice Assistant: Whisper + Ollama + Piper." https://localaimaster.com/blog/local-voice-assistant-whisper-ollama-piper
- Let's Data Science, "RK3576 Runs Local Home Assistant Voice." https://letsdatascience.com/news/rk3576-runs-local-home-assistant-voice-8c8cb018
- Hackster.io / Hanzo Huang, "Make Home Assistant Voice Fully Local with RK3576." https://www.hackster.io/h1300923175/make-home-assistant-voice-fully-local-with-rk3576-50b4de
- RoyalCities, "RC-Home-Assistant-Low-VRAM," GitHub. https://github.com/RoyalCities/RC-Home-Assistant-Low-VRAM
- Retell AI, "How Real-Time Voice AI Actually Works (STT → LLM → TTS)." https://www.retellai.com/blog/how-real-time-voice-ai-works-stt-llm-tts
- Smallest.ai, "Designing Voice Assistants: STT, LLM, TTS, Tools, and Latency Budget." https://smallest.ai/blog/designing-voice-assistants-stt-llm-tts-tools-and-latency-budget
- Gladia, "How to measure latency in speech-to-text." https://www.gladia.io/blog/measuring-latency-in-stt
- leon-ai, "Leon," GitHub. https://github.com/leon-ai/leon
- Langfuse, GitHub / site. https://github.com/langfuse/langfuse
- Laminar, "Top 6 Agent Observability Platforms (2026)." https://laminar.sh/article/2026-04-23-top-6-agent-observability-platforms
- DigitalOcean, "LangSmith Explained: Debugging and Evaluating LLM Agents." https://www.digitalocean.com/community/tutorials/langsmith-debudding-evaluating-llm-agents
- Practical DevSecOps, "MCP Security Vulnerabilities: How to Prevent Prompt Injection and Tool Poisoning Attacks in 2026." https://www.practical-devsecops.com/mcp-security-vulnerabilities/
- DataDome, "MCP Security: How to Stop Prompt Injection Attacks." https://datadome.co/agent-trust-management/mcp-security-prompt-injection-prevention/
- Christian Schneider, "Securing MCP: a defense-first architecture guide." https://christian-schneider.net/blog/securing-mcp-defense-first-architecture/
- Docker, "MCP Horror Stories: The GitHub Prompt Injection Data Heist." https://www.docker.com/blog/mcp-horror-stories-github-prompt-injection/
- Checkmarx, "MCP Security: Risks, Best Practices, and Security Controls." https://checkmarx.com/learn/mcp-security-risks-real-world-incidents-and-security-controls/
- "Model Context Protocol Threat Modeling and Analyzing Vulnerabilities to Prompt Injection with Tool Poisoning," arXiv:2603.22489, 2026. https://arxiv.org/html/2603.22489v1