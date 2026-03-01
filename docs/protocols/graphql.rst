GraphQL Rate Limiting
=======================================

Overview
--------

RateThrottle supports comprehensive GraphQL rate limiting with:

* **Query complexity analysis** - Prevent expensive queries
* **Depth limiting** - Prevent deep nested queries
* **Operation type limits** - Different limits for queries/mutations/subscriptions
* **Field-level limiting** - Rate limit specific fields
* **Framework support** - Ariadne, Graphene, Strawberry
* **Custom cost calculation** - Define field costs

Installation
------------

.. code-block:: bash

    # Install with GraphQL support
    pip install ratethrottle[graphql]
    
    # Or install graphql-core separately
    pip install ratethrottle graphql-core


Quick Start
-----------

1. Basic Rate Limiting
~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

    from ratethrottle import GraphQLRateLimiter, GraphQLLimits
    
    # Create limiter
    limiter = GraphQLRateLimiter(
        GraphQLLimits(
            queries_per_minute=100,
            mutations_per_minute=20,
            max_complexity=1000,
            max_depth=10
        )
    )
    
    # Check if query is allowed
    error = limiter.check_rate_limit(
        document_ast=parsed_query,
        context=request_context
    )
    
    if error:
        raise error  # GraphQLError with rate limit info

Framework Integrations
----------------------

1. Ariadne
~~~~~~~~~~

.. code-block:: python

    from ariadne import make_executable_schema, QueryType, gql
    from ratethrottle import AriadneRateLimiter, GraphQLLimits
    
    # Define schema
    type_defs = gql("""
        type Query {
            users: [User!]!
            user(id: ID!): User
        }
        
        type User {
            id: ID!
            name: String!
            posts: [Post!]!
        }
        
        type Post {
            id: ID!
            title: String!
            content: String!
        }
    """)
    
    # Create resolvers
    query = QueryType()
    
    @query.field("users")
    def resolve_users(obj, info):
        return get_all_users()
    
    @query.field("user")
    def resolve_user(obj, info, id):
        return get_user_by_id(id)
    
    # Create rate limiter
    limiter = AriadneRateLimiter(
        GraphQLLimits(
            queries_per_minute=100,
            max_complexity=1000,
            max_depth=10
        )
    )
    
    # Create schema with rate limiting
    schema = make_executable_schema(
        type_defs,
        query,
        middleware=[limiter]  # Add middleware here
    )
    
    # Use with your server (Flask, FastAPI, etc.)
    from ariadne.asgi import GraphQL
    
    app = GraphQL(schema, debug=True)

2. Graphene (Django/Flask)
~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

    import graphene
    from graphene import ObjectType, String, Int, List, Field
    from ratethrottle import GraphQLRateLimiter, GraphQLLimits
    
    # Define types
    class User(ObjectType):
        id = Int()
        name = String()
        email = String()
        posts = List(lambda: Post)
        
        def resolve_posts(self, info):
            return get_user_posts(self.id)
    
    class Post(ObjectType):
        id = Int()
        title = String()
        content = String()
        author = Field(User)
    
    # Define queries
    class Query(ObjectType):
        users = List(User)
        user = Field(User, id=Int(required=True))
        
        def resolve_users(self, info):
            return get_all_users()
        
        def resolve_user(self, info, id):
            return get_user_by_id(id)
    
    # Create schema
    schema = graphene.Schema(query=Query)
    
    # Create rate limiter
    limiter = GraphQLRateLimiter(
        GraphQLLimits(
            queries_per_minute=100,
            max_complexity=1000
        )
    )
    
    # Use in your view (Flask example)
    from flask import Flask, request, jsonify
    from graphql import parse, execute
    
    app = Flask(__name__)
    
    @app.route('/graphql', methods=['POST'])
    def graphql_endpoint():
        data = request.get_json()
        
        # Parse query
        document = parse(data['query'])
        
        # Check rate limit
        error = limiter.check_rate_limit(
            document,
            request,
            data.get('operationName'),
            data.get('variables')
        )
        
        if error:
            return jsonify({
                'errors': [error.formatted]
            }), 429
        
        # Execute query
        result = execute(
            schema,
            document,
            variable_values=data.get('variables'),
            operation_name=data.get('operationName'),
            context_value=request
        )
        
        return jsonify(result)

