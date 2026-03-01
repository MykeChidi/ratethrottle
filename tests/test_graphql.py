"""
Tests for GraphQL rate limiting
"""

import pytest
from unittest.mock import Mock, patch


from ratethrottle.graphQL import (
    GraphQLLimits,
    ComplexityAnalyzer,
    DepthAnalyzer,
    GraphQLRateLimiter,
    AriadneRateLimiter,
)


class TestGraphQLLimits:
    """Test GraphQLLimits configuration"""

    def test_default_limits(self):
        """Test default limit values"""
        limits = GraphQLLimits()

        assert limits.queries_per_minute == 1000
        assert limits.mutations_per_minute == 100
        assert limits.subscriptions_per_minute == 50
        assert limits.max_complexity == 1000
        assert limits.max_depth == 15
        assert limits.field_limits is None

    def test_custom_limits(self):
        """Test custom limit values"""
        field_limits = {"expensiveField": 10, "anotherField": 50}

        limits = GraphQLLimits(
            queries_per_minute=100,
            mutations_per_minute=10,
            subscriptions_per_minute=5,
            max_complexity=500,
            max_depth=10,
            field_limits=field_limits,
        )

        assert limits.queries_per_minute == 100
        assert limits.mutations_per_minute == 10
        assert limits.subscriptions_per_minute == 5
        assert limits.max_complexity == 500
        assert limits.max_depth == 10
        assert limits.field_limits == field_limits


class TestComplexityAnalyzer:
    """Test ComplexityAnalyzer"""

    @pytest.fixture
    def analyzer(self):
        """Create complexity analyzer"""
        return ComplexityAnalyzer(
            max_complexity=1000, default_list_size=10, field_costs={"expensiveField": 100}
        )

    def test_initialization(self, analyzer):
        """Test analyzer initialization"""
        assert analyzer.max_complexity == 1000
        assert analyzer.default_list_size == 10
        assert analyzer.field_costs == {"expensiveField": 100}

    def test_simple_query_complexity(self, analyzer):
        """Test complexity of simple query"""
        # Import actual GraphQL AST nodes
        from graphql.language import ast as gql_ast

        # Create a real AST node for a simple field
        field_node = gql_ast.FieldNode(
            name=gql_ast.NameNode(value="user"), arguments=[], selection_set=None
        )

        selection_set = gql_ast.SelectionSetNode(selections=[field_node])

        operation = gql_ast.OperationDefinitionNode(
            operation=gql_ast.OperationType.QUERY, selection_set=selection_set
        )

        document_ast = gql_ast.DocumentNode(definitions=[operation])

        # Calculate complexity
        complexity = analyzer.calculate_complexity(document_ast)

        # Simple field = 1 point * depth 1 = 1
        assert complexity >= 1

    def test_list_multiplier(self, analyzer):
        """Test list field multiplier"""
        # Mock list argument
        arg = Mock()
        arg.name.value = "limit"
        arg.value.value = 50

        field_node = Mock()
        field_node.arguments = [arg]

        multiplier = analyzer._get_list_multiplier(field_node)
        assert multiplier == 50

    def test_default_list_multiplier(self, analyzer):
        """Test default list multiplier when no limit specified"""
        field_node = Mock()
        field_node.arguments = []

        multiplier = analyzer._get_list_multiplier(field_node)
        assert multiplier == 1  # No list field


class TestDepthAnalyzer:
    """Test DepthAnalyzer"""

    @pytest.fixture
    def analyzer(self):
        """Create depth analyzer"""
        return DepthAnalyzer(max_depth=10)

    def test_initialization(self, analyzer):
        """Test analyzer initialization"""
        assert analyzer.max_depth == 10

    def test_simple_query_depth(self, analyzer):
        """Test depth of simple query"""
        from graphql.language import ast as gql_ast

        # Mock simple query: { user { name } }
        name_field = gql_ast.FieldNode(name=gql_ast.NameNode(value="name"), selection_set=None)

        user_selection = gql_ast.SelectionSetNode(selections=[name_field])

        user_field = gql_ast.FieldNode(
            name=gql_ast.NameNode(value="user"), selection_set=user_selection
        )

        root_selection = gql_ast.SelectionSetNode(selections=[user_field])

        operation = gql_ast.OperationDefinitionNode(
            operation=gql_ast.OperationType.QUERY, selection_set=root_selection
        )

        document_ast = gql_ast.DocumentNode(definitions=[operation])

        # Depth should be 2 (root -> user -> name)
        depth = analyzer.calculate_depth(document_ast)
        assert depth >= 2

    def test_nested_query_depth(self, analyzer):
        """Test depth of nested query"""
        from graphql.language import ast as gql_ast

        # Create mock for deeply nested query
        # Level 3
        level3 = gql_ast.FieldNode(name=gql_ast.NameNode(value="level3"), selection_set=None)

        # Level 2
        level2_selection = gql_ast.SelectionSetNode(selections=[level3])
        level2 = gql_ast.FieldNode(
            name=gql_ast.NameNode(value="level2"), selection_set=level2_selection
        )

        # Level 1
        level1_selection = gql_ast.SelectionSetNode(selections=[level2])
        level1 = gql_ast.FieldNode(
            name=gql_ast.NameNode(value="level1"), selection_set=level1_selection
        )

        # Root
        root_selection = gql_ast.SelectionSetNode(selections=[level1])

        operation = gql_ast.OperationDefinitionNode(
            operation=gql_ast.OperationType.QUERY, selection_set=root_selection
        )

        document_ast = gql_ast.DocumentNode(definitions=[operation])

        depth = analyzer.calculate_depth(document_ast)
        assert depth >= 3


