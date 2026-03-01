GRPC Rate Limiting
====================================

Overview
--------

RateThrottle supports comprehensive gRPC rate limiting with:

* **Server interceptors** - Global rate limiting for all RPCs
* **Method decorators** - Per-method rate limits
* **Service-level limits** - Different limits per service
* **Stream support** - Unary, server streaming, client streaming, bidirectional
* **Concurrent request limiting** - Prevent resource exhaustion
* **Custom metadata extraction** - Use user IDs, API keys, etc.

Installation
------------

.. code-block:: bash

    # Install with gRPC support
    pip install ratethrottle[grpc]

Quick Start
-----------

1. Basic Server with Rate Limiting
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

    import grpc
    from concurrent import futures
    from ratethrottle import GRPCRateLimitInterceptor, GRPCLimits
    
    # Import your generated protobuf files
    import user_pb2
    import user_pb2_grpc
    
    # Create rate limit interceptor
    interceptor = GRPCRateLimitInterceptor(
        GRPCLimits(
            requests_per_minute=100,        # Max 100 requests/min per client
            concurrent_requests=10,          # Max 10 concurrent requests per client
            stream_messages_per_minute=1000  # Max 1000 stream messages/min
        )
    )
    
    # Create gRPC server with rate limiting
    server = grpc.server(
        futures.ThreadPoolExecutor(max_workers=10),
        interceptors=[interceptor]  # Add interceptor here
    )
    
    # Add your service
    user_pb2_grpc.add_UserServiceServicer_to_server(
        UserServiceImpl(),
        server
    )
    
    # Start server
    server.add_insecure_port('[::]:50051')
    server.start()
    print("gRPC server with rate limiting running on port 50051")
    server.wait_for_termination()

Complete Examples
-----------------

Example 1: User Service with Global Rate Limiting
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

    # user_service.py
    import grpc
    from concurrent import futures
    from ratethrottle import GRPCRateLimitInterceptor, GRPCLimits
    
    # Protobuf generated files
    import user_pb2
    import user_pb2_grpc
    
    class UserServiceImpl(user_pb2_grpc.UserServiceServicer):
        """User service implementation"""
        
        def GetUser(self, request, context):
            """Get user by ID (unary RPC)"""
            print(f"GetUser called for user_id: {request.user_id}")
            
            # Your business logic here
            user = get_user_from_db(request.user_id)
            
            return user_pb2.User(
                id=user['id'],
                name=user['name'],
                email=user['email']
            )
        
        def ListUsers(self, request, context):
            """List users (server streaming RPC)"""
            print(f"ListUsers called with limit: {request.limit}")
            
            # Stream users
            users = get_users_from_db(limit=request.limit)
            for user in users:
                yield user_pb2.User(
                    id=user['id'],
                    name=user['name'],
                    email=user['email']
                )
        
        def CreateUser(self, request, context):
            """Create new user (unary RPC)"""
            print(f"CreateUser called: {request.name}")
            
            user_id = create_user_in_db(request.name, request.email)
            
            return user_pb2.User(
                id=user_id,
                name=request.name,
                email=request.email
            )
    
    
    def serve():
        """Start gRPC server with rate limiting"""
        
        # Create rate limiter
        interceptor = GRPCRateLimitInterceptor(
            GRPCLimits(
                requests_per_minute=100,
                concurrent_requests=10,
                stream_messages_per_minute=1000
            )
        )
        
        # Create server
        server = grpc.server(
            futures.ThreadPoolExecutor(max_workers=10),
            interceptors=[interceptor]
        )
        
        # Add service
        user_pb2_grpc.add_UserServiceServicer_to_server(
            UserServiceImpl(),
            server
        )
        
        # Start
        server.add_insecure_port('[::]:50051')
        server.start()
        print("Server started on port 50051")
        
        try:
            server.wait_for_termination()
        except KeyboardInterrupt:
            server.stop(0)
    
    
    if __name__ == '__main__':
        serve()

