"""Simple registry for tool tabs in the standalone main window.

Future tools (e.g. a Variation Splitter) register themselves here and
appear as additional tabs in the ``StandaloneMainWindow``.
"""

_TOOLS = []


def register_tool(name, widget_class):
    """Register a tool tab.  *widget_class* must be a ``QWidget`` subclass."""
    _TOOLS.append((name, widget_class))


def iter_tools():
    """Yield ``(name, widget_class)`` for all registered tools."""
    return iter(_TOOLS)
