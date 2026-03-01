WebSocket Rate Limiting
=========================================

Overview
--------

RateThrottle supports comprehensive WebSocket rate limiting with:

* **Connection-level limiting** - Control new connections per minute
* **Message-level limiting** - Control messages per minute
* **Bandwidth limiting** - Control bytes per minute
* **Concurrent connection limiting** - Max connections per client
* **Message size limiting** - Max size per message

Quick Start
-----------

Installation
~~~~~~~~~~~~

.. code-block:: bash

    # WebSocket support included by default
    pip install ratethrottle
    
    # For specific socket-io or channels support:
    pip install ratethrottle[websocket]

Basic Usage
-----------

Simple Rate Limiter
~~~~~~~~~~~~~~~~~~~

.. code-block:: python

    from ratethrottle import WebSocketRateLimiter, WebSocketLimits
    
    # Create limiter with custom limits
    limiter = WebSocketRateLimiter(
        WebSocketLimits(
            connections_per_minute=10,      # Max 10 new connections/min
            messages_per_minute=100,         # Max 100 messages/min
            bytes_per_minute=1048576,        # Max 1MB/min
            max_concurrent_connections=5,    # Max 5 concurrent per client
            max_message_size=65536          # Max 64KB per message
        )
    )
    
    # Check if connection allowed
    if await limiter.check_connection("client_id"):
        await limiter.register_connection("conn_id", "client_id")
        
        # Check if message allowed
        result = await limiter.check_message("conn_id", message_size=len(data))
        if result['allowed']:
            # Send message
            pass

Framework Integrations
----------------------

1. FastAPI WebSocket
~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

    from fastapi import FastAPI, WebSocket, WebSocketDisconnect
    from ratethrottle import FastAPIWebSocketLimiter, WebSocketLimits
    
    app = FastAPI()
    
    # Create limiter
    limiter = FastAPIWebSocketLimiter(
        WebSocketLimits(
            connections_per_minute=10,
            messages_per_minute=100,
            max_message_size=10240  # 10KB
        )
    )
    
    @app.websocket("/ws/{client_id}")
    async def websocket_endpoint(websocket: WebSocket, client_id: str):
        """
        WebSocket endpoint with rate limiting
        """
        # Try to connect (automatically rate-limited)
        if not await limiter.connect(websocket, client_id):
            # Connection rejected - rate limit exceeded
            return
        
        try:
            while True:
                # Receive message
                data = await websocket.receive_text()
                
                # Check if message allowed
                if not await limiter.check_message(websocket, data):
                    await websocket.send_text(
                        '{"error": "Rate limit exceeded. Please slow down."}'
                    )
                    continue
                
                # Process and send response
                response = process_message(data)
                await websocket.send_text(response)
        
        except WebSocketDisconnect:
            # Clean up
            await limiter.disconnect(websocket)
    
    
    # Example: Chat application
    @app.websocket("/chat")
    async def chat_endpoint(websocket: WebSocket):
        # Get client IP automatically
        if not await limiter.connect(websocket):
            return
        
        try:
            while True:
                message = await websocket.receive_json()
                
                if await limiter.check_message(websocket, message):
                    # Broadcast to all
                    await broadcast_message(message)
                else:
                    await websocket.send_json({
                        "error": "Too many messages. Wait a moment."
                    })
        
        except WebSocketDisconnect:
            await limiter.disconnect(websocket)

2. Socket.IO
~~~~~~~~~~~~

