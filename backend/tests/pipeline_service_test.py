from types import SimpleNamespace

from backend.services.pipeline_service import PipelineService


class _FakeQuery:
    def __init__(self, result):
        self._result = result

    def filter(self, *args, **kwargs):
        return self

    def order_by(self, *args, **kwargs):
        return self

    def first(self):
        return self._result


class _FakeDb:
    def __init__(self, results):
        self._results = list(results)

    def query(self, *_args, **_kwargs):
        return _FakeQuery(self._results.pop(0))


def test_get_initial_stage_for_pipeline_prefers_marked_first_stage():
    marked_stage = SimpleNamespace(id=10)
    db = _FakeDb([marked_stage])

    assert PipelineService.get_initial_stage_for_pipeline(3, db) is marked_stage


def test_get_initial_stage_for_pipeline_falls_back_to_operational_stage():
    operational_stage = SimpleNamespace(id=30)
    db = _FakeDb([None, operational_stage])

    assert PipelineService.get_initial_stage_for_pipeline(3, db) is operational_stage
