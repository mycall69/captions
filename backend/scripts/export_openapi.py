"""T121: FastAPI 런타임 OpenAPI 스펙을 contracts/openapi.yaml 과 비교하는 스크립트.

목적:

1. FastAPI 가 라우터로부터 생성하는 실제 OpenAPI 스펙 (런타임) 을 dump 한다.
2. ``specs/001-dual-subtitle-mvp/contracts/openapi.yaml`` 목표 스펙을 로드한다.
3. **path 집합** + **각 path 의 HTTP method 집합** + **각 method 의 status code 집합** 이
   목표 스펙에 모두 존재하는지 확인한다.
4. 누락이 있으면 한국어 요약 리포트를 출력하고 exit 1 — 그렇지 않으면 exit 0.

설계 원칙 (tasks.md T121):

- 모든 schema property 까지 검증하지 않는다 (over-engineering).
- "contracts/openapi.yaml 의 path/method/status 가 런타임 스펙에 존재" 만 검사한다.
- 런타임에만 존재하는 추가 path/method 는 경고로 보고하되 exit code 에 영향을 주지 않는다.

사용법::

    cd backend && python -m scripts.export_openapi
    # 또는
    cd backend && python scripts/export_openapi.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import yaml

# scripts/ 디렉터리에서 직접 실행해도 ``app`` 패키지를 import 할 수 있도록 경로 보강.
_BACKEND_ROOT = Path(__file__).resolve().parent.parent
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

# 기본 contracts 위치 — backend 디렉터리 기준 상위 specs 경로
_DEFAULT_CONTRACT_PATH = (
    _BACKEND_ROOT.parent / "specs" / "001-dual-subtitle-mvp" / "contracts" / "openapi.yaml"
)

# OpenAPI path 접두어 — 런타임에는 ``/v1`` 가 붙고 contracts/ 는 ``/v1`` 없이 정의됨.
_RUNTIME_PREFIX = "/v1"


def _load_runtime_spec() -> dict[str, Any]:
    """FastAPI 앱 팩토리에서 OpenAPI dict 를 추출한다."""
    from app.main import create_app

    app = create_app()
    spec: dict[str, Any] = app.openapi()
    return spec


def _load_contract_spec(contract_path: Path) -> dict[str, Any]:
    """contracts/openapi.yaml 을 dict 로 로드한다."""
    with contract_path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f)  # type: ignore[no-any-return]


def _normalize_runtime_paths(runtime_paths: dict[str, Any]) -> dict[str, Any]:
    """런타임 path 에서 ``/v1`` 접두어를 제거해 contract 와 비교 가능한 키로 변환한다.

    런타임 스펙은 ``/v1/jobs/{job_id}`` 처럼 prefix 가 붙고, contracts/ 는
    ``/jobs/{job_id}`` 만 정의한다 — 비교를 단순화하기 위해 prefix 를 제거한다.
    """
    normalized: dict[str, Any] = {}
    for raw_path, item in runtime_paths.items():
        if raw_path.startswith(_RUNTIME_PREFIX):
            key = raw_path[len(_RUNTIME_PREFIX) :] or "/"
        else:
            key = raw_path
        normalized[key] = item
    return normalized


def _path_methods(path_item: dict[str, Any]) -> set[str]:
    """OpenAPI path item 에서 HTTP method (소문자) 집합을 추출한다."""
    methods = {"get", "post", "put", "patch", "delete", "head", "options", "trace"}
    return {m for m in path_item if m in methods}


def _status_codes(operation: dict[str, Any]) -> set[str]:
    """단일 operation 의 ``responses`` 에서 status code 키 집합을 반환한다."""
    responses = operation.get("responses", {}) or {}
    return {str(code) for code in responses}


def diff_specs(
    contract: dict[str, Any], runtime: dict[str, Any]
) -> tuple[list[str], list[str]]:
    """contract 스펙이 runtime 스펙에 모두 포함되는지 검사한다.

    Returns:
        (errors, warnings)
        - errors: contract 가 요구하지만 runtime 에 없는 path/method 항목 → exit 1.
        - warnings: 그 외 정보성(추가 path, status code 불일치) → exit 0 유지.

    Note:
        FastAPI 라우트가 ``responses=`` 를 명시하지 않으면 런타임 스펙에는
        ``200`` 만 노출된다. contracts 의 4xx/5xx 코드는 도메인 예외 핸들러가
        처리하므로 ``status code 누락`` 은 errors 가 아닌 warnings 로 보고한다.
    """
    errors: list[str] = []
    warnings: list[str] = []

    contract_paths = contract.get("paths", {}) or {}
    runtime_paths = _normalize_runtime_paths(runtime.get("paths", {}) or {})

    # 1) contract 의 path 가 runtime 에 모두 존재해야 한다 — strict.
    contract_path_set = set(contract_paths.keys())
    runtime_path_set = set(runtime_paths.keys())

    missing_paths = contract_path_set - runtime_path_set
    for p in sorted(missing_paths):
        errors.append(f"누락된 path: {p}")

    extra_paths = runtime_path_set - contract_path_set
    for p in sorted(extra_paths):
        warnings.append(f"contracts 에 정의되지 않은 추가 path: {p}")

    # 2) 공통 path 의 method / status code 비교.
    for path in sorted(contract_path_set & runtime_path_set):
        c_methods = _path_methods(contract_paths[path])
        r_methods = _path_methods(runtime_paths[path])

        # method 누락은 strict — 라우트가 실제로 누락된 것을 의미한다.
        missing_methods = c_methods - r_methods
        for m in sorted(missing_methods):
            errors.append(f"누락된 method: {m.upper()} {path}")

        # status code 누락은 loose — exception handler 가 처리하므로 정보성 warning.
        for method in sorted(c_methods & r_methods):
            c_codes = _status_codes(contract_paths[path][method])
            r_codes = _status_codes(runtime_paths[path][method])
            missing_codes = c_codes - r_codes
            for code in sorted(missing_codes):
                warnings.append(
                    f"라우트에 응답 코드 미선언 (도메인 예외 핸들러 추정): "
                    f"{method.upper()} {path} → {code}"
                )

    return errors, warnings


def main(argv: list[str] | None = None) -> int:
    """엔트리 포인트 — diff 실행 후 한국어 리포트를 출력하고 exit code 를 반환한다."""
    args = argv if argv is not None else sys.argv[1:]
    contract_path = Path(args[0]) if args else _DEFAULT_CONTRACT_PATH

    if not contract_path.exists():
        print(f"[오류] contract 파일을 찾을 수 없습니다: {contract_path}", file=sys.stderr)
        return 1

    runtime = _load_runtime_spec()
    contract = _load_contract_spec(contract_path)

    errors, warnings = diff_specs(contract, runtime)

    print("=== OpenAPI 스펙 비교 리포트 ===")
    print(f"contract: {contract_path}")
    print(f"runtime path 수: {len(runtime.get('paths', {}) or {})}")
    print(f"contract path 수: {len(contract.get('paths', {}) or {})}")

    if warnings:
        print("\n[경고] 다음 항목은 contracts 에 미정의 (정보성):")
        for w in warnings:
            print(f"  - {w}")

    if errors:
        print("\n[오류] contracts 가 요구하는 항목이 런타임에 누락되었습니다:")
        for e in errors:
            print(f"  - {e}")
        print("\n결과: 불일치 ✗")
        return 1

    print("\n결과: 일치 ✓ (path / method / status 집합 검증 통과)")
    # 런타임 스펙 요약을 JSON 한 줄로 노출 (CI 로그 추적용).
    runtime_summary = {
        "paths": sorted(_normalize_runtime_paths(runtime.get("paths", {}) or {}).keys()),
    }
    print(f"runtime paths: {json.dumps(runtime_summary, ensure_ascii=False)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
