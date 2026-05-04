import types
import os
import re
import datetime
from dataclasses import dataclass, field
from typing import Any, Dict, Pattern, Sequence, Mapping, Optional
from core.translation.context_resolver import resolve_initial_context
from core.translation.prompt_builder import build_system_prompt
from utils.srt_manager import parse_srt_blocks
from core.translation.pipeline_helpers import backfill_history, determine_effective_batch_size
from core.session_manager import (
    get_next_checkpoint_file, resolve_checkpoint_paths,
    restore_profile_from_checkpoint
)
from core.translation_stats import make_stats
from utils.app_utils import log, format_cost_display

class InitializationError(Exception):
    """Raised when initial checks, checkpoint recovery, or file resolution fails."""
    pass

@dataclass(frozen=True)
class PipelineConfig:
    """Read-only static configurations and resolved constants."""
    # Mode Flags
    resume_mode: bool
    debug_mode: bool
    use_scratchpad: bool
    bypass_intervention: bool

    # Engine Settings
    profile: Any
    model_cfg: Mapping[str, Any]
    api_key: str
    original_batch_size: int
    effective_batch_size: int

    # File Paths and Directories
    sys_file: str
    srt_file: str
    current_checkpoint_file: str
    output_file: str
    session_log_file: str
    scratch_dir: str

    # Regex Patterns
    re_ghost_chars: Pattern
    re_name_labels: Pattern
    re_newline_cleanup: Pattern
    illegal_labels: Sequence[Any]

    # Prompts and Context
    system_prompt: str
    blocks: Sequence[str]  # Typed specifically for SRT block string chunks
    eng_by_index: Mapping[int, str]
    ordered_srt_indices: Sequence[int]

    def __post_init__(self):
        """Enforce strict runtime immutability using Python primitives."""
        super().__setattr__('model_cfg', types.MappingProxyType(self.model_cfg))
        super().__setattr__('blocks', tuple(self.blocks))
        super().__setattr__('illegal_labels', tuple(self.illegal_labels))
        super().__setattr__('eng_by_index', types.MappingProxyType(self.eng_by_index))
        super().__setattr__('ordered_srt_indices', tuple(self.ordered_srt_indices))

    @property
    def total_blocks(self) -> int:
        """Derive count directly to prevent any stale duplicate state."""
        return len(self.blocks)

@dataclass(frozen=True)
class ProgressState:
    """Tracks indices and counts processed."""
    current_index: int = 0
    processed: int = 0
    session_processed: int = 0

@dataclass(frozen=True)
class BatchingState:
    """Tracks success streaks and failures for dynamic resizing."""
    success_streak: int = 0
    failures_at_current_size: int = 0
    min_batch_failures: int = 0
    attempted_batch_sizes: list = field(default_factory=list)

@dataclass(frozen=True)
class ErrorAuditState:
    """Saves error notes and previously targeted indices."""
    last_judge_error: str = ""
    last_judged_indices: set = field(default_factory=set)
    previous_overlong_indices: set = field(default_factory=set)

@dataclass(frozen=True)
class BypassState:
    """Tracks bypass logs and skipped counts."""
    bypass_count: int = 0
    bypass_log_file: Optional[str] = None

@dataclass
class PipelineRuntimeState:
    """Cohesive top-level mutable runtime and telemetry session state."""
    progress: ProgressState
    batching: BatchingState
    error_audit: ErrorAuditState
    bypass: BypassState
    total_main_cost: float
    total_judge_cost: float
    context_state: Dict[str, Any]
    translated_target_by_index: Dict[int, str]
    stats: Dict[str, Any]