3. Strawberry (FastAPI)
~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

    import strawberry
    from fastapi import FastAPI
    from strawberry.fastapi import GraphQLRouter
    from ratethrottle import GraphQLRateLimiter, GraphQLLimits
    
    # Define types
    @strawberry.type
    class User:
        id: int
        name: str
        email: str
    
    @strawberry.type
    class Post:
        id: int
        title: str
        content: str
    
    # Define queries
    @strawberry.type
    class Query:
        @strawberry.field
        def users(self) -> list[User]:
            return get_all_users()
        
        @strawberry.field
        def user(self, id: int) -> User:
            return get_user_by_id(id)
    
    # Create schema
    schema = strawberry.Schema(query=Query)
    
    # Create rate limiter
    limiter = GraphQLRateLimiter(
        GraphQLLimits(
            queries_per_minute=100,
            max_complexity=1000
        )
    )
    
    # Custom GraphQL router with rate limiting
    class RateLimitedGraphQLRouter(GraphQLRouter):
        async def process_request(self, request):
            # Parse query
            data = await request.json()
            document = parse(data['query'])
            
            # Check rate limit
            error = limiter.check_rate_limit(
                document,
                request,
                data.get('operationName')
            )
            
            if error:
                return JSONResponse(
                    {'errors': [error.formatted]},
                    status_code=429
                )
            
            return await super().process_request(request)
    
    # Create FastAPI app
    app = FastAPI()
    graphql_app = RateLimitedGraphQLRouter(schema)
    app.include_router(graphql_app, prefix="/graphql")

Complete Examples
-----------------

Example 1: E-commerce API
~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

    from ariadne import make_executable_schema, QueryType, MutationType, gql
    from ratethrottle import AriadneRateLimiter, GraphQLLimits
    
    type_defs = gql("""
        type Query {
            products(limit: Int): [Product!]!
            product(id: ID!): Product
            cart: Cart
        }
        
        type Mutation {
            addToCart(productId: ID!, quantity: Int!): Cart!
            checkout: Order!
        }
        
        type Product {
            id: ID!
            name: String!
            price: Float!
            reviews: [Review!]!
        }
        
        type Review {
            id: ID!
            rating: Int!
            comment: String!
        }
        
        type Cart {
            items: [CartItem!]!
            total: Float!
        }
        
        type CartItem {
            product: Product!
            quantity: Int!
        }
        
        type Order {
            id: ID!
            total: Float!
            status: String!
        }
    """)
    
    query = QueryType()
    mutation = MutationType()
    
    @query.field("products")
    def resolve_products(obj, info, limit=10):
        return get_products(limit=limit)
    
    @query.field("cart")
    def resolve_cart(obj, info):
        return get_user_cart(info.context['user_id'])
    
    @mutation.field("addToCart")
    def resolve_add_to_cart(obj, info, productId, quantity):
        return add_to_cart(info.context['user_id'], productId, quantity)
    
    @mutation.field("checkout")
    def resolve_checkout(obj, info):
        return process_checkout(info.context['user_id'])
    
    # Rate limiter with custom field costs
    limiter = AriadneRateLimiter(
        GraphQLLimits(
            queries_per_minute=200,      # Generous for browsing
            mutations_per_minute=10,      # Strict for checkout
            max_complexity=2000,
            max_depth=8,
            field_limits={
                'checkout': 5,            # Very strict for checkout
                'addToCart': 30           # Moderate for cart operations
            }
        ),
        custom_field_costs={
            'products': 10,               # Expensive list
            'reviews': 5,                 # Moderate nested list
            'checkout': 100               # Very expensive operation
        }
    )
    
    schema = make_executable_schema(type_defs, query, mutation, middleware=[limiter])