.. code-block:: python

    from socketio import AsyncServer
    from ratethrottle import SocketIOLimiter, WebSocketLimits
    
    # Create Socket.IO server
    sio = AsyncServer(async_mode='asgi')
    
    # Create limiter
    limiter = SocketIOLimiter(
        WebSocketLimits(
            connections_per_minute=20,
            messages_per_minute=200
        )
    )
    
    @sio.event
    async def connect(sid, environ):
        """Handle new connection"""
        # Extract client IP
        client_ip = environ.get('REMOTE_ADDR', 'unknown')
        
        # Check rate limit
        if not await limiter.on_connect(sid, client_ip):
            return False  # Reject connection
        
        print(f"Client {client_ip} connected: {sid}")
        return True
    
    @sio.event
    async def message(sid, data):
        """Handle incoming message"""
        # Check rate limit
        if not await limiter.check_message(sid, data):
            await sio.emit('error', {
                'message': 'Rate limit exceeded',
                'retry_after': 10
            }, to=sid)
            return
        
        # Process message
        response = process_message(data)
        await sio.emit('response', response, to=sid)
    
    @sio.event
    async def disconnect(sid):
        """Handle disconnection"""
        await limiter.on_disconnect(sid)
        print(f"Client disconnected: {sid}")
    
    # Chat room example
    @sio.event
    async def join_room(sid, data):
        """Join chat room"""
        room = data['room']
        
        if await limiter.check_message(sid, data):
            sio.enter_room(sid, room)
            await sio.emit('joined', {'room': room}, to=sid)
    
    @sio.event
    async def chat_message(sid, data):
        """Send chat message"""
        if await limiter.check_message(sid, data):
            room = data['room']
            await sio.emit('message', data, room=room, skip_sid=sid)

3. Django Channels
~~~~~~~~~~~~~~~~~~

.. code-block:: python

    from channels.generic.websocket import AsyncWebsocketConsumer
    from ratethrottle import ChannelsRateLimiter, WebSocketLimits
    import json
    
    # Create global limiter
    limiter = ChannelsRateLimiter(
        WebSocketLimits(
            connections_per_minute=15,
            messages_per_minute=150
        )
    )
    
    class ChatConsumer(AsyncWebsocketConsumer):
        """Chat consumer with rate limiting"""
        
        async def connect(self):
            """Handle WebSocket connection"""
            # Get client IP
            client_ip = self.scope['client'][0]
            
            # Check rate limit
            if await limiter.check_connection(client_ip):
                await self.accept()
                
                # Register connection
                await limiter.register_connection(
                    self.channel_name,
                    client_ip,
                    metadata={'user': self.scope.get('user')}
                )
                
                # Join room
                self.room_name = self.scope['url_route']['kwargs']['room_name']
                await self.channel_layer.group_add(
                    self.room_name,
                    self.channel_name
                )
            else:
                # Reject connection
                await self.close(code=1008)
        
        async def disconnect(self, close_code):
            """Handle disconnection"""
            # Leave room
            await self.channel_layer.group_discard(
                self.room_name,
                self.channel_name
            )
            
            # Unregister connection
            await limiter.unregister_connection(self.channel_name)
        
        async def receive(self, text_data):
            """Receive message from WebSocket"""
            # Check rate limit
            if not await limiter.check_message(self.channel_name, text_data):
                await self.send(text_data=json.dumps({
                    'type': 'error',
                    'message': 'Rate limit exceeded'
                }))
                return
            
            # Parse message
            data = json.loads(text_data)
            message = data['message']
            
            # Broadcast to room
            await self.channel_layer.group_send(
                self.room_name,
                {
                    'type': 'chat_message',
                    'message': message
                }
            )
        
        async def chat_message(self, event):
            """Send message to WebSocket"""
            message = event['message']
            
            await self.send(text_data=json.dumps({
                'type': 'message',
                'message': message
            }))

Advanced Usage
--------------

Custom Client ID Extraction
~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

    from ratethrottle import FastAPIWebSocketLimiter
    
    def get_user_id(websocket):
        """Extract user ID from WebSocket"""
        # Get from query params
        user_id = websocket.query_params.get('user_id')
        
        # Or from headers
        if not user_id:
            user_id = websocket.headers.get('X-User-ID')
        
        # Fallback to IP
        if not user_id:
            user_id = websocket.client.host
        
        return user_id
    
    limiter = FastAPIWebSocketLimiter(
        get_client_id=get_user_id
    )

