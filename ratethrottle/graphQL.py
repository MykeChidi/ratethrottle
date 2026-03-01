"""
RateThrottle - GraphQL Rate Limiting

GraphQL rate limiting with support for:
- Query complexity analysis
- Depth limiting
- Field-level rate limiting
- Mutation rate limiting
- Subscription rate limiting
- Ariadne, Graphene, Strawberry support
"""

import logging
from dataclasses import dataclass
from typing import Any, Callable, Dict, Optional, Set

from graphql import GraphQLError
from graphql.language import ast

logger = logging.getLogger(__name__)


@dataclass
class GraphQLLimits:
    """
    Configuration for GraphQL rate limits

    Args:
        queries_per_minute: Max queries per minute per client
        mutations_per_minute: Max mutations per minute per client
        subscriptions_per_minute: Max subscriptions per minute per client
        max_complexity: Max query complexity score
        max_depth: Max query depth
        field_limits: Per-field rate limits

    Example:
        >>> limits = GraphQLLimits(
        ...     queries_per_minute=100,
        ...     mutations_per_minute=20,
        ...     max_complexity=1000,
        ...     max_depth=10
        ... )
    """

    queries_per_minute: int = 1000
    mutations_per_minute: int = 100
    subscriptions_per_minute: int = 50
    max_complexity: int = 1000
    max_depth: int = 15
    field_limits: Optional[Dict[str, int]] = None


class ComplexityAnalyzer:
    """
    Analyze GraphQL query complexity

    Complexity calculation:
    - Each field: 1 point
    - Each nested level: multiplier
    - Lists: estimated by limit or default
    - Arguments: additional cost

    Example:
        >>> analyzer = ComplexityAnalyzer()
        >>> complexity = analyzer.calculate_complexity(query_ast)
    """

    def __init__(
        self,
        max_complexity: int = 1000,
        default_list_size: int = 10,
        field_costs: Optional[Dict[str, int]] = None,
    ):
        """
        Initialize complexity analyzer

        Args:
            max_complexity: Maximum allowed complexity
            default_list_size: Default list size for complexity calculation
            field_costs: Custom costs for specific fields
        """
        self.max_complexity = max_complexity
        self.default_list_size = default_list_size
        self.field_costs = field_costs or {}

    def calculate_complexity(self, document_ast, operation_name: Optional[str] = None) -> int:
        """
        Calculate complexity of GraphQL query

        Args:
            document_ast: Parsed GraphQL document
            operation_name: Specific operation to analyze

        Returns:
            Complexity score
        """
        try:
            # Find the operation
            operation = self._get_operation(document_ast, operation_name)

            if not operation:
                return 0

            # Calculate complexity recursively
            complexity = self._calculate_selection_set_complexity(operation.selection_set, depth=1)

            return complexity

        except Exception as e:
            logger.error(f"Error calculating complexity: {e}")
            return self.max_complexity  # Fail-safe: assume max complexity

    def _get_operation(self, document_ast, operation_name: Optional[str]):
        """Get specific operation from document"""
        operations = [
            definition
            for definition in document_ast.definitions
            if isinstance(definition, ast.OperationDefinitionNode)
        ]

        if not operations:
            return None

        if operation_name:
            for op in operations:
                if op.name and op.name.value == operation_name:
                    return op

        return operations[0]

    def _calculate_selection_set_complexity(
        self, selection_set, depth: int, multiplier: int = 1
    ) -> int:
        """Calculate complexity of selection set"""
        if not selection_set or not selection_set.selections:
            return 0

        total_complexity = 0

        for selection in selection_set.selections:
            if isinstance(selection, ast.FieldNode):
                # Get field name
                field_name = selection.name.value

                # Base cost (custom or default)
                field_cost = self.field_costs.get(field_name, 1)

                # Apply depth multiplier (deeper queries cost more)
                cost = field_cost * depth * multiplier

                # Check for list arguments
                list_multiplier = self._get_list_multiplier(selection)

                # Add field cost
                total_complexity += cost * list_multiplier

                # Recurse into nested selections
                if selection.selection_set:
                    nested_complexity = self._calculate_selection_set_complexity(
                        selection.selection_set, depth + 1, list_multiplier
                    )
                    total_complexity += nested_complexity

            elif isinstance(selection, ast.InlineFragmentNode):
                # Handle inline fragments
                if selection.selection_set:
                    total_complexity += self._calculate_selection_set_complexity(
                        selection.selection_set, depth, multiplier
                    )

            elif isinstance(selection, ast.FragmentSpreadNode):
                # Handle fragment spreads
                # Note: Would need fragment definitions from document
                # For now, add conservative estimate
                total_complexity += 10 * depth

        return total_complexity

    def _get_list_multiplier(self, field_node) -> int:
        """Get list multiplier from field arguments"""
        if not field_node.arguments:
            return 1

        # Look for limit/first/last arguments
        for arg in field_node.arguments:
            arg_name = arg.name.value.lower()

            if arg_name in ("limit", "first", "last", "take"):
                try:
                    if hasattr(arg.value, "value"):
                        return int(arg.value.value)
                except Exception:
                    pass

        # Default multiplier for lists
        return self.default_list_size