Example 2: Social Network API
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

    from ariadne import gql, QueryType, MutationType
    from ratethrottle import AriadneRateLimiter, GraphQLLimits
    
    type_defs = gql("""
        type Query {
            feed(limit: Int): [Post!]!
            user(id: ID!): User
            search(query: String!): [User!]!
        }
        
        type Mutation {
            createPost(content: String!): Post!
            likePost(postId: ID!): Post!
            follow(userId: ID!): User!
        }
        
        type User {
            id: ID!
            username: String!
            followers: [User!]!
            following: [User!]!
            posts(limit: Int): [Post!]!
        }
        
        type Post {
            id: ID!
            content: String!
            author: User!
            likes: Int!
            comments: [Comment!]!
        }
        
        type Comment {
            id: ID!
            content: String!
            author: User!
        }
    """)
    
    # Different limits for different user types
    def get_limits_for_user(user_id):
        """Get rate limits based on user tier"""
        user = get_user(user_id)
        
        if user.is_premium:
            return GraphQLLimits(
                queries_per_minute=1000,
                mutations_per_minute=100,
                max_complexity=5000,
                max_depth=20
            )
        else:
            return GraphQLLimits(
                queries_per_minute=100,
                mutations_per_minute=20,
                max_complexity=1000,
                max_depth=10
            )
    
    # Dynamic rate limiter
    def extract_client_id(context):
        """Extract user ID for personalized limits"""
        return f"user_{context.get('user_id', 'anonymous')}"
    
    limiter = AriadneRateLimiter(
        GraphQLLimits(
            queries_per_minute=100,  # Default
            mutations_per_minute=20,
            max_complexity=1000,
            max_depth=10,
            field_limits={
                'createPost': 10,     # Limit post creation
                'follow': 20,         # Limit follows
                'likePost': 60        # Limit likes
            }
        ),
        extract_client_id=extract_client_id,
        custom_field_costs={
            'feed': 20,              # Expensive
            'followers': 10,         # Moderate
            'comments': 5            # Light
        }
    )

Complexity Analysis
-------------------

How Complexity is Calculated
~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: graphql

    # Simple query: Complexity = 2
    query {
      user(id: 1) {    # Cost: 1
        name           # Cost: 1
      }
    }
    
    # Nested query: Complexity = 3 + (depth multiplier)
    query {
      user(id: 1) {    # Cost: 1
        posts {        # Cost: 1 * list_size (default 10) = 10
          title        # Cost: 1 * 10 (nested in list) = 10
        }
      }
    }
    # Total: ~21
    
    # With limit: Complexity adjusted
    query {
      user(id: 1) {
        posts(limit: 5) {  # Cost: 1 * 5 = 5
          title            # Cost: 1 * 5 = 5
          comments(limit: 3) {  # Cost: 1 * 5 * 3 = 15
            content        # Cost: 1 * 5 * 3 = 15
          }
        }
      }
    }
    # Total: ~40

Custom Field Costs
~~~~~~~~~~~~~~~~~~

.. code-block:: python

    # Define expensive fields
    custom_field_costs = {
        'analytics': 100,      # Very expensive calculation
        'recommendations': 50,  # Expensive ML operation
        'search': 30,          # Moderate database query
        'users': 20,           # Moderate list
        'posts': 10,           # Light list
    }
    
    limiter = GraphQLRateLimiter(
        GraphQLLimits(max_complexity=1000),
        custom_field_costs=custom_field_costs
    )
    
    # Now these queries have different costs:
    # query { users { name } }          # Cost: 20
    # query { recommendations { ... } }  # Cost: 50
    # query { analytics { ... } }        # Cost: 100

Depth Limiting
--------------

.. code-block:: graphql

    # Depth = 1
    query {
      user
    }
    
    # Depth = 2
    query {
      user {
        name
      }
    }
    
    # Depth = 3
    query {
      user {
        posts {
          title
        }
      }
    }
    
    # Depth = 5 (too deep!)
    query {
      user {
        posts {
          comments {
            author {
              posts {
                title
              }
            }
          }
        }
      }
    }