Example 2: Per-Method Rate Limiting
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

    # Different limits for different methods
    from ratethrottle import grpc_ratelimit
    import user_pb2
    import user_pb2_grpc
    
    class UserServiceImpl(user_pb2_grpc.UserServiceServicer):
        """User service with method-specific rate limits"""
        
        @grpc_ratelimit(limit=10, window=60)
        def GetUser(self, request, context):
            """
            Get user - STRICT limit (10 req/min)
            Suitable for expensive operations
            """
            user = get_user_from_db(request.user_id)
            return user_pb2.User(
                id=user['id'],
                name=user['name'],
                email=user['email']
            )
        
        @grpc_ratelimit(limit=100, window=60)
        def ListUsers(self, request, context):
            """
            List users - MODERATE limit (100 req/min)
            Suitable for read operations
            """
            users = get_users_from_db(limit=request.limit)
            for user in users:
                yield user_pb2.User(
                    id=user['id'],
                    name=user['name'],
                    email=user['email']
                )
        
        @grpc_ratelimit(limit=5, window=60)
        def CreateUser(self, request, context):
            """
            Create user - VERY STRICT limit (5 req/min)
            Suitable for write operations
            """
            user_id = create_user_in_db(request.name, request.email)
            return user_pb2.User(
                id=user_id,
                name=request.name,
                email=request.email
            )
        
        @grpc_ratelimit(limit=1000, window=60)
        def SearchUsers(self, request, context):
            """
            Search users - GENEROUS limit (1000 req/min)
            Suitable for lightweight operations
            """
            users = search_users(request.query)
            for user in users:
                yield user_pb2.User(
                    id=user['id'],
                    name=user['name'],
                    email=user['email']
                )
    
    # No need for interceptor when using decorators!
    # But you can combine both for defense in depth
    server = grpc.server(
        futures.ThreadPoolExecutor(max_workers=10)
    )
    
    user_pb2_grpc.add_UserServiceServicer_to_server(
        UserServiceImpl(),
        server
    )
    
    server.add_insecure_port('[::]:50051')
    server.start()

Example 3: Custom Client ID Extraction
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

    # Extract user ID from metadata instead of IP
    from ratethrottle import (
        GRPCRateLimitInterceptor,
        GRPCLimits,
        extract_user_id_from_metadata
    )
    
    # Option 1: Use built-in helper
    extractor = extract_user_id_from_metadata('x-user-id')
    
    interceptor = GRPCRateLimitInterceptor(
        GRPCLimits(requests_per_minute=100),
        extract_client_id=extractor
    )
    
    
    # Option 2: Custom extraction logic
    def custom_extract_client_id(context):
        """Extract client ID from API key"""
        metadata = dict(context.invocation_metadata())
        
        # Try API key first
        api_key = metadata.get('x-api-key', '')
        if api_key:
            # Look up user from API key
            user_id = get_user_from_api_key(api_key)
            if user_id:
                return f"user_{user_id}"
        
        # Try user ID header
        user_id = metadata.get('x-user-id', '')
        if user_id:
            return f"user_{user_id}"
        
        # Fallback to IP address
        peer = context.peer()
        if peer and ':' in peer:
            parts = peer.split(':')
            if len(parts) >= 2:
                return f"ip_{parts[1]}"
        
        return 'anonymous'
    
    interceptor = GRPCRateLimitInterceptor(
        GRPCLimits(requests_per_minute=100),
        extract_client_id=custom_extract_client_id
    )