Per-Room/Channel Limits
~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

    from ratethrottle import WebSocketRateLimiter, WebSocketLimits
    
    class RoomLimiter:
        """Rate limiter with per-room limits"""
        
        def __init__(self):
            self.room_limiters = {}
        
        def get_room_limiter(self, room_name: str):
            """Get or create limiter for room"""
            if room_name not in self.room_limiters:
                self.room_limiters[room_name] = WebSocketRateLimiter(
                    WebSocketLimits(
                        connections_per_minute=50,
                        messages_per_minute=500
                    )
                )
            return self.room_limiters[room_name]
        
        async def check_room_message(
            self,
            room_name: str,
            connection_id: str,
            message: str
        ) -> bool:
            """Check message rate for specific room"""
            limiter = self.get_room_limiter(room_name)
            result = await limiter.check_message(connection_id, len(message))
            return result['allowed']
    
    # Usage
    room_limiter = RoomLimiter()
    
    @app.websocket("/room/{room_name}")
    async def room_endpoint(websocket: WebSocket, room_name: str):
        if not await limiter.connect(websocket):
            return
        
        try:
            while True:
                data = await websocket.receive_text()
                
                # Check both global and room limits
                if await limiter.check_message(websocket, data):
                    if await room_limiter.check_room_message(
                        room_name,
                        f"ws_{id(websocket)}",
                        data
                    ):
                        await broadcast_to_room(room_name, data)
                    else:
                        await websocket.send_text("Room rate limit exceeded")
                else:
                    await websocket.send_text("Global rate limit exceeded")
        
        except WebSocketDisconnect:
            await limiter.disconnect(websocket)

Violation Callbacks
~~~~~~~~~~~~~~~~~~~

.. code-block:: python

    def on_violation(violation_info):
        """Handle rate limit violations"""
        print(f"Violation: {violation_info}")
        
        # Log to database
        log_violation(violation_info)
        
        # Send alert
        if violation_info['type'] == 'message_rate':
            send_alert(f"High message rate from {violation_info['client_id']}")
        
        # Auto-ban repeated violators
        if get_violation_count(violation_info['client_id']) > 10:
            ban_client(violation_info['client_id'])
    
    limiter = WebSocketRateLimiter(
        on_violation=on_violation
    )

Statistics and Monitoring
~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

    # Get current statistics
    stats = limiter.get_statistics()
    print(stats)
    # {
    #     'active_connections': 42,
    #     'unique_clients': 15,
    #     'total_messages': 1523,
    #     'total_bytes_sent': 1048576,
    #     'limits': {
    #         'connections_per_minute': 10,
    #         'messages_per_minute': 100,
    #         ...
    #     }
    # }
    
    # Get specific connection info
    conn_info = limiter.get_connection_info("conn_123")
    print(f"Messages: {conn_info.message_count}")
    print(f"Bytes: {conn_info.bytes_sent}")
    print(f"Connected: {time.time() - conn_info.connected_at}s ago")
    
    # Get client connection count
    count = limiter.get_client_connections("192.168.1.1")
    print(f"Client has {count} active connections")

Complete Examples
-----------------

Example 1: Real-Time Chat
~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

    from fastapi import FastAPI, WebSocket
    from ratethrottle import FastAPIWebSocketLimiter, WebSocketLimits
    
    app = FastAPI()
    
    limiter = FastAPIWebSocketLimiter(
        WebSocketLimits(
            connections_per_minute=5,
            messages_per_minute=30,
            max_message_size=1024
        )
    )
    
    # Store active connections
    active_connections = []
    
    @app.websocket("/chat")
    async def chat(websocket: WebSocket):
        if not await limiter.connect(websocket):
            return
        
        active_connections.append(websocket)
        
        try:
            while True:
                message = await websocket.receive_text()
                
                if await limiter.check_message(websocket, message):
                    # Broadcast to all
                    for connection in active_connections:
                        try:
                            await connection.send_text(message)
                        except:
                            pass
                else:
                    await websocket.send_text("⚠️  Slow down! Rate limit exceeded.")
        
        except:
            pass
        finally:
            active_connections.remove(websocket)
            await limiter.disconnect(websocket)

