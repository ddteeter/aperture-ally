"""Application configuration.

Values come from environment variables prefixed ``APERTURE_ALLY_`` and an optional ``.env`` file in the
working directory. Provider secrets are read from their conventional variables (``OPENAI_API_KEY``,
``GEMINI_API_KEY``) and are never serialized to the frontend or logs.

Model identifiers and prices are intentionally *not* defaulted: they change often and must be taken
from the providers' official documentation at setup time (see docs/setup.md).
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[2]


class ModelPrice(BaseModel):
    """USD per 1M tokens, copied from the provider's official pricing page."""

    input_per_mtok: float
    output_per_mtok: float
    verified_on: str | None = None
    source_url: str | None = None


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="APERTURE_ALLY_", env_file=".env", env_file_encoding="utf-8", extra="ignore",
        env_ignore_empty=True,  # `APERTURE_ALLY_CLAUDE_EFFORT=` means "use the default", as .env.example says
    )

    # --- storage ---------------------------------------------------------------------------
    data_dir: Path = Field(default=Path.home() / "ApertureAlly", description="DB + session storage root")
    import_roots: list[Path] = Field(
        default_factory=lambda: [REPO_ROOT / "fixtures", Path.home() / "Pictures"],
        description="Directories manual path imports may read from",
    )

    # --- server ----------------------------------------------------------------------------
    host: str = "127.0.0.1"
    port: int = 8765
    allowed_origins: list[str] = Field(
        default_factory=lambda: [
            "http://127.0.0.1:8765",
            "http://localhost:8765",
            "http://127.0.0.1:5173",
            "http://localhost:5173",
        ]
    )
    frontend_dist: Path = REPO_ROOT / "frontend" / "dist"

    # --- ingestion -------------------------------------------------------------------------
    fast_ready_images: bool = Field(
        True, description="A JPEG/TIFF/PNG that fully decodes on first sight is ready at once (OM Capture moves "
                          "complete files in by rename, verified on the E-M1 II); otherwise the quiet-poll checks apply")
    stability_interval_ms: int = 250
    stability_checks: int = 3
    stability_timeout_s: float = 30.0
    reconcile_interval_s: float = 5.0
    pair_grace_s: float = Field(4.0, description="Wait this long for a JPEG partner before a RAW-only capture")
    pair_time_tolerance_s: float = 2.0
    raw_unverified_settle_s: float = Field(2.0, description="Extra stable time before keeping a RAW LibRaw cannot decode")
    attribution_ambiguity_s: float = Field(3.0, description="Active-shot change this close to detection = ambiguous")
    watch_recursive: bool = True
    image_workers: int = 2

    # --- evidence --------------------------------------------------------------------------
    overview_long_edge: int = 1600
    crop_max_edge: int = 1024
    max_crops: int = 3

    # --- coaching --------------------------------------------------------------------------
    assess_provider: Literal["mock", "openai", "gemini", "claude"] = "mock"
    openai_model: str | None = None
    gemini_model: str | None = None
    claude_model: str | None = Field(
        "claude-opus-5-5",
        description="Anthropic model id; Anthropic's recommended starting model (platform.claude.com, checked 2026-09-27)")
    claude_effort: Literal["low", "medium", "high", "xhigh", "max"] | None = Field(
        None, description="output_config.effort; None = API default. Lower = faster/cheaper; sweep it in evals")
    claude_refusal_fallback: bool = Field(True, description='server-side fallbacks: "default" on safety declines')
    openai_effort: Literal["none", "low", "medium", "high", "xhigh", "max"] | None = Field(
        None, description="reasoning.effort; None = model default (medium on gpt-6/gpt-5.6). Sweep it in evals")
    openai_image_detail: Literal["low", "high", "auto", "original"] = "high"
    gemini_media_resolution: Literal["low", "medium", "high", "ultra_high"] = "high"
    gemini_thinking_level: Literal["minimal", "low", "medium", "high"] | None = Field(
        None, description="thinking_config.thinking_level; None = model default. minimal is not valid on 3.8-flash")
    model_timeout_s: float = 45.0
    max_model_concurrency: int = 2
    auto_coach: bool = True
    session_max_model_calls: int | None = Field(
        150, description="Default cap on paid assess/answer calls per session (transcription not capped)")
    session_budget_usd: float | None = Field(
        None, description="Default USD cap per session; only priced models count (set APERTURE_ALLY_PRICES)")
    history_limit: int = 4
    retry_online_poll_s: float = Field(15.0, description="While a retry-when-online is armed: provider reachability check")
    teaching_prompt_every: int = Field(3, description="Ask Drew to predict/explain roughly every Nth coached capture")
    prices: dict[str, ModelPrice] = Field(default_factory=dict, description="model id -> price; optional")

    # --- telemetry ---------------------------------------------------------------------------
    store_model_io: bool = Field(True, description="Persist full request context + raw model output per call")
    network_probe_interval_s: float = Field(300.0, description="DNS/TCP probe of configured provider hosts; 0 = off")
    log_to_file: bool = True

    # --- speech / voice --------------------------------------------------------------------
    speech_provider: Literal["say", "mock", "none"] = "mock"
    say_voice: str | None = None
    say_rate_wpm: int | None = 190
    say_tail_silence_ms: int = Field(400, ge=0, le=2000, description="Silence after each utterance so Bluetooth "
                                     "headphones don't clip the last word; 0 = off")
    say_audio_device: str | None = Field(None, description="`say -a` device name/ID; None = system output")
    recorder: Literal["sounddevice", "mock"] = "mock"
    input_device: str | None = None
    transcriber: Literal["openai", "mock"] = "mock"
    transcription_model: str | None = None
    mock_transcripts: list[str] = Field(default_factory=list)
    ptt_max_seconds: float = 60.0
    ptt_timeout_action: Literal["discard", "submit"] = "discard"
    min_utterance_s: float = 0.35
    ready_cue: bool = True
    received_cue: Literal["sound", "speech", "none"] = Field(
        "sound", description="Audible confirmation that a photo arrived (sound mixes with speech; speech waits)")
    received_cue_sound: str = "/System/Library/Sounds/Pop.aiff"
    failure_cue_sound: str = "/System/Library/Sounds/Basso.aiff"
    cue_volume: float = Field(1.0, ge=0.25, le=4.0, description="afplay -v for the cues; 1 = the sound's own level")
    ready_cue_sound: str = "/System/Library/Sounds/Tink.aiff"
    keep_voice_audio: bool = False

    # --- global keys -----------------------------------------------------------------------
    global_keys: Literal["pynput", "none"] = "none"
    ptt_key: str = "f18"
    ptt_mode: Literal["hold", "toggle"] = "hold"
    cancel_key: str | None = None
    pause_key: str | None = Field(None, description="Optional remote key that toggles auto-coaching pause")

    # --- secrets (unprefixed conventional names) ------------------------------------------
    openai_api_key: SecretStr | None = Field(None, validation_alias="OPENAI_API_KEY")
    gemini_api_key: SecretStr | None = Field(None, validation_alias="GEMINI_API_KEY")
    anthropic_api_key: SecretStr | None = Field(None, validation_alias="ANTHROPIC_API_KEY")

    @field_validator("data_dir", "frontend_dist", mode="after")
    @classmethod
    def _expand(cls, v: Path) -> Path:
        return v.expanduser()

    @field_validator("import_roots", mode="after")
    @classmethod
    def _expand_all(cls, v: list[Path]) -> list[Path]:
        return [p.expanduser() for p in v]

    @property
    def db_path(self) -> Path:
        return self.data_dir / "aperture_ally.sqlite3"

    @property
    def sessions_dir(self) -> Path:
        return self.data_dir / "sessions"

    def model_for(self, provider: str) -> str | None:
        return {"openai": self.openai_model, "gemini": self.gemini_model, "claude": self.claude_model,
                "mock": "mock-heuristic-v1"}.get(provider)

    def public_view(self) -> dict:
        """Configuration safe to send to the UI (no secrets)."""
        data = self.model_dump(exclude={"openai_api_key", "gemini_api_key", "anthropic_api_key", "prices"}, mode="json")
        data["openai_key_configured"] = self.openai_api_key is not None
        data["gemini_key_configured"] = self.gemini_api_key is not None
        data["anthropic_key_configured"] = self.anthropic_api_key is not None
        data["priced_models"] = sorted(self.prices)
        return data


@lru_cache
def get_settings() -> Settings:
    return Settings()