def initialize_pipeline_session(config: dict, log_queue: Any = None, ui_queue: Any = None, shared_state: Any = None) -> tuple[PipelineConfig, PipelineRuntimeState]:
    """Fully initializes variables, file dependencies, and dataclasses for the session."""
    resume_mode = config["resume_mode"]
    debug_mode = config.get("debug_mode", False)
    model_cfg = config["model_cfg"]
    api_key = config["api_key"]
    batch_size = config["batch_size"]
    session_log_file = config["session_log_file"]
    bypass_intervention = config.get("bypass_intervention", False)

    profile = config.get("language_profile")
    if not profile:
        from utils.settings import SETTINGS
        profile = SETTINGS.get_active_profile()

    checkpoint_dir = config["checkpoint_dir"]
    sysprm_dir = config["sysprm_dir"]
    english_subs_dir = config["english_subs_dir"]
    output_dir = config["output_dir"]

    if resume_mode:
        checkpoint_data = config["checkpoint_data"]
        sys_file, srt_file = resolve_checkpoint_paths(checkpoint_data, sysprm_dir, english_subs_dir)
        output_file = checkpoint_data['output_file']
        current_index = checkpoint_data['current_index']
        processed = checkpoint_data.get('processed', 0)
        total_main_cost = checkpoint_data.get('total_main_cost', checkpoint_data.get('total_cost', 0.0))
        total_judge_cost = checkpoint_data.get('total_judge_cost', 0.0)

        restore_profile_from_checkpoint(profile, checkpoint_data)
        current_checkpoint_file = config["checkpoint_file_path"]

        if not os.path.exists(srt_file) or not os.path.exists(sys_file):
            log(log_queue, session_log_file, "❌ Error: Original files missing. Cannot resume.")
            if ui_queue:
                ui_queue.put(("finished", None))
            raise InitializationError("Original files missing. Cannot resume.")

        log(log_queue, session_log_file, f"\n✅ Resuming session: {srt_file} from block {current_index}")
        log(log_queue, session_log_file, f"📁 Using Checkpoint File: {current_checkpoint_file}")
    else:
        sys_file = os.path.join(sysprm_dir, config["sys_name"])
        srt_file = os.path.join(english_subs_dir, config["srt_name"])
        current_checkpoint_file = get_next_checkpoint_file(checkpoint_dir)

        base_name = os.path.basename(srt_file)
        output_file = os.path.join(output_dir, base_name.replace('.srt', f'_{model_cfg["name"]}_{profile.target_lang_code}.srt'))
        current_index = 0
        processed = 0
        total_main_cost = 0.0
        total_judge_cost = 0.0
        log(log_queue, session_log_file, f"\n📁 Creating new Checkpoint File: {current_checkpoint_file}")

    log(log_queue, session_log_file, f"📝 Target File: {os.path.basename(srt_file)}")
    if resume_mode:
        log(log_queue, session_log_file, f"🔄 Resuming from index: {current_index}")

    (profile, series_context, initial_context_str, context_state,
     last_idx, illegal_labels, srt_content, ordered_srt_indices, prompt_prefix) = resolve_initial_context(config, log_queue, session_log_file)

    idx_workflow = last_idx + 1
    idx_tech = idx_workflow + 1
    idx_clean = idx_tech + 1

    use_scratchpad = model_cfg.get("enable_scratchpad", True)

    system_prompt = build_system_prompt(profile, model_cfg, idx_workflow, idx_tech, idx_clean, prompt_prefix, series_context)

    log(log_queue, session_log_file, f"🚀 [Mode: {'High-Quality (Scratchpad)' if use_scratchpad else 'Efficiency (Direct)'}] Starting translation with {model_cfg['name']}...")

    blocks, eng_by_index, _ = parse_srt_blocks(srt_content)
    total_blocks = len(blocks)

    translated_target_by_index = backfill_history(
        resume_mode, output_file, srt_content, ordered_srt_indices,
        current_index, eng_by_index, ui_queue, log_queue, session_log_file
    )
    effective_batch_size, override_msg = determine_effective_batch_size(resume_mode, checkpoint_data if resume_mode else {}, batch_size)

    if resume_mode:
        stats = make_stats(resume_from=checkpoint_data.get("stats"))
    else:
        stats = make_stats()

    # Create regex patterns exactly like in original run_pipeline:
    ranges_str = "".join([f"\\u{s:04x}-\\u{e:04x}" for s, e in profile.target_unicode_ranges])
    re_ghost_chars = re.compile(rf'\n[a-zA-Z]{{1,2}}(?=\s|[{ranges_str}]|<|♪)')
    re_name_labels = re.compile(rf'([A-Z][a-z]+|\([{ranges_str}]+\))')
    re_newline_cleanup = re.compile(profile.newline_regex)

    cfg = PipelineConfig(
        resume_mode=resume_mode,
        debug_mode=debug_mode,
        use_scratchpad=use_scratchpad,
        bypass_intervention=bypass_intervention,
        profile=profile,
        model_cfg=model_cfg,
        api_key=api_key,
        original_batch_size=batch_size,
        effective_batch_size=effective_batch_size,
        sys_file=sys_file,
        srt_file=srt_file,
        current_checkpoint_file=current_checkpoint_file,
        output_file=output_file,
        session_log_file=session_log_file,
        scratch_dir=config.get("scratch_dir", "scratch"),
        re_ghost_chars=re_ghost_chars,
        re_name_labels=re_name_labels,
        re_newline_cleanup=re_newline_cleanup,
        illegal_labels=illegal_labels,
        system_prompt=system_prompt,
        blocks=blocks,
        eng_by_index=eng_by_index,
        ordered_srt_indices=ordered_srt_indices
    )

    state = PipelineRuntimeState(
        progress=ProgressState(
            current_index=current_index,
            processed=processed,
            session_processed=0
        ),
        batching=BatchingState(
            success_streak=0,
            failures_at_current_size=0,
            min_batch_failures=0,
            attempted_batch_sizes=[]
        ),
        error_audit=ErrorAuditState(),
        bypass=BypassState(),
        total_main_cost=total_main_cost,
        total_judge_cost=total_judge_cost,
        context_state=context_state,
        translated_target_by_index=translated_target_by_index,
        stats=stats
    )

    if ui_queue:
        ui_queue.put(("cost", (total_main_cost, total_judge_cost)))
        if stats.get("total_interventions", 0) > 0:
            ui_queue.put(("intervention_count", stats["total_interventions"]))
        ui_queue.put(("progress", (processed, total_blocks)))

    if shared_state:
        shared_state.update_cost(total_main_cost, total_judge_cost, format_cost_display(total_main_cost, total_judge_cost))
        shared_state.update_progress(processed, total_blocks)

    log(log_queue, session_log_file, f"🚀 Starting Protected AI Translation with {model_cfg['provider']}")
    if resume_mode:
        if override_msg:
            log(log_queue, session_log_file, f"📦 Batch: {batch_size}{override_msg}")
        elif effective_batch_size != batch_size:
            log(log_queue, session_log_file, f"📦 Batch: configured {batch_size} | continuing with effective size {effective_batch_size} (checkpoint memory)")
        else:
            log(log_queue, session_log_file, f"📦 Batch Size: {effective_batch_size}")
    else:
        log(log_queue, session_log_file, f"📦 Batch Size: {effective_batch_size} | Safety Net: ACTIVE")

    return cfg, state