Example 2: Live Dashboard
~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

    import asyncio
    from fastapi import FastAPI, WebSocket
    from ratethrottle import FastAPIWebSocketLimiter
    
    app = FastAPI()
    limiter = FastAPIWebSocketLimiter()
    
    @app.websocket("/dashboard")
    async def dashboard(websocket: WebSocket):
        if not await limiter.connect(websocket):
            return
        
        try:
            while True:
                # Send stats every second
                stats = limiter.limiter.get_statistics()
                await websocket.send_json(stats)
                
                # Rate limit check for updates
                if await limiter.check_message(websocket, stats):
                    await asyncio.sleep(1)
                else:
                    # Slow down if hitting limits
                    await asyncio.sleep(5)
        
        except:
            await limiter.disconnect(websocket)

Configuration Examples
----------------------

Strict Limits (API)
~~~~~~~~~~~~~~~~~~~

.. code-block:: python

    WebSocketLimits(
        connections_per_minute=5,
        messages_per_minute=50,
        bytes_per_minute=102400,  # 100KB
        max_concurrent_connections=2,
        max_message_size=1024
    )

Moderate Limits (Chat)
~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

    WebSocketLimits(
        connections_per_minute=10,
        messages_per_minute=100,
        bytes_per_minute=1048576,  # 1MB
        max_concurrent_connections=5,
        max_message_size=10240
    )

Generous Limits (Internal Tools)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

    WebSocketLimits(
        connections_per_minute=50,
        messages_per_minute=1000,
        bytes_per_minute=10485760,  # 10MB
        max_concurrent_connections=20,
        max_message_size=65536
    )

Best Practices
--------------

1. Choose Appropriate Limits
~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

    # Real-time trading: Strict
    WebSocketLimits(connections_per_minute=2, messages_per_minute=10)
    
    # Chat application: Moderate
    WebSocketLimits(connections_per_minute=10, messages_per_minute=60)
    
    # Live dashboard: Generous
    WebSocketLimits(connections_per_minute=20, messages_per_minute=120)

2. Handle Rate Limit Gracefully
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

    if not result['allowed']:
        reason = result['reason']
        
        if reason == 'rate_limit_exceeded':
            await websocket.send_json({
                'error': 'Too many messages',
                'retry_after': result.get('retry_after', 60)
            })
        elif reason == 'message_too_large':
            await websocket.send_json({
                'error': f"Message too large. Max: {result['max_size']} bytes"
            })

3. Monitor and Alert
~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

    def on_violation(info):
        # Log violations
        logger.warning(f"Rate limit violation: {info}")
        
        # Alert on repeated violations
        if info['type'] == 'message_rate':
            violation_count = get_violation_count(info['client_id'])
            if violation_count > 10:
                send_admin_alert(f"Client {info['client_id']} exceeding limits")

4. Use Redis for Distributed Systems
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

    from ratethrottle import RedisStorage
    
    storage = RedisStorage('redis://localhost:6379/0')
    limiter = WebSocketRateLimiter(storage=storage)
    
    # Now limits are shared across all servers

Summary
-------

* **Connection limiting** - Prevent connection spam
* **Message limiting** - Prevent message floods
* **Bandwidth limiting** - Prevent bandwidth abuse
* **Size limiting** - Prevent oversized messages
* **Framework support** - FastAPI, Socket.IO, Channels
* **Monitoring** - Real-time statistics
* **Production-ready** - Error handling, logging

Next Steps
----------

* Explore :doc:`graphql` examples
* Learn about :doc:`grpc` set up and examples
