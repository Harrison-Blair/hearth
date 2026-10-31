"""WebSocket messages exchanged by hearth clients and the backend.

Every frame is one JSON object with a ``type`` discriminator. Clients may send
only :class:`HelloMessage` and :class:`UserTextMessage`; the backend may send
only :class:`ReplyDeltaMessage`, :class:`ReplyDoneMessage`, and
:class:`ErrorMessage`. The models in this module are the complete whitelist of
what may cross the wire.
"""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

PROTOCOL_VERSION = 1

#: Close code for a wrong protocol version or a malformed/unexpected first message.
CLOSE_BAD_MESSAGE = 4400
#: Close code for an unknown device or a wrong token.
CLOSE_UNAUTHORIZED = 4401


class _Message(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class HelloMessage(_Message):
    type: Literal["hello"] = "hello"
    device_id: str
    token: str
    protocol_version: int


class UserTextMessage(_Message):
    type: Literal["user_text"] = "user_text"
    turn_id: str
    text: str


class ReplyDeltaMessage(_Message):
    type: Literal["reply_delta"] = "reply_delta"
    turn_id: str
    text: str


class ReplyDoneMessage(_Message):
    type: Literal["reply_done"] = "reply_done"
    turn_id: str


class ErrorMessage(_Message):
    type: Literal["error"] = "error"
    turn_id: str | None
    code: str
    message: str


type ClientMessage = Annotated[HelloMessage | UserTextMessage, Field(discriminator="type")]
type ServerMessage = Annotated[
    ReplyDeltaMessage | ReplyDoneMessage | ErrorMessage, Field(discriminator="type")
]
type Message = ClientMessage | ServerMessage

_CLIENT_ADAPTER: TypeAdapter[ClientMessage] = TypeAdapter(ClientMessage)
_SERVER_ADAPTER: TypeAdapter[ServerMessage] = TypeAdapter(ServerMessage)


def parse_client_message(data: str | bytes) -> ClientMessage:
    """Parse and validate a frame sent by a client."""
    return _CLIENT_ADAPTER.validate_json(data)


def parse_server_message(data: str | bytes) -> ServerMessage:
    """Parse and validate a frame sent by the backend."""
    return _SERVER_ADAPTER.validate_json(data)


def serialize(message: Message) -> str:
    """Serialize a protocol message to a JSON text frame."""
    return message.model_dump_json()
