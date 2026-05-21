import os
import importlib.util
import inspect
from .base import ProviderPlugin

class PluginManager:
    def __init__(self):
        self.plugins = {}
        self._load_plugins()

    def _load_plugins(self):
        import importlib
        plugins_dir = os.path.dirname(__file__)
        for filename in os.listdir(plugins_dir):
            if filename.endswith('.py') and filename not in ('__init__.py', 'base.py', 'manager.py'):
                module_name = filename[:-3]
                module = importlib.import_module(f'.{module_name}', package='plugins')
                
                for name, obj in inspect.getmembers(module, inspect.isclass):
                    if (issubclass(obj, ProviderPlugin)
                            and obj is not ProviderPlugin
                            and not inspect.isabstract(obj)):
                        plugin_instance = obj()
                        self.plugins[plugin_instance.plugin_id] = plugin_instance

    def get_plugin(self, plugin_id: str) -> ProviderPlugin:
        return self.plugins.get(plugin_id)

    def get_all_plugins(self):
        return list(self.plugins.values())

plugin_manager = PluginManager()
