# tests/conftest.py

import sys
from pathlib import Path

# Add the project root directory to the system path to ensure
# modules like 'common' and 'agent' can be imported in tests.
# The project root is two levels up from this file (tests/conftest.py).
project_root = Path(__file__).parent.parent.resolve()
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))
