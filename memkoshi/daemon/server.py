"""Memkoshi search daemon — keeps VelociRAG warm in memory."""

import json
import logging
import os
import signal
import socket
import time
from pathlib import Path
from typing import Dict, Any, Optional

from .protocol import send_message, recv_message
from ..search.engine import MemkoshiSearch

logger = logging.getLogger(__name__)


class MemkoshiDaemon:
    """Search daemon keeping VelociRAG warm in memory."""
    
    def __init__(self, storage_path: str, socket_path: str = None, max_memory_mb: int = 1024):
        self.storage_path = storage_path
        self.socket_path = socket_path or f"/tmp/memkoshi-search-{os.getuid()}.sock"
        self.max_memory_mb = max_memory_mb
        
        self.search_engine = None
        self.running = False
        self.server_socket = None
        self.stats = {
            "start_time": None,
            "requests_served": 0,
            "total_duration_ms": 0.0
        }
    
    def start(self) -> None:
        """Initialize and start serving requests."""
        logger.info(f"Starting Memkoshi search daemon on {self.socket_path}")
        
        # Setup signal handlers (only in main thread)
        try:
            signal.signal(signal.SIGTERM, self._signal_handler)
            signal.signal(signal.SIGINT, self._signal_handler)
        except ValueError:
            # Signal handlers only work in main thread - ignore for tests
            logger.debug("Signal handlers not available (not main thread)")
            pass
        
        # Initialize search engine
        self.search_engine = MemkoshiSearch(self.storage_path)
        self.search_engine.initialize()
        logger.info("Search engine initialized")
        
        # Setup socket server
        self.server_socket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        
        # Remove existing socket file
        try:
            Path(self.socket_path).unlink()
        except FileNotFoundError:
            pass
        
        self.server_socket.bind(self.socket_path)
        self.server_socket.listen(10)
        self.server_socket.settimeout(1.0)  # 1s timeout so we can check self.running
        
        self.running = True
        self.stats["start_time"] = time.time()
        
        logger.info(f"Daemon listening on {self.socket_path}")
        
        # Write socket path for clients to discover
        ready_path = self.socket_path + ".ready"
        try:
            with open(ready_path, 'w') as f:
                f.write(str(os.getpid()))
        except Exception:
            pass
        
        # Main request loop
        try:
            while self.running:
                try:
                    client_sock, _ = self.server_socket.accept()
                    self._handle_client(client_sock)
                except socket.timeout:
                    continue  # Check self.running and loop
                except OSError:
                    if self.running:
                        logger.error("Socket error in main loop")
                        break
        finally:
            self._cleanup()
            try:
                Path(ready_path).unlink(missing_ok=True)
            except Exception:
                pass
    
    def _signal_handler(self, signum, frame):
        """Handle shutdown signals."""
        logger.info(f"Received signal {signum}, shutting down")
        self.running = False
        if self.server_socket:
            self.server_socket.close()
    
    def _handle_client(self, client_sock: socket.socket) -> None:
        """Handle individual client request."""
        try:
            client_sock.settimeout(10)
            
            # Receive request
            request = recv_message(client_sock)
            start_time = time.perf_counter()
            
            # Process command
            response = self._process_request(request)
            
            # Add timing info
            duration_ms = (time.perf_counter() - start_time) * 1000
            response["duration_ms"] = round(duration_ms, 2)
            
            # Send response
            send_message(client_sock, response)
            
            # Update stats
            self.stats["requests_served"] += 1
            self.stats["total_duration_ms"] += duration_ms
            
        except Exception as e:
            logger.error(f"Error handling client: {e}")
            error_response = {
                "status": "error",
                "error": str(e),
                "duration_ms": 0
            }
            try:
                send_message(client_sock, error_response)
            except:
                pass
        finally:
            client_sock.close()
    
    def _process_request(self, request: Dict[str, Any]) -> Dict[str, Any]:
        """Process command and return response."""
        cmd = request.get("cmd")
        params = request.get("params", {})
        request_id = request.get("id")
        
        response = {"status": "success", "daemon_version": "0.3.0"}
        if request_id:
            response["id"] = request_id
        
        try:
            if cmd == "search":
                data = self._handle_search(params)
                response["data"] = data
                
            elif cmd == "ping":
                response["data"] = {"pong": True}
                
            elif cmd == "health":
                response["data"] = self._get_health_info()
                
            elif cmd == "stats":
                response["data"] = self._get_stats()
                
            elif cmd == "shutdown":
                response["data"] = {"shutdown_initiated": True}
                self.running = False
                
            else:
                response["status"] = "error"
                response["error"] = f"Unknown command: {cmd}"
                
        except Exception as e:
            logger.error(f"Error processing {cmd}: {e}")
            response["status"] = "error" 
            response["error"] = str(e)
        
        return response
    
    def _handle_search(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Handle search command."""
        query = params.get("query", "")
        limit = params.get("limit", 5)
        category = params.get("category")
        recency_bias = params.get("recency_bias", True)
        
        if not query:
            raise ValueError("Query parameter required")
        
        search_start = time.perf_counter()
        results = self.search_engine.search(
            query=query, 
            limit=limit, 
            category=category,
            recency_bias=recency_bias
        )
        search_duration = (time.perf_counter() - search_start) * 1000
        
        return {
            "query": query,
            "results": results,
            "total_found": len(results),
            "search_duration_ms": round(search_duration, 2)
        }
    
    def _get_health_info(self) -> Dict[str, Any]:
        """Get daemon health and performance info."""
        uptime = time.time() - self.stats["start_time"]
        avg_response_ms = 0
        
        if self.stats["requests_served"] > 0:
            avg_response_ms = self.stats["total_duration_ms"] / self.stats["requests_served"]
        
        return {
            "daemon_version": "0.3.0",
            "uptime_seconds": round(uptime, 1),
            "memory_usage_mb": 0,  # TODO: implement memory monitoring
            "request_stats": {
                "total_requests": self.stats["requests_served"],
                "avg_response_ms": round(avg_response_ms, 2)
            }
        }
    
    def _get_stats(self) -> Dict[str, Any]:
        """Get detailed daemon statistics."""
        return {
            "queries_served": self.stats["requests_served"],
            "avg_response_ms": round(self.stats["total_duration_ms"] / max(1, self.stats["requests_served"]), 2)
        }
    
    def _cleanup(self) -> None:
        """Clean up resources."""
        logger.info("Cleaning up daemon resources")
        
        if hasattr(self, 'server_socket') and self.server_socket:
            self.server_socket.close()
        
        try:
            Path(self.socket_path).unlink()
        except FileNotFoundError:
            pass
        
        logger.info("Daemon stopped")


if __name__ == "__main__":
    import sys
    import argparse
    
    parser = argparse.ArgumentParser(description="Memkoshi search daemon")
    parser.add_argument("--storage-path", required=True, help="Path to storage directory")
    parser.add_argument("--socket-path", help="Unix socket path")
    parser.add_argument("--max-memory", type=int, default=1024, help="Max memory in MB")
    parser.add_argument("--log-level", default="INFO", help="Logging level")
    
    args = parser.parse_args()
    
    logging.basicConfig(level=getattr(logging, args.log_level.upper()))
    
    daemon = MemkoshiDaemon(
        storage_path=args.storage_path,
        socket_path=args.socket_path,
        max_memory_mb=args.max_memory
    )
    
    try:
        daemon.start()
    except KeyboardInterrupt:
        print("\nShutting down...")
        sys.exit(0)