class DepthAnalyzer:
    """
    Analyze GraphQL query depth

    Example:
        >>> analyzer = DepthAnalyzer(max_depth=10)
        >>> depth = analyzer.calculate_depth(query_ast)
    """

    def __init__(self, max_depth: int = 15):
        """
        Initialize depth analyzer

        Args:
            max_depth: Maximum allowed depth
        """
        self.max_depth = max_depth

    def calculate_depth(self, document_ast, operation_name: Optional[str] = None) -> int:
        """Calculate depth of GraphQL query"""
        try:
            # Find operation
            operations = [
                definition
                for definition in document_ast.definitions
                if isinstance(definition, ast.OperationDefinitionNode)
            ]

            if not operations:
                return 0

            operation = operations[0]
            if operation_name:
                for op in operations:
                    if op.name and op.name.value == operation_name:
                        operation = op
                        break

            # Calculate depth
            return self._calculate_selection_set_depth(operation.selection_set, current_depth=1)

        except Exception as e:
            logger.error(f"Error calculating depth: {e}")
            return self.max_depth  # Fail-safe

    def _calculate_selection_set_depth(self, selection_set, current_depth: int) -> int:
        """Calculate depth of selection set"""
        if not selection_set or not selection_set.selections:
            return current_depth

        max_depth = current_depth

        for selection in selection_set.selections:
            if isinstance(selection, ast.FieldNode):
                if selection.selection_set:
                    depth = self._calculate_selection_set_depth(
                        selection.selection_set, current_depth + 1
                    )
                    max_depth = max(max_depth, depth)

            elif isinstance(selection, (ast.InlineFragmentNode, ast.FragmentSpreadNode)):
                if hasattr(selection, "selection_set") and selection.selection_set:
                    depth = self._calculate_selection_set_depth(
                        selection.selection_set, current_depth
                    )
                    max_depth = max(max_depth, depth)

        return max_depth


