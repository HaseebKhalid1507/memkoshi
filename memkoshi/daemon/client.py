"""Daemon client for Memkoshi search with fallback support."""

import os
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import Dict, List, Any, Optional

from .protocol import send_message, recv_message


class DaemonClient:
    """Client for communicating with Memkoshi search daemon."""
    
    def __init__(self, storage_path: str, auto_start: bool = False):
        self.storage_path = storage_path
        self.auto_start = auto_start
        self.socket_path = os.environ.get(
            'MEMKOSHI_SOCKET', 
            f"/tmp/memkoshi-search-{os.getuid()}.sock"
        )
    
    def connect(self) -> socket.socket:
        """Connect to daemon socket."""
        if self.auto_start and not self.is_running():
            self._start_daemon()
        
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.settimeout(10)
        sock.connect(self.socket_path)
        return sock
    
    def search(self, query: str, limit: int = 5, **kwargs) -> List[Dict[str, Any]]:
        """Send search request to daemon."""
        sock = self.connect()
        try:
            request = {
                "cmd": "search",
                "params": {
                    "query": query,
                    "limit": limit,
                    **kwargs
                }
            }
            
            send_message(sock, request)
            response = recv_message(sock)
            
            if response["status"] == "error":
                raise RuntimeError(response["error"])
            
            return response["data"]["results"]
        finally:
            sock.close()
    
    def health(self) -> Dict[str, Any]:
        """Check daemon health."""
        sock = self.connect()
        try:
            send_message(sock, {"cmd": "health"})
            response = recv_message(sock)
            
            if response["status"] == "error":
                raise RuntimeError(response["error"])
            
            return response["data"]
        finally:
            sock.close()
    
    def is_running(self) -> bool:
        """Check if daemon is running and responsive."""
        try:
            sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            sock.settimeout(2)
            sock.connect(self.socket_path)
            
            send_message(sock, {"cmd": "ping"})
            response = recv_message(sock)
            sock.close()
            
            return response.get("status") == "success"
        except:
            return False
    
    def _start_daemon(self) -> bool:
        """Start daemon process and wait for readiness."""
        daemon_cmd = [
            sys.executable, "-m", "memkoshi.daemon.server",
            "--storage-path", self.storage_path,
            "--socket-path", self.socket_path
        ]
        
        subprocess.Popen(
            daemon_cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True
        )
        
        # Wait for daemon to be ready (up to 10 seconds)
        for _ in range(50):  # 50 * 200ms = 10s
            time.sleep(0.2)
            if self.is_running():
                return True
        
        return False