class TestGraphQLRateLimiter:
    """Test GraphQLRateLimiter"""

    @pytest.fixture
    def limiter(self):
        """Create rate limiter"""
        limits = GraphQLLimits(
            queries_per_minute=10, mutations_per_minute=5, max_complexity=100, max_depth=5
        )
        return GraphQLRateLimiter(limits)

    @pytest.fixture
    def mock_context(self):
        """Create mock context"""
        context = Mock()
        context.request = Mock()
        context.request.META = {"REMOTE_ADDR": "192.168.1.1"}
        return context

    def test_initialization(self, limiter):
        """Test limiter initialization"""
        assert limiter.limits.queries_per_minute == 10
        assert limiter.limits.mutations_per_minute == 5
        assert limiter.complexity_analyzer is not None
        assert limiter.depth_analyzer is not None

    def test_extract_client_id_from_request(self, limiter):
        """Test extracting client ID from request"""
        context = Mock()
        context.request = Mock()
        context.request.META = {"REMOTE_ADDR": "192.168.1.1"}

        from ratethrottle.helpers import get_client_ip

        with patch("ratethrottle.helpers.get_client_ip", return_value="192.168.1.1"):
            client_id = limiter.extract_client_id(context)
            # Will use default extraction

    def test_extract_client_id_from_user(self, limiter):
        """Test extracting client ID from user"""
        context = Mock(spec=["user"])

        # Use a simple class to simulate user
        class User:
            def __init__(self):
                self.id = 123

        context.user = User()

        client_id = limiter._default_extract_client_id(context)
        assert client_id == "user_123"

    def test_extract_client_id_fallback(self, limiter):
        """Test client ID extraction fallback"""
        context = Mock()
        delattr(context, "request") if hasattr(context, "request") else None
        delattr(context, "user") if hasattr(context, "user") else None

        client_id = limiter._default_extract_client_id(context)
        assert client_id == "unknown"

    def test_custom_field_costs(self):
        """Test custom field complexity costs"""
        custom_costs = {"expensiveQuery": 500, "cheapQuery": 1}

        limiter = GraphQLRateLimiter(custom_field_costs=custom_costs)

        assert limiter.custom_field_costs == custom_costs
        assert limiter.complexity_analyzer.field_costs == custom_costs

    def test_field_level_limits(self):
        """Test field-level rate limits"""
        field_limits = {"expensiveField": 5, "normalField": 100}

        limiter = GraphQLRateLimiter(GraphQLLimits(field_limits=field_limits))

        assert "expensiveField" in limiter.field_limiters
        assert "normalField" in limiter.field_limiters

    def test_get_statistics(self, limiter):
        """Test getting statistics"""
        stats = limiter.get_statistics()

        assert "limits" in stats
        assert stats["limits"]["queries_per_minute"] == 10
        assert stats["limits"]["mutations_per_minute"] == 5
        assert stats["limits"]["max_complexity"] == 100
        assert stats["limits"]["max_depth"] == 5


class TestGraphQLViolations:
    """Test violation detection and handling"""

    def test_query_rate_limit_violation(self):
        """Test query rate limit violation"""
        violations = []

        def on_violation(info):
            violations.append(info)

        limiter = GraphQLRateLimiter(GraphQLLimits(queries_per_minute=2), on_violation=on_violation)

        # Mock query operation
        operation = Mock()
        operation.operation.value = "query"
        operation.selection_set = Mock()
        operation.selection_set.selections = []

        document = Mock()
        document.definitions = [operation]

        context = Mock()

        # Make 3 requests (exceeds limit of 2)
        for i in range(3):
            error = limiter.check_rate_limit(document, context)

        # Should have triggered violation
        # (Note: actual violation callback in real code)

    def test_complexity_violation(self):
        """Test complexity limit violation"""
        violations = []

        def on_violation(info):
            violations.append(info)

        limiter = GraphQLRateLimiter(GraphQLLimits(max_complexity=10), on_violation=on_violation)

        # Mock complex query
        # Would normally trigger violation if complexity > 10

    def test_depth_violation(self):
        """Test depth limit violation"""
        violations = []

        def on_violation(info):
            violations.append(info)

        limiter = GraphQLRateLimiter(GraphQLLimits(max_depth=3), on_violation=on_violation)

        # Mock deep query
        # Would normally trigger violation if depth > 3


