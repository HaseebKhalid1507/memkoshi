"""Tests for Memkoshi search daemon."""

import json
import os
import pytest
import socket
import tempfile
import threading
import time
from pathlib import Path
from unittest.mock import Mock, patch

from memkoshi.daemon.server import MemkoshiDaemon
from memkoshi.daemon.client import DaemonClient
from memkoshi.daemon.protocol import send_message, recv_message


class TestProtocol:
    """Test wire protocol helpers."""
    
    def test_send_recv_message(self):
        """Test message serialization round-trip."""
        # Create socket pair
        server_sock, client_sock = socket.socketpair()
        
        try:
            # Send message
            test_msg = {"cmd": "test", "data": {"value": 42}}
            send_message(client_sock, test_msg)
            
            # Receive message
            received = recv_message(server_sock)
            
            assert received == test_msg
        finally:
            server_sock.close()
            client_sock.close()
    
    def test_message_too_large(self):
        """Test message size limit enforcement."""
        server_sock, client_sock = socket.socketpair()
        
        try:
            # Create oversized message (> 1MB)
            huge_data = "x" * (1024 * 1024 + 1)
            huge_msg = {"cmd": "test", "data": huge_data}
            
            with pytest.raises(ValueError, match="Message too large"):
                send_message(client_sock, huge_msg)
        finally:
            server_sock.close()
            client_sock.close()
    
    def test_socket_closed_during_recv(self):
        """Test handling of closed socket during receive."""
        server_sock, client_sock = socket.socketpair()
        
        # Close client while server tries to read
        client_sock.close()
        
        with pytest.raises(ConnectionError):
            recv_message(server_sock)
        
        server_sock.close()