Field-Level Rate Limiting
-------------------------

.. code-block:: python

    # Limit specific expensive fields
    limiter = GraphQLRateLimiter(
        GraphQLLimits(
            queries_per_minute=100,
            field_limits={
                'analytics': 10,        # Only 10/min
                'generateReport': 5,    # Only 5/min
                'exportData': 2         # Only 2/min
            }
        )
    )
    
    # Now these fields have individual limits regardless of overall query rate

Violation Callbacks
-------------------

.. code-block:: python

    def on_rate_limit_violation(violation_info):
        """Handle rate limit violations"""
        violation_type = violation_info['type']
        client_id = violation_info['client_id']
        
        if violation_type == 'complexity':
            complexity = violation_info['complexity']
            limit = violation_info['limit']
            
            print(f"Client {client_id} exceeded complexity: {complexity} > {limit}")
            
            # Log to analytics
            log_violation('complexity', client_id, complexity)
            
        elif violation_type == 'depth':
            depth = violation_info['depth']
            limit = violation_info['limit']
            
            print(f"Client {client_id} exceeded depth: {depth} > {limit}")
            
        elif violation_type == 'operation_rate':
            operation_type = violation_info['operation_type']
            print(f"Client {client_id} exceeded {operation_type} rate")
            
        elif violation_type == 'field_rate':
            field_name = violation_info['field_name']
            print(f"Client {client_id} exceeded rate for field: {field_name}")
    
    limiter = GraphQLRateLimiter(
        on_violation=on_rate_limit_violation
    )

Configuration Examples
----------------------

Public API (Strict)
~~~~~~~~~~~~~~~~~~~

.. code-block:: python

    GraphQLLimits(
        queries_per_minute=60,
        mutations_per_minute=10,
        subscriptions_per_minute=5,
        max_complexity=500,
        max_depth=5
    )

Authenticated API (Moderate)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

    GraphQLLimits(
        queries_per_minute=300,
        mutations_per_minute=50,
        subscriptions_per_minute=20,
        max_complexity=2000,
        max_depth=10
    )

Premium/Internal (Generous)
~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

    GraphQLLimits(
        queries_per_minute=1000,
        mutations_per_minute=200,
        subscriptions_per_minute=100,
        max_complexity=10000,
        max_depth=20
    )

Best Practices
--------------

1. Set Reasonable Complexity Limits
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

    # Too strict - even simple queries fail
    GraphQLLimits(max_complexity=10)
    
    # Good - allows reasonable queries
    GraphQLLimits(max_complexity=1000)
    
    # Too loose - allows abuse
    GraphQLLimits(max_complexity=1000000)

2. Define Custom Costs for Expensive Fields
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

    custom_field_costs = {
        'generateReport': 500,   # Very expensive
        'analytics': 200,        # Expensive
        'search': 50,            # Moderate
        'users': 10              # Light
    }

3. Use Field-Level Limits for Critical Operations
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

    GraphQLLimits(
        field_limits={
            'createOrder': 5,      # Protect critical operations
            'deleteAccount': 1,     # Very strict
            'sendEmail': 10        # Prevent spam
        }
    )

4. Monitor and Adjust
~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

    def on_violation(info):
        # Track which limits are hit most often
        metrics.increment(f"rate_limit.{info['type']}")
        
        # Alert if specific users hit limits repeatedly
        if get_violation_count(info['client_id']) > 100:
            send_alert(f"User {info['client_id']} hitting limits frequently")

Summary
-------

* **Query complexity analysis** - Prevent expensive queries
* **Depth limiting** - Prevent deep nesting
* **Operation-specific limits** - Query/Mutation/Subscription
* **Field-level limiting** - Protect specific fields
* **Custom costs** - Define field complexity
* **Framework support** - Ariadne, Graphene, Strawberry
* **Monitoring** - Violation callbacks

Next Steps
----------

* See :doc:`websocket` configuration
* Explore :doc:`grpc` examples