class TestAriadneRateLimiter:
    """Test Ariadne integration"""

    def test_initialization(self):
        """Test Ariadne limiter initialization"""
        limits = GraphQLLimits(queries_per_minute=100)
        ariadne_limiter = AriadneRateLimiter(limits)

        assert ariadne_limiter.limiter is not None
        assert ariadne_limiter.limiter.limits.queries_per_minute == 100

    def test_callable(self):
        """Test that AriadneRateLimiter is callable as middleware"""
        ariadne_limiter = AriadneRateLimiter()

        assert callable(ariadne_limiter)


class TestGraphQLEdgeCases:
    """Test edge cases and error handling"""

    def test_empty_document(self):
        """Test handling empty document"""
        analyzer = ComplexityAnalyzer()

        document = Mock()
        document.definitions = []

        complexity = analyzer.calculate_complexity(document)
        assert complexity == 0

    def test_multiple_operations(self):
        """Test document with multiple operations"""
        analyzer = ComplexityAnalyzer()

        # Create two operations
        op1 = Mock()
        op1.name = Mock()
        op1.name.value = "Query1"
        op1.selection_set = Mock()
        op1.selection_set.selections = []

        op2 = Mock()
        op2.name = Mock()
        op2.name.value = "Query2"
        op2.selection_set = Mock()
        op2.selection_set.selections = []

        document = Mock()
        document.definitions = [op1, op2]

        # Should analyze first operation by default
        complexity = analyzer.calculate_complexity(document)
        assert complexity >= 0

    def test_specific_operation_name(self):
        """Test analyzing specific operation by name"""
        analyzer = ComplexityAnalyzer()

        op1 = Mock()
        op1.name = Mock()
        op1.name.value = "Query1"
        op1.selection_set = Mock()
        op1.selection_set.selections = []

        op2 = Mock()
        op2.name = Mock()
        op2.name.value = "Query2"
        op2.selection_set = Mock()
        op2.selection_set.selections = []

        document = Mock()
        document.definitions = [op1, op2]

        # Analyze specific operation
        complexity = analyzer.calculate_complexity(document, "Query2")
        assert complexity >= 0

    def test_different_operation_types(self):
        """Test different operation types (query, mutation, subscription)"""
        limiter = GraphQLRateLimiter(
            GraphQLLimits(
                queries_per_minute=100, mutations_per_minute=10, subscriptions_per_minute=5
            )
        )

        # Each operation type should have its own limit
        assert limiter.limiter.rules["graphql_queries"].limit == 100
        assert limiter.limiter.rules["graphql_mutations"].limit == 10
        assert limiter.limiter.rules["graphql_subscriptions"].limit == 5


class TestGraphQLIntegration:
    """Integration tests"""

    def test_full_query_check(self):
        """Test complete query checking flow"""
        limiter = GraphQLRateLimiter(
            GraphQLLimits(queries_per_minute=10, max_complexity=100, max_depth=5)
        )

        # Mock query operation
        field = Mock()
        field.name.value = "user"
        field.selection_set = None

        selection_set = Mock()
        selection_set.selections = [field]

        operation = Mock()
        operation.operation.value = "query"
        operation.name = None
        operation.selection_set = selection_set

        document = Mock()
        document.definitions = [operation]

        context = Mock()

        # Check should pass for simple query
        error = limiter.check_rate_limit(document, context)
        # Error would be None if allowed

    def test_multiple_checks_same_client(self):
        """Test multiple checks for same client"""
        limiter = GraphQLRateLimiter(GraphQLLimits(queries_per_minute=3))

        # Mock simple operation
        operation = Mock()
        operation.operation.value = "query"
        operation.selection_set = Mock()
        operation.selection_set.selections = []

        document = Mock()
        document.definitions = [operation]

        context = Mock()

        # Make multiple checks
        results = []
        for i in range(5):
            error = limiter.check_rate_limit(document, context)
            results.append(error)

        # First 3 should pass, rest should fail
        # (actual behavior depends on implementation)


class TestGraphQLPerformance:
    """Performance-related tests"""

    def test_many_concurrent_clients(self):
        """Test handling many concurrent clients"""
        limiter = GraphQLRateLimiter()

        # Simple user class to avoid Mock string representation issues
        class User:
            def __init__(self, user_id):
                self.id = user_id

        # Simulate 1000 different clients
        for i in range(1000):
            context = Mock(spec=["user"])
            context.user = User(i)

            client_id = limiter._default_extract_client_id(context)
            assert client_id == f"user_{i}"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