Example 4: Per-Service Rate Limits
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

    # Different limits for different services
    from ratethrottle import GRPCRateLimitInterceptor, GRPCLimits
    
    # Define service-specific limits
    method_limits = {
        'GetUser': GRPCLimits(requests_per_minute=100),
        'CreateUser': GRPCLimits(requests_per_minute=10),
        'DeleteUser': GRPCLimits(requests_per_minute=5),
        'ListUsers': GRPCLimits(requests_per_minute=50),
    }
    
    interceptor = GRPCRateLimitInterceptor(
        GRPCLimits(requests_per_minute=100),  # Default
        method_limits=method_limits            # Per-method overrides
    )
    
    server = grpc.server(
        futures.ThreadPoolExecutor(max_workers=10),
        interceptors=[interceptor]
    )

Example 5: Multiple Services with Different Limits
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

    import grpc
    from concurrent import futures
    from ratethrottle import GRPCRateLimitInterceptor, GRPCLimits
    
    # Import multiple services
    import user_pb2_grpc
    import product_pb2_grpc
    import order_pb2_grpc
    
    # Create interceptor with method-specific limits
    method_limits = {
        # User service - moderate limits
        'GetUser': GRPCLimits(requests_per_minute=100),
        'CreateUser': GRPCLimits(requests_per_minute=10),
        
        # Product service - generous limits (read-heavy)
        'GetProduct': GRPCLimits(requests_per_minute=500),
        'ListProducts': GRPCLimits(requests_per_minute=200),
        
        # Order service - strict limits (critical operations)
        'CreateOrder': GRPCLimits(requests_per_minute=5),
        'CancelOrder': GRPCLimits(requests_per_minute=10),
    }
    
    interceptor = GRPCRateLimitInterceptor(
        GRPCLimits(requests_per_minute=100),  # Default
        method_limits=method_limits
    )
    
    # Create server
    server = grpc.server(
        futures.ThreadPoolExecutor(max_workers=10),
        interceptors=[interceptor]
    )
    
    # Add all services
    user_pb2_grpc.add_UserServiceServicer_to_server(
        UserServiceImpl(), server
    )
    product_pb2_grpc.add_ProductServiceServicer_to_server(
        ProductServiceImpl(), server
    )
    order_pb2_grpc.add_OrderServiceServicer_to_server(
        OrderServiceImpl(), server
    )
    
    server.add_insecure_port('[::]:50051')
    server.start()

Example 6: Streaming RPCs
~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

    class ChatServiceImpl(chat_pb2_grpc.ChatServiceServicer):
        """Chat service with streaming"""
        
        @grpc_ratelimit(limit=100, window=60)
        def SendMessage(self, request_iterator, context):
            """
            Client streaming - receive messages
            Rate limited: 100 requests/min
            """
            for message in request_iterator:
                print(f"Received: {message.text}")
                save_message(message)
            
            return chat_pb2.SendResponse(success=True)
        
        @grpc_ratelimit(limit=1000, window=60)
        def GetMessages(self, request, context):
            """
            Server streaming - send messages
            Rate limited: 1000 messages/min total
            """
            messages = get_messages_from_db(request.chat_id)
            for msg in messages:
                yield chat_pb2.Message(
                    id=msg['id'],
                    text=msg['text'],
                    timestamp=msg['timestamp']
                )
        
        @grpc_ratelimit(limit=500, window=60)
        def Chat(self, request_iterator, context):
            """
            Bidirectional streaming - live chat
            Rate limited: 500 messages/min
            """
            for message in request_iterator:
                # Process incoming message
                response = process_message(message)
                
                # Send response
                yield chat_pb2.Message(
                    id=response['id'],
                    text=response['text'],
                    timestamp=response['timestamp']
                )

Example 7: Violation Callbacks
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

    def on_rate_limit_violation(violation_info):
        """Handle rate limit violations"""
        print(f"Rate limit violation: {violation_info}")
        
        violation_type = violation_info['type']
        client_id = violation_info['client_id']
        method = violation_info.get('method', 'unknown')
        
        # Log to database
        log_violation({
            'client_id': client_id,
            'method': method,
            'type': violation_type,
            'timestamp': time.time()
        })
        
        # Send alert for repeated violations
        violation_count = get_violation_count(client_id)
        if violation_count > 10:
            send_alert(f"Client {client_id} has {violation_count} violations")
        
        # Auto-ban abusive clients
        if violation_count > 50:
            ban_client(client_id, duration=3600)  # Ban for 1 hour
    
    # Create interceptor with callback
    interceptor = GRPCRateLimitInterceptor(
        GRPCLimits(requests_per_minute=100),
        on_violation=on_rate_limit_violation
    )