class GraphQLRateLimiter:
    """
    Comprehensive GraphQL rate limiting

    Features:
    - Query/Mutation/Subscription rate limiting
    - Complexity analysis and limiting
    - Depth analysis and limiting
    - Field-level rate limiting
    - Custom cost calculation

    Example:
        >>> limiter = GraphQLRateLimiter(
        ...     GraphQLLimits(
        ...         queries_per_minute=100,
        ...         max_complexity=1000
        ...     )
        ... )
    """

    def __init__(
        self,
        limits: Optional[GraphQLLimits] = None,
        storage=None,
        extract_client_id: Optional[Callable] = None,
        on_violation: Optional[Callable] = None,
        custom_field_costs: Optional[Dict[str, int]] = None,
    ):
        """
        Initialize GraphQL rate limiter

        Args:
            limits: Rate limits configuration
            storage: Storage backend
            extract_client_id: Function to extract client ID from context
            on_violation: Callback for violations
            custom_field_costs: Custom complexity costs per field
        """

        from .core import RateThrottleCore, RateThrottleRule
        from .storage_backend import InMemoryStorage

        self.limits = limits or GraphQLLimits()
        self.storage = storage or InMemoryStorage()
        self.extract_client_id = extract_client_id or self._default_extract_client_id
        self.on_violation = on_violation
        self.custom_field_costs = custom_field_costs or {}

        # Core rate limiter
        self.limiter = RateThrottleCore(storage=self.storage)

        # Add rate limiting rules
        self.limiter.add_rule(
            RateThrottleRule(
                name="graphql_queries", limit=self.limits.queries_per_minute, window=60
            )
        )

        self.limiter.add_rule(
            RateThrottleRule(
                name="graphql_mutations", limit=self.limits.mutations_per_minute, window=60
            )
        )

        self.limiter.add_rule(
            RateThrottleRule(
                name="graphql_subscriptions", limit=self.limits.subscriptions_per_minute, window=60
            )
        )

        # Complexity analyzer
        self.complexity_analyzer = ComplexityAnalyzer(
            max_complexity=self.limits.max_complexity, field_costs=self.custom_field_costs
        )

        # Depth analyzer
        self.depth_analyzer = DepthAnalyzer(max_depth=self.limits.max_depth)

        # Field-level limiters
        self.field_limiters: Dict[str, RateThrottleCore] = {}
        if self.limits.field_limits:
            for field_name, limit in self.limits.field_limits.items():
                field_limiter = RateThrottleCore(storage=self.storage)
                field_limiter.add_rule(
                    RateThrottleRule(name=f"graphql_field_{field_name}", limit=limit, window=60)
                )
                self.field_limiters[field_name] = field_limiter

        logger.info(f"GraphQL rate limiter initialized: {self.limits}")

    def _default_extract_client_id(self, context) -> str:
        """Extract client identifier from context"""
        # Try to get from request
        if hasattr(context, "request"):
            from .helpers import get_client_ip

            return get_client_ip(context.request)

        # Try user
        if hasattr(context, "user") and context.user:
            if hasattr(context.user, "id"):
                return f"user_{context.user.id}"

        return "unknown"

    def check_rate_limit(
        self,
        document_ast,
        context,
        operation_name: Optional[str] = None,
        variables: Optional[Dict] = None,
    ) -> Optional[GraphQLError]:
        """
        Check if GraphQL operation is allowed

        Args:
            document_ast: Parsed GraphQL document
            context: Request context
            operation_name: Operation name (if multiple in document)
            variables: Query variables

        Returns:
            GraphQLError if rate limited, None if allowed
        """
        try:
            # Extract client identifier
            client_id = self.extract_client_id(context)

            # Get operation type
            operation = self._get_operation(document_ast, operation_name)
            if not operation:
                return None

            operation_type = operation.operation.value  # query, mutation, subscription

            # Check operation-specific rate limit
            rule_name = f"graphql_{operation_type}s"
            status = self.limiter.check_rate_limit(client_id, rule_name)

            if not status.allowed:
                logger.warning(
                    f"GraphQL {operation_type} denied for {client_id} - " f"rate limit exceeded"
                )

                if self.on_violation:
                    self.on_violation(
                        {
                            "type": "operation_rate",
                            "client_id": client_id,
                            "operation_type": operation_type,
                            "retry_after": status.retry_after,
                        }
                    )

                return GraphQLError(
                    f"Rate limit exceeded for {operation_type}. "
                    f"Retry after {status.retry_after} seconds.",
                    extensions={
                        "code": "RATE_LIMIT_EXCEEDED",
                        "retry_after": status.retry_after,
                        "limit": status.limit,
                        "remaining": status.remaining,
                    },
                )

            # Check complexity
            complexity = self.complexity_analyzer.calculate_complexity(document_ast, operation_name)

            if complexity > self.limits.max_complexity:
                logger.warning(
                    f"GraphQL query denied for {client_id} - "
                    f"complexity {complexity} exceeds limit {self.limits.max_complexity}"
                )

                if self.on_violation:
                    self.on_violation(
                        {
                            "type": "complexity",
                            "client_id": client_id,
                            "complexity": complexity,
                            "limit": self.limits.max_complexity,
                        }
                    )

                return GraphQLError(
                    f"Query too complex. Complexity: {complexity}"
                    "Limit: {self.limits.max_complexity}",
                    extensions={
                        "code": "COMPLEXITY_LIMIT_EXCEEDED",
                        "complexity": complexity,
                        "max_complexity": self.limits.max_complexity,
                    },
                )

            # Check depth
            depth = self.depth_analyzer.calculate_depth(document_ast, operation_name)

            if depth > self.limits.max_depth:
                logger.warning(
                    f"GraphQL query denied for {client_id} - "
                    f"depth {depth} exceeds limit {self.limits.max_depth}"
                )

                if self.on_violation:
                    self.on_violation(
                        {
                            "type": "depth",
                            "client_id": client_id,
                            "depth": depth,
                            "limit": self.limits.max_depth,
                        }
                    )

                return GraphQLError(
                    f"Query too deep. Depth: {depth}, Limit: {self.limits.max_depth}",
                    extensions={
                        "code": "DEPTH_LIMIT_EXCEEDED",
                        "depth": depth,
                        "max_depth": self.limits.max_depth,
                    },
                )

            # Check field-level limits
            if self.field_limiters:
                field_error = self._check_field_limits(operation, client_id)
                if field_error:
                    return field_error

            # All checks passed
            return None

        except Exception as e:
            logger.error(f"Error checking rate limit: {e}")
            return None  # Fail open in case of errors

    def _get_operation(self, document_ast, operation_name: Optional[str]):
        """Get operation from document"""
        operations = [
            definition
            for definition in document_ast.definitions
            if isinstance(definition, ast.OperationDefinitionNode)
        ]

        if not operations:
            return None

        if operation_name:
            for op in operations:
                if op.name and op.name.value == operation_name:
                    return op

        return operations[0]

    def _check_field_limits(self, operation, client_id: str) -> Optional[GraphQLError]:
        """Check field-level rate limits"""
        # Extract field names from query
        field_names = self._extract_field_names(operation.selection_set)

        # Check each field
        for field_name in field_names:
            if field_name in self.field_limiters:
                limiter = self.field_limiters[field_name]
                rule_name = f"graphql_field_{field_name}"

                status = limiter.check_rate_limit(client_id, rule_name)

                if not status.allowed:
                    logger.warning(
                        f"GraphQL field '{field_name}' denied for {client_id} - "
                        f"field rate limit exceeded"
                    )

                    if self.on_violation:
                        self.on_violation(
                            {
                                "type": "field_rate",
                                "client_id": client_id,
                                "field_name": field_name,
                                "retry_after": status.retry_after,
                            }
                        )

                    return GraphQLError(
                        f"Rate limit exceeded for field '{field_name}'. "
                        f"Retry after {status.retry_after} seconds.",
                        extensions={
                            "code": "FIELD_RATE_LIMIT_EXCEEDED",
                            "field": field_name,
                            "retry_after": status.retry_after,
                        },
                    )

        return None

    def _extract_field_names(
        self, selection_set, field_names: Optional[Set[str]] = None
    ) -> Set[str]:
        """Extract all field names from selection set"""
        if field_names is None:
            field_names = set()

        if not selection_set or not selection_set.selections:
            return field_names

        for selection in selection_set.selections:
            if isinstance(selection, ast.FieldNode):
                field_names.add(selection.name.value)

                if selection.selection_set:
                    self._extract_field_names(selection.selection_set, field_names)

        return field_names

    def get_statistics(self) -> Dict[str, Any]:
        """Get rate limiting statistics"""
        return {
            "limits": {
                "queries_per_minute": self.limits.queries_per_minute,
                "mutations_per_minute": self.limits.mutations_per_minute,
                "subscriptions_per_minute": self.limits.subscriptions_per_minute,
                "max_complexity": self.limits.max_complexity,
                "max_depth": self.limits.max_depth,
            },
            "metrics": self.limiter.get_metrics(),
        }


# ============================================
# Framework Integrations
# ============================================


class AriadneRateLimiter:
    """
    Ariadne GraphQL rate limiting middleware

    Example:
        >>> from ariadne import make_executable_schema, QueryType
        >>> from ratethrottle import AriadneRateLimiter, GraphQLLimits
        >>>
        >>> limiter = AriadneRateLimiter(
        ...     GraphQLLimits(queries_per_minute=100)
        ... )
        >>>
        >>> schema = make_executable_schema(
        ...     type_defs,
        ...     query,
        ...     middleware=[limiter]
        ... )
    """

    def __init__(self, limits: Optional[GraphQLLimits] = None, **kwargs):
        """Initialize Ariadne rate limiter"""
        self.limiter = GraphQLRateLimiter(limits, **kwargs)

    def __call__(self, next_resolver, root, info, **kwargs):
        """Middleware function for Ariadne"""
        # Check rate limit before executing
        error = self.limiter.check_rate_limit(
            info.context["document"],
            info.context,
            info.operation.name.value if info.operation.name else None,
        )

        if error:
            raise error

        # Continue to resolver
        return next_resolver(root, info, **kwargs)