class TestDaemonClient:
    """Test daemon client functionality."""
    
    @pytest.fixture
    def mock_storage_path(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            yield tmpdir
    
    def test_client_init(self, mock_storage_path):
        """Test client initialization."""
        client = DaemonClient(mock_storage_path, auto_start=False)
        
        assert client.storage_path == mock_storage_path
        assert client.auto_start == False
        assert client.socket_path.startswith("/tmp/memkoshi-search-")
    
    def test_is_running_false_when_no_daemon(self, mock_storage_path):
        """Test is_running returns False when no daemon."""
        client = DaemonClient(mock_storage_path, auto_start=False)
        
        assert client.is_running() == False
    
    @patch('subprocess.Popen')
    def test_start_daemon(self, mock_popen, mock_storage_path):
        """Test daemon startup."""
        client = DaemonClient(mock_storage_path, auto_start=False)
        
        # Mock daemon becomes available after start
        with patch.object(client, 'is_running') as mock_is_running:
            mock_is_running.side_effect = [False, False, True]  # Available on 3rd check
            
            result = client._start_daemon()
            
            assert result == True
            mock_popen.assert_called_once()


class TestMemkoshiDaemon:
    """Test daemon server functionality."""
    
    @pytest.fixture
    def mock_storage_path(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            yield tmpdir
    
    @pytest.fixture
    def daemon_socket_path(self):
        # Create unique socket path for test
        return f"/tmp/test-memkoshi-{os.getpid()}-{int(time.time())}.sock"
    
    @pytest.fixture
    def mock_search_engine(self):
        """Mock search engine."""
        engine = Mock()
        engine.initialize.return_value = None
        engine.search.return_value = [
            {
                "id": "test_mem_1",
                "score": 0.95,
                "title": "Test Memory",
                "category": "test",
                "abstract": "Test abstract"
            }
        ]
        return engine
    
    def test_daemon_init(self, mock_storage_path, daemon_socket_path):
        """Test daemon initialization."""
        daemon = MemkoshiDaemon(
            storage_path=mock_storage_path,
            socket_path=daemon_socket_path
        )
        
        assert daemon.storage_path == mock_storage_path
        assert daemon.socket_path == daemon_socket_path
        assert daemon.running == False
    
    def test_process_ping_request(self, mock_storage_path, daemon_socket_path):
        """Test ping command processing."""
        daemon = MemkoshiDaemon(
            storage_path=mock_storage_path,
            socket_path=daemon_socket_path
        )
        
        request = {"cmd": "ping"}
        response = daemon._process_request(request)
        
        assert response["status"] == "success"
        assert response["data"]["pong"] == True
    
    @patch('memkoshi.daemon.server.MemkoshiSearch')
    def test_process_search_request(self, mock_search_class, mock_storage_path, daemon_socket_path, mock_search_engine):
        """Test search command processing."""
        mock_search_class.return_value = mock_search_engine
        
        daemon = MemkoshiDaemon(
            storage_path=mock_storage_path,
            socket_path=daemon_socket_path
        )
        daemon.search_engine = mock_search_engine
        
        request = {
            "cmd": "search",
            "params": {
                "query": "test query",
                "limit": 5
            }
        }
        response = daemon._process_request(request)
        
        assert response["status"] == "success"
        assert response["data"]["query"] == "test query"
        assert len(response["data"]["results"]) == 1
        assert response["data"]["results"][0]["id"] == "test_mem_1"
        
        mock_search_engine.search.assert_called_once_with(
            query="test query",
            limit=5,
            category=None,
            recency_bias=True
        )
    
    def test_process_health_request(self, mock_storage_path, daemon_socket_path):
        """Test health command processing."""
        daemon = MemkoshiDaemon(
            storage_path=mock_storage_path,
            socket_path=daemon_socket_path
        )
        daemon.stats["start_time"] = time.time() - 100  # 100 seconds ago
        daemon.stats["requests_served"] = 10
        daemon.stats["total_duration_ms"] = 1000.0  # 100ms average
        
        request = {"cmd": "health"}
        response = daemon._process_request(request)
        
        assert response["status"] == "success"
        assert response["data"]["daemon_version"] == "0.3.0"
        assert response["data"]["uptime_seconds"] >= 100
        assert response["data"]["request_stats"]["total_requests"] == 10
        assert response["data"]["request_stats"]["avg_response_ms"] == 100.0
    
    def test_process_shutdown_request(self, mock_storage_path, daemon_socket_path):
        """Test shutdown command processing."""
        daemon = MemkoshiDaemon(
            storage_path=mock_storage_path,
            socket_path=daemon_socket_path
        )
        daemon.running = True
        
        request = {"cmd": "shutdown"}
        response = daemon._process_request(request)
        
        assert response["status"] == "success"
        assert response["data"]["shutdown_initiated"] == True
        assert daemon.running == False
    
    def test_process_unknown_command(self, mock_storage_path, daemon_socket_path):
        """Test handling of unknown commands."""
        daemon = MemkoshiDaemon(
            storage_path=mock_storage_path,
            socket_path=daemon_socket_path
        )
        
        request = {"cmd": "unknown_command"}
        response = daemon._process_request(request)
        
        assert response["status"] == "error"
        assert "Unknown command" in response["error"]
    
    def test_handle_search_missing_query(self, mock_storage_path, daemon_socket_path):
        """Test search request without query parameter."""
        daemon = MemkoshiDaemon(
            storage_path=mock_storage_path,
            socket_path=daemon_socket_path
        )
        
        request = {
            "cmd": "search",
            "params": {}  # Missing query
        }
        response = daemon._process_request(request)
        
        assert response["status"] == "error"
        assert "Query parameter required" in response["error"]


class TestDaemonIntegration:
    """Integration tests for daemon + client."""
    
    @pytest.fixture
    def mock_storage_path(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create basic storage structure
            storage_dir = Path(tmpdir)
            storage_dir.mkdir(exist_ok=True)
            yield str(storage_dir)
    
    @pytest.fixture
    def daemon_socket_path(self):
        return f"/tmp/test-memkoshi-integration-{os.getpid()}-{int(time.time())}.sock"
    
    @pytest.fixture
    def mock_search_engine(self):
        """Mock search engine for integration tests."""
        engine = Mock()
        engine.initialize.return_value = None
        engine.search.return_value = [
            {
                "id": "integration_test_mem",
                "score": 0.9,
                "title": "Integration Test Memory",
                "category": "test",
                "abstract": "Test memory for integration testing"
            }
        ]
        return engine
    
    @patch('memkoshi.daemon.server.MemkoshiSearch')
    def test_full_daemon_lifecycle(self, mock_search_class, mock_storage_path, daemon_socket_path, mock_search_engine):
        """Test complete daemon start -> request -> stop cycle."""
        mock_search_class.return_value = mock_search_engine
        
        # Start daemon in thread
        daemon = MemkoshiDaemon(
            storage_path=mock_storage_path,
            socket_path=daemon_socket_path
        )
        
        daemon_thread = threading.Thread(target=daemon.start, daemon=True)
        daemon_thread.start()
        
        # Wait for daemon to be ready
        max_wait = 5  # 5 seconds
        start_time = time.time()
        while time.time() - start_time < max_wait:
            try:
                sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                sock.settimeout(1)
                sock.connect(daemon_socket_path)
                sock.close()
                break
            except:
                time.sleep(0.1)
        else:
            pytest.fail("Daemon failed to start within timeout")
        
        try:
            # Test ping
            sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            sock.connect(daemon_socket_path)
            
            send_message(sock, {"cmd": "ping"})
            response = recv_message(sock)
            sock.close()
            
            assert response["status"] == "success"
            assert response["data"]["pong"] == True
            
            # Test search
            sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            sock.connect(daemon_socket_path)
            
            send_message(sock, {
                "cmd": "search",
                "params": {
                    "query": "integration test",
                    "limit": 1
                }
            })
            response = recv_message(sock)
            sock.close()
            
            assert response["status"] == "success"
            assert len(response["data"]["results"]) == 1
            assert response["data"]["results"][0]["id"] == "integration_test_mem"
            
            # Test shutdown
            sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            sock.connect(daemon_socket_path)
            
            send_message(sock, {"cmd": "shutdown"})
            response = recv_message(sock)
            sock.close()
            
            assert response["status"] == "success"
            assert response["data"]["shutdown_initiated"] == True
            
            # Wait for daemon to stop
            daemon_thread.join(timeout=2)
            
        finally:
            # Cleanup
            daemon.running = False
            try:
                Path(daemon_socket_path).unlink()
            except FileNotFoundError:
                pass
    
    @patch('memkoshi.daemon.server.MemkoshiSearch')
    def test_client_daemon_integration(self, mock_search_class, mock_storage_path, daemon_socket_path, mock_search_engine):
        """Test client connecting to daemon."""
        mock_search_class.return_value = mock_search_engine
        
        # Start daemon
        daemon = MemkoshiDaemon(
            storage_path=mock_storage_path,
            socket_path=daemon_socket_path
        )
        
        daemon_thread = threading.Thread(target=daemon.start, daemon=True)
        daemon_thread.start()
        
        # Wait for daemon
        time.sleep(0.5)
        
        try:
            # Create client
            client = DaemonClient(mock_storage_path, auto_start=False)
            client.socket_path = daemon_socket_path  # Override for test
            
            # Test is_running
            assert client.is_running() == True
            
            # Test search
            results = client.search("test query", limit=1)
            assert len(results) == 1
            assert results[0]["id"] == "integration_test_mem"
            
            # Test health
            health = client.health()
            assert "daemon_version" in health
            assert health["daemon_version"] == "0.3.0"
            
        finally:
            # Cleanup
            daemon.running = False
            try:
                Path(daemon_socket_path).unlink()
            except FileNotFoundError:
                pass


class TestDaemonFallback:
    """Test daemon fallback behavior."""
    
    def test_search_engine_transparent_daemon_usage(self):
        """Test that search engine tries daemon first, falls back gracefully."""
        from memkoshi.search.engine import MemkoshiSearch
        
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create search engine with daemon enabled
            search = MemkoshiSearch(tmpdir, enable_daemon=True)
            
            # Mock daemon client
            mock_daemon_client = Mock()
            mock_daemon_client.search.side_effect = ConnectionError("Daemon not available")
            search._daemon_client = mock_daemon_client
            search._use_fallback = False
            
            # Mock direct search fallback
            with patch.object(search, '_direct_search') as mock_direct:
                mock_direct.return_value = [{"id": "fallback_result", "score": 0.8}]
                
                # Search should try daemon (fail) then fall back to direct
                results = search.search("test query")
                
                # Verify daemon was tried first
                mock_daemon_client.search.assert_called_once_with(
                    query="test query", limit=5, category=None, recency_bias=True
                )
                
                # Verify fallback was called
                mock_direct.assert_called_once_with("test query", 5, None, True)
                
                # Verify we got fallback results
                assert results == [{"id": "fallback_result", "score": 0.8}]
    
    def test_daemon_disabled_skips_daemon(self):
        """Test search engine uses direct search when daemon disabled."""
        from memkoshi.search.engine import MemkoshiSearch
        
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create search engine with daemon disabled
            search = MemkoshiSearch(tmpdir, enable_daemon=False)
            search._use_fallback = False
            
            # Daemon client should not be created
            assert search._daemon_client is None
            
            # Mock direct search
            with patch.object(search, '_direct_search') as mock_direct:
                mock_direct.return_value = [{"id": "direct_result", "score": 0.9}]
                
                results = search.search("test query")
                
                # Should go directly to direct search (no daemon attempt)
                mock_direct.assert_called_once_with("test query", 5, None, True)
                assert results == [{"id": "direct_result", "score": 0.9}]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])