Example 8: Redis Storage for Distributed Systems
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

    from ratethrottle import GRPCRateLimitInterceptor, GRPCLimits
    from ratethrottle import RedisStorage
    
    # Use Redis for shared rate limits across multiple servers
    storage = RedisStorage('redis://localhost:6379/0')
    
    interceptor = GRPCRateLimitInterceptor(
        GRPCLimits(requests_per_minute=100),
        storage=storage
    )
    
    # Now rate limits are shared across all gRPC servers!
    server = grpc.server(
        futures.ThreadPoolExecutor(max_workers=10),
        interceptors=[interceptor]
    )

Client-Side Usage
-----------------

Handling Rate Limit Errors
~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

    # client.py
    import grpc
    import user_pb2
    import user_pb2_grpc
    
    def call_grpc_with_retry(stub, request):
        """Call gRPC method with automatic retry on rate limit"""
        max_retries = 3
        
        for attempt in range(max_retries):
            try:
                response = stub.GetUser(request)
                return response
            
            except grpc.RpcError as e:
                if e.code() == grpc.StatusCode.RESOURCE_EXHAUSTED:
                    # Extract retry-after from metadata
                    metadata = dict(e.trailing_metadata())
                    retry_after = int(metadata.get('retry-after', 60))
                    
                    print(f"Rate limited. Retry after {retry_after}s")
                    
                    if attempt < max_retries - 1:
                        time.sleep(retry_after)
                        continue
                    else:
                        raise
                else:
                    raise
    
    # Usage
    channel = grpc.insecure_channel('localhost:50051')
    stub = user_pb2_grpc.UserServiceStub(channel)
    
    request = user_pb2.GetUserRequest(user_id=123)
    response = call_grpc_with_retry(stub, request)
    print(f"User: {response.name}")

Reading Rate Limit Headers
~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

    import grpc
    import user_pb2
    import user_pb2_grpc
    
    def call_with_rate_limit_info(stub, request):
        """Call gRPC and show rate limit information"""
        
        # Set up call with metadata callback
        metadata_future = []
        
        def callback(metadata):
            metadata_future.append(metadata)
        
        # Make call
        try:
            response = stub.GetUser(request)
            
            # Check trailing metadata
            if metadata_future:
                metadata = dict(metadata_future[0])
                
                limit = metadata.get('x-ratelimit-limit', 'N/A')
                remaining = metadata.get('x-ratelimit-remaining', 'N/A')
                reset = metadata.get('x-ratelimit-reset', 'N/A')
                
                print(f"Rate Limit: {remaining}/{limit}")
                print(f"Resets at: {reset}")
            
            return response
        
        except grpc.RpcError as e:
            if e.code() == grpc.StatusCode.RESOURCE_EXHAUSTED:
                metadata = dict(e.trailing_metadata())
                retry_after = metadata.get('retry-after', 'unknown')
                print(f"❌ Rate limit exceeded. Retry after {retry_after}s")
            raise

Configuration Examples
----------------------

Public API (Strict)
~~~~~~~~~~~~~~~~~~~

.. code-block:: python

    GRPCLimits(
        requests_per_minute=60,          # 1 req/second
        concurrent_requests=5,            # Max 5 concurrent
        stream_messages_per_minute=600    # Max 10 messages/sec in streams
    )

Authenticated API (Moderate)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

    GRPCLimits(
        requests_per_minute=300,          # 5 req/second
        concurrent_requests=20,           # Max 20 concurrent
        stream_messages_per_minute=3000   # Max 50 messages/sec in streams
    )

