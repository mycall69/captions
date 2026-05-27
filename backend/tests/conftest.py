"""테스트 공통 설정.

backend 디렉터리를 sys.path에 추가하여 `pip install -e .` 없이도
`from app.core ...` 임포트가 가능하도록 한다.
"""

import pathlib
import sys

# backend/ 디렉터리를 경로에 추가
_BACKEND_DIR = pathlib.Path(__file__).parent.parent
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))
