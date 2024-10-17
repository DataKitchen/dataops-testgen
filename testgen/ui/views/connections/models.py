import dataclasses


@dataclasses.dataclass(frozen=True, slots=True)
class ConnectionStatus:
    message: str
    successful: bool
    details: str | None = dataclasses.field(default=None)