Internal Services (Generous)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

    GRPCLimits(
        requests_per_minute=6000,         # 100 req/second
        concurrent_requests=100,          # Max 100 concurrent
        stream_messages_per_minute=60000  # Max 1000 messages/sec in streams
    )

Monitoring & Statistics
-----------------------

.. code-block:: python

    # Get current statistics
    interceptor = GRPCRateLimitInterceptor(
        GRPCLimits(requests_per_minute=100)
    )
    
    # Later, get stats
    stats = interceptor.get_statistics()
    print(stats)
    # {
    #     'limits': {
    #         'requests_per_minute': 100,
    #         'concurrent_requests': 50,
    #         'stream_messages_per_minute': 5000
    #     },
    #     'current_concurrent_requests': 15,
    #     'unique_clients': 8,
    #     'metrics': {
    #         'total_requests': 1523,
    #         'allowed_requests': 1498,
    #         'blocked_requests': 25
    #     }
    # }

Protobuf Example
----------------

.. code-block:: protobuf

    // user.proto
    syntax = "proto3";
    
    package user;
    
    service UserService {
      // Unary RPC
      rpc GetUser(GetUserRequest) returns (User);
      
      // Server streaming RPC
      rpc ListUsers(ListUsersRequest) returns (stream User);
      
      // Client streaming RPC
      rpc CreateUsers(stream CreateUserRequest) returns (CreateUsersResponse);
      
      // Bidirectional streaming RPC
      rpc Chat(stream ChatMessage) returns (stream ChatMessage);
    }
    
    message GetUserRequest {
      int32 user_id = 1;
    }
    
    message User {
      int32 id = 1;
      string name = 2;
      string email = 3;
    }
    
    message ListUsersRequest {
      int32 limit = 1;
    }
    
    message CreateUserRequest {
      string name = 1;
      string email = 2;
    }
    
    message CreateUsersResponse {
      int32 created_count = 1;
    }
    
    message ChatMessage {
      string text = 1;
      int64 timestamp = 2;
    }


Generate Python code:

.. code-block:: bash

    python -m grpc_tools.protoc -I. --python_out=. --grpc_python_out=. user.proto

Best Practices
--------------

1. Use Per-Method Limits for Fine Control
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

    # Different operations need different limits
    @grpc_ratelimit(limit=5, window=60)    # Write: strict
    def CreateUser(self, request, context):
        pass
    
    @grpc_ratelimit(limit=100, window=60)  # Read: generous
    def GetUser(self, request, context):
        pass

2. Combine Global + Method Limits
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

    # Global interceptor for baseline protection
    interceptor = GRPCRateLimitInterceptor(
        GRPCLimits(requests_per_minute=1000)
    )
    
    # + Method decorators for specific limits
    class UserService:
        @grpc_ratelimit(limit=10, window=60)  # Extra strict
        def DeleteUser(self, request, context):
            pass

3. Use Custom Metadata for Better Tracking
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

    # Track by user ID instead of IP
    extractor = extract_user_id_from_metadata('x-user-id')
    interceptor = GRPCRateLimitInterceptor(
        extract_client_id=extractor
    )

4. Monitor Violations
~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

    def on_violation(info):
        logger.warning(f"Rate limit: {info}")
        metrics.increment('rate_limit_violations')
        
    interceptor = GRPCRateLimitInterceptor(
        on_violation=on_violation
    )

Summary
-------

* **Global rate limiting** - Server interceptors
* **Method-specific limits** - Decorators
* **Streaming support** - All RPC types
* **Concurrent limiting** - Prevent resource exhaustion
* **Custom extraction** - User IDs, API keys, etc.
* **Distributed support** - Redis storage
* **Monitoring** - Statistics and callbacks

Next Steps
----------

* Explore :doc:`websocket` configuration
* Learn about :doc:`graphql` setup and configuration