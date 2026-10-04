from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator

DEMO_URL = "http://127.0.0.1:8001/probe"
DISPATCH_GRACE_SECONDS = 1


class CheckConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(default="Local demo", min_length=1, max_length=100)
    url: Literal[DEMO_URL] = DEMO_URL
    interval_seconds: int = Field(default=5, ge=1, le=3600)
    timeout_seconds: float = Field(default=2, gt=0, le=60)
    expected_status: int = Field(default=200, ge=100, le=599)
    required_text: str = Field(default="synthetic demo OK", max_length=1000)
    latency_threshold_ms: float = Field(default=500, gt=0, le=60000)
    enabled: bool = True

    @model_validator(mode="after")
    def bounded_timeout(self):
        if self.timeout_seconds >= self.interval_seconds:
            raise ValueError("timeout_seconds must be less than interval_seconds")
        return self


class DemoControl(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mode: Literal["Healthy", "Slow", "Failing"] = "Healthy"
    delay_seconds: float = Field(default=1, ge=0, le=30)


class Policy(BaseModel):
    model_config = ConfigDict(extra="forbid")
    slo_target: float = Field(gt=0, lt=1)
    window_seconds: int = Field(ge=10, le=2592000)
    short_window_seconds: int = Field(ge=5, le=2592000)
    long_window_seconds: int = Field(ge=5, le=2592000)
    short_min_samples: int = Field(ge=1)
    long_min_samples: int = Field(ge=1)
    alert_burn_threshold: float = Field(gt=0)

    @model_validator(mode="after")
    def ordered_windows(self):
        if not self.short_window_seconds <= self.long_window_seconds <= self.window_seconds:
            raise ValueError("require short window <= long window <= reporting window")
        return self


DEFAULT_POLICIES = {
    "demo": Policy(slo_target=.95, window_seconds=300, short_window_seconds=30,
                   long_window_seconds=120, short_min_samples=4, long_min_samples=12,
                   alert_burn_threshold=2),
    "thirty_day": Policy(slo_target=.999, window_seconds=2592000,
                         short_window_seconds=300, long_window_seconds=3600,
                         short_min_samples=48, long_min_samples=576,
                         alert_burn_threshold=14.4),
}
