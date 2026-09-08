"""
Plugin loader.

Automatically imports all Python files in this folder.
Each plugin can register handlers using the @app.on_message decorator.
"""

import importlib
import inspect
import pkgutil
import logging
from typing import List

logger = logging.getLogger("plugins.loader")

def load_plugins(app) -> List[str]:
    """
    Import all modules inside the plugins package.
    Returns list of imported module names.
    """
    imported = []
    package_path = __path__  # path of this package

    for module_info in pkgutil.iter_modules(package_path):
        module_name = f"{__name__}.{module_info.name}"
        try:
            module = importlib.import_module(module_name)
            # Call setup function if defined, and log it
            if hasattr(module, "setup"):
                logger.info("Calling setup for %s", module_name)
                module.setup(app)
                logger.info("Setup completed for %s", module_name)
            else:
                logger.warning("Module %s has no setup function.", module_name)
            imported.append(module_name)
        except Exception as e:
            logger.exception("Failed to load plugin %s: %s", module_name, e)
            raise  # or continue? Better to crash so we know.

    return imported
