import sys
sys.path.insert(0, '.')
from src.qsearch.config.loader import ConfigLoader

# Test loading valid config
loader = ConfigLoader('test_config.yaml')
config = loader.get_config()
print('✓ Valid config loaded successfully')
print(f'  text.components.stem.weight = {config["text"]["components"]["stem"]["weight"]}')

# Test runtime overrides
overrides = {'matching': {'content_match': {'threshold': 0.90}}}
merged = loader.get_config(overrides)
print(f'✓ Runtime override applied: threshold = {merged["matching"]["content_match"]["threshold"]}')
print(f'✓ Base config unchanged: threshold = {config["matching"]["content_match"]["threshold"]}')

# Test export
loader.export_yaml(merged, 'test_export.yaml')
print('✓ Configuration exported successfully')
