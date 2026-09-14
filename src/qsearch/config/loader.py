"""Configuration loader for question matching system.

Loads and validates YAML configuration files for feature extraction and matching.
"""

import copy
from pathlib import Path
from typing import Any, Dict, Optional, Union

import yaml

from qsearch.config import presets


class ConfigLoader:
    """Loads and manages YAML-based configuration files.

    Supports loading from files, merging multiple configs, and runtime overrides
    while maintaining immutability of base configuration.
    """

    def __init__(self, config_path: Optional[Union[str, Path]] = None):
        """Initialize ConfigLoader.

        Args:
            config_path: Path to YAML configuration file. If None, uses empty base config.
        """
        self._base_config: Dict[str, Any] = {}

        if config_path is not None:
            self._base_config = self.load_yaml(config_path)

    @staticmethod
    def load_yaml(path: Union[str, Path]) -> Dict[str, Any]:
        """Load configuration from YAML file.

        Args:
            path: Path to YAML file

        Returns:
            Parsed configuration dictionary

        Raises:
            FileNotFoundError: If file does not exist
            yaml.YAMLError: If YAML parsing fails
        """
        path = Path(path)

        if not path.exists():
            raise FileNotFoundError(f"Configuration file not found: {path}")

        try:
            with open(path, 'r', encoding='utf-8') as f:
                config = yaml.safe_load(f)

            if config is None:
                return {}

            if not isinstance(config, dict):
                raise ValueError(f"Configuration must be a dictionary, got {type(config).__name__}")

            return config

        except yaml.YAMLError as e:
            raise yaml.YAMLError(f"Failed to parse YAML file {path}: {e}")

    def merge_configs(self, *configs: Dict[str, Any]) -> Dict[str, Any]:
        """Merge multiple configuration dictionaries.

        Later configs override earlier ones. Nested dictionaries are merged recursively.

        Args:
            *configs: Configuration dictionaries to merge

        Returns:
            Merged configuration dictionary
        """
        result = {}

        for config in configs:
            result = self._deep_merge(result, config)

        return result

    @staticmethod
    def _deep_merge(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
        """Recursively merge two dictionaries.

        Args:
            base: Base dictionary
            override: Dictionary with override values

        Returns:
            New merged dictionary (does not mutate inputs)
        """
        result = copy.deepcopy(base)

        for key, value in override.items():
            if key in result and isinstance(result[key], dict) and isinstance(value, dict):
                result[key] = ConfigLoader._deep_merge(result[key], value)
            else:
                result[key] = copy.deepcopy(value)

        return result

    def get_config(self, overrides: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Get configuration with optional runtime overrides.

        Args:
            overrides: Optional dictionary of override values

        Returns:
            Configuration dictionary (base config merged with overrides)
        """
        if overrides is None:
            return copy.deepcopy(self._base_config)

        return self.merge_configs(self._base_config, overrides)

    @property
    def base_config(self) -> Dict[str, Any]:
        """Get copy of base configuration."""
        return copy.deepcopy(self._base_config)

    def load_preset(self, preset_name: str) -> Dict[str, Any]:
        """Load a configuration preset by name.

        Args:
            preset_name: Name of the preset (conservative, balanced, aggressive)

        Returns:
            Configuration dictionary from the preset

        Raises:
            ValueError: If preset name is not recognized
        """
        return presets.get_preset(preset_name)

    def load_multiple(self, *paths: Union[str, Path]) -> Dict[str, Any]:
        """Load and merge multiple configuration files.

        Args:
            *paths: Paths to YAML configuration files

        Returns:
            Merged configuration dictionary
        """
        configs = [self.load_yaml(path) for path in paths]
        return self.merge_configs(*configs)

    def export_yaml(self, config: Dict[str, Any], output_path: Union[str, Path]) -> None:
        """Export configuration to YAML file.

        Args:
            config: Configuration dictionary to export
            output_path: Path where YAML file will be written
        """
        output_path = Path(output_path)

        # Atomic write: write to temp file then rename
        temp_path = output_path.with_suffix('.tmp')

        try:
            with open(temp_path, 'w', encoding='utf-8') as f:
                yaml.safe_dump(config, f, default_flow_style=False, allow_unicode=True, sort_keys=False)

            # Atomic rename
            temp_path.replace(output_path)

        except Exception as e:
            # Clean up temp file on error
            if temp_path.exists():
                temp_path.unlink()
            raise IOError(f"Failed to export configuration to {output_path}: {e}")
