"""
The P19 tool registry package. Importing this package registers every
tool (the modules below each call register() once). The policy engine
and the API read the registry through `catalogue()` / `get_tool()` /
`all_tools()`.
"""

from .base import (  # noqa: F401
    Decision,
    ToolActor,
    ToolContext,
    ToolError,
    ToolSpec,
    all_tools,
    canonical_arguments,
    catalogue,
    get_tool,
    register,
)

# Import the tool modules for their registration side effects.
from . import read_tools, low_tools, high_tools  # noqa: F401,E402
