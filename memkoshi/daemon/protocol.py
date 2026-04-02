"""Wire protocol helpers for daemon communication."""

import json
import socket
import struct
from typing import Dict, Any


MAX_MESSAGE_SIZE = 1024 * 1024  # 1MB


def send_message(sock: socket.socket, msg_dict: Dict[str, Any]) -> None:
    """Send length-prefixed JSON message."""
    payload = json.dumps(msg_dict).encode('utf-8')
    if len(payload) > MAX_MESSAGE_SIZE:
        raise ValueError(f"Message too large: {len(payload)} > {MAX_MESSAGE_SIZE}")
    
    length = struct.pack('>I', len(payload))  # Big-endian 4-byte length
    sock.sendall(length + payload)


def recv_message(sock: socket.socket) -> Dict[str, Any]:
    """Receive length-prefixed JSON message."""
    # Read 4-byte length header
    raw_len = recv_exact(sock, 4)
    msg_len = struct.unpack('>I', raw_len)[0]
    
    if msg_len > MAX_MESSAGE_SIZE:
        raise ValueError(f"Message too large: {msg_len} > {MAX_MESSAGE_SIZE}")
    
    # Read message payload
    payload = recv_exact(sock, msg_len)
    return json.loads(payload.decode('utf-8'))


def recv_exact(sock: socket.socket, length: int) -> bytes:
    """Receive exactly length bytes."""
    data = b''
    while len(data) < length:
        chunk = sock.recv(length - len(data))
        if not chunk:
            raise ConnectionError("Socket closed during message read")
        data += chunk
    return data