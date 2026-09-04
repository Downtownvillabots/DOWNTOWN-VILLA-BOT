"""
Plugin loader.

Automatically imports all Python files in this folder.
Each plugin can register handlers using the @app.on_message decorator.
"""

import importlib
import inspect
import pkgutil
from typing import List


def load_plugins(app) -> List[str]:
    """
    Import all modules inside the plugins package.
    Returns list of imported module names.
    """
    imported = []
    package_path = __path__  # path of this package

    for module_info in pkgutil.iter_modules(package_path):
        module_name = f"{__name__}.{module_info.name}"
        module = importlib.import_module(module_name)
        # Optional: call a setup function if defined
        if hasattr(module, "setup"):
            module.setup(app)
        imported.append(module_name)

    return imported
