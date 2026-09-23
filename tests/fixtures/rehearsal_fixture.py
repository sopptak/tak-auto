"""6-31 Operational Rehearsal Engine - 공유 fixture 진입점.

새 KNOWLEDGE->MEDIA 생성 로직을 만들지 않는다(6-31 6장 지시). 6-28
(``tests/test_full_e2e_operating_readiness.py``)이 이미 구축한
synthetic KNOWLEDGE 1건 -> Blog1/Shorts3/Threads5 = 9개 MEDIA draft
생성 fixture(``E2EFixtureMixin``, ``TEST_KNOWLEDGE``)와 헬퍼
(``_minimal_record``, ``_write_temp_knowledge_file``)를 그대로 재수출한다
(re-export) - 이 파일은 새 코드를 추가하지 않고, 어디서 리허설
fixture를 찾을 수 있는지 하나의 위치로 안내하는 역할만 한다.

사용 예::

    from tests.fixtures.rehearsal_fixture import E2EFixtureMixin, TEST_KNOWLEDGE

실제 data/ 운영 디렉터리는 이 fixture 어디에서도 참조하지 않는다 - 전부
tempfile.TemporaryDirectory() 안에서만 동작한다(``E2EFixtureMixin.setUp()``
참고).
"""

from __future__ import annotations

from tests.test_full_e2e_operating_readiness import (
    TEST_KNOWLEDGE,
    E2EFixtureMixin,
    _minimal_record as minimal_record,
    _write_temp_knowledge_file as write_temp_knowledge_file,
)

__all__ = [
    "TEST_KNOWLEDGE",
    "E2EFixtureMixin",
    "minimal_record",
    "write_temp_knowledge_file",
]
