"""IDE integrations package."""

# 1. Standard library imports
# (None)

# 2. Third-party imports
# (None)

# 3. Local / internal imports
from nemo.integrations.ide.antigravity import AntigravityAdapter
from nemo.integrations.ide.base import IDEAdapter
from nemo.integrations.ide.registry import IDERegistry
from nemo.integrations.ide.vscode import VSCodeAdapter

# 4. Types, Protocols, Schemas
# (None)

# 5. Core logic / classes / functions
# (None)

# 6. Public exports
__all__ = ["IDEAdapter", "AntigravityAdapter", "VSCodeAdapter", "IDERegistry"]

