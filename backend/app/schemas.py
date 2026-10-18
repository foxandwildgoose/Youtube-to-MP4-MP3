"""Request models. Extra fields are rejected."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class PasswordBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    password: str = Field(min_length=10, max_length=200)


class UrlBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    url: str = Field(min_length=1, max_length=2048)


class JobCreateBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    analysis_id: str = Field(min_length=8, max_length=64)
    choice_id: str = Field(min_length=4, max_length=128)
    keep_on_server: bool = False
    conversion_consent: bool = False


class RetentionBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    keep_on_server: bool


class SettingsPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    language: Literal["ko", "en"] | None = None
    theme: Literal["light", "dark", "system"] | None = None
    mp3_bitrate: Literal[128, 192, 320] | None = None
