"""T017: ORM 매핑 단위 테스트.

data-model.md에 정의된 7개 테이블의 컬럼, 인덱스, 제약 조건을 검증한다.
인메모리 SQLite DB에서 테이블 생성 및 FK CASCADE 동작도 확인한다.
"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine, inspect, text

# ── 기대 테이블·인덱스 목록 ────────────────────────────────────────────────────

EXPECTED_TABLES = {
    "video_job",
    "subtitle_track",
    "subtitle_cue",
    "translation_task",
    "render_task",
    "video_asset",
    "job_event",
}

# data-model.md에 명시된 인덱스 (테이블명, 인덱스명)
EXPECTED_INDEXES = [
    ("video_job", "ix_video_job_youtube_video_id"),
    ("video_job", "ix_video_job_status_created_at"),
    ("video_job", "ix_video_job_created_at"),
    ("subtitle_track", "ix_subtitle_track_job_id_kind"),
    ("subtitle_cue", "ix_subtitle_cue_track_start_ms"),
    ("video_asset", "ix_video_asset_job_id_kind"),
    ("job_event", "ix_job_event_job_id"),
    ("job_event", "ix_job_event_created_at"),
]

# uq_subtitle_cue_track_sequence는 UniqueConstraint로 등록됨
EXPECTED_UNIQUE_CONSTRAINT = "uq_subtitle_cue_track_sequence"


class TestOrmTablePresence:
    """Base.metadata에 7개 테이블이 모두 등록되어야 한다."""

    def test_all_tables_registered(self) -> None:
        """7개 테이블 이름이 Base.metadata.tables에 있어야 한다."""
        from app.infrastructure.db.orm import Base

        actual = set(Base.metadata.tables.keys())
        assert actual == EXPECTED_TABLES, f"누락 테이블: {EXPECTED_TABLES - actual}"

    def test_table_names_sorted(self) -> None:
        """테이블 이름을 정렬하면 예상 목록과 일치해야 한다."""
        from app.infrastructure.db.orm import Base

        assert sorted(Base.metadata.tables.keys()) == sorted(EXPECTED_TABLES)


class TestVideoJobColumns:
    """video_job 테이블 컬럼 검증."""

    def test_required_columns_exist(self) -> None:
        """video_job 테이블에 필수 컬럼이 모두 있어야 한다."""
        from app.infrastructure.db.orm import Base

        table = Base.metadata.tables["video_job"]
        expected_cols = {
            "id", "source_url", "youtube_video_id", "source_language",
            "target_language", "status", "error_stage", "error_message",
            "error_code", "video_title", "video_channel", "video_duration_sec",
            "subtitle_source", "created_at", "updated_at", "completed_at",
        }
        actual_cols = set(table.c.keys())
        assert expected_cols == actual_cols

    def test_id_is_string_primary_key(self) -> None:
        """id 컬럼은 String 타입의 PK여야 한다."""
        from sqlalchemy import String

        from app.infrastructure.db.orm import Base

        table = Base.metadata.tables["video_job"]
        assert table.c["id"].primary_key
        assert isinstance(table.c["id"].type, String)


class TestSubtitleTrackColumns:
    """subtitle_track 테이블 컬럼 검증."""

    def test_required_columns_exist(self) -> None:
        """subtitle_track 테이블에 필수 컬럼이 모두 있어야 한다."""
        from app.infrastructure.db.orm import Base

        table = Base.metadata.tables["subtitle_track"]
        expected_cols = {
            "id", "job_id", "kind", "language", "origin",
            "source_format", "file_path", "cue_count", "created_at",
        }
        actual_cols = set(table.c.keys())
        assert expected_cols == actual_cols


class TestSubtitleCueColumns:
    """subtitle_cue 테이블 컬럼 및 제약 조건 검증."""

    def test_required_columns_exist(self) -> None:
        """subtitle_cue 테이블에 필수 컬럼이 모두 있어야 한다."""
        from app.infrastructure.db.orm import Base

        table = Base.metadata.tables["subtitle_cue"]
        expected_cols = {"id", "track_id", "sequence", "start_ms", "end_ms", "text"}
        actual_cols = set(table.c.keys())
        assert expected_cols == actual_cols

    def test_id_is_integer_autoincrement(self) -> None:
        """id 컬럼은 Integer 타입 AUTOINCREMENT PK여야 한다."""
        from sqlalchemy import Integer

        from app.infrastructure.db.orm import Base

        table = Base.metadata.tables["subtitle_cue"]
        id_col = table.c["id"]
        assert id_col.primary_key
        assert isinstance(id_col.type, Integer)
        assert id_col.autoincrement is True or id_col.autoincrement == "auto"

    def test_check_constraint_exists(self) -> None:
        """end_ms > start_ms CHECK 제약이 존재해야 한다."""
        from sqlalchemy import CheckConstraint

        from app.infrastructure.db.orm import Base

        table = Base.metadata.tables["subtitle_cue"]
        check_names = [
            c.name for c in table.constraints if isinstance(c, CheckConstraint)
        ]
        assert "ck_subtitle_cue_end_after_start" in check_names

    def test_unique_constraint_exists(self) -> None:
        """uq_subtitle_cue_track_sequence UNIQUE 제약이 존재해야 한다."""
        from sqlalchemy import UniqueConstraint

        from app.infrastructure.db.orm import Base

        table = Base.metadata.tables["subtitle_cue"]
        uq_names = [
            c.name for c in table.constraints if isinstance(c, UniqueConstraint)
        ]
        assert EXPECTED_UNIQUE_CONSTRAINT in uq_names


class TestIndexes:
    """data-model.md에 명시된 인덱스 존재 여부 검증."""

    @pytest.mark.parametrize("table_name,index_name", EXPECTED_INDEXES)
    def test_index_exists(self, table_name: str, index_name: str) -> None:
        """각 인덱스가 해당 테이블에 정의되어 있어야 한다."""
        from app.infrastructure.db.orm import Base

        table = Base.metadata.tables[table_name]
        index_names = {idx.name for idx in table.indexes}
        assert index_name in index_names, (
            f"{table_name}.{index_name} 인덱스가 없음. "
            f"실제 인덱스: {index_names}"
        )


class TestCreateAllInMemory:
    """인메모리 SQLite에서 create_all / FK cascade 동작 검증."""

    @pytest.fixture
    def sync_engine(self):  # type: ignore[no-untyped-def]
        """테스트용 인메모리 SQLite 동기 엔진."""
        engine = create_engine(
            "sqlite:///:memory:",
            connect_args={"check_same_thread": False},
        )
        # foreign_keys 강제 활성화
        with engine.connect() as conn:
            conn.execute(text("PRAGMA foreign_keys=ON"))
            conn.commit()
        return engine

    def test_create_all_succeeds(self, sync_engine) -> None:  # type: ignore[no-untyped-def]
        """Base.metadata.create_all()이 오류 없이 완료되어야 한다."""
        from app.infrastructure.db.orm import Base

        Base.metadata.create_all(sync_engine)

        inspector = inspect(sync_engine)
        actual_tables = set(inspector.get_table_names())
        assert EXPECTED_TABLES.issubset(actual_tables)

    def test_insert_video_job(self, sync_engine) -> None:  # type: ignore[no-untyped-def]
        """VideoJob 행을 삽입하고 조회할 수 있어야 한다."""
        from sqlalchemy.orm import Session

        from app.infrastructure.db.orm import Base, VideoJob

        Base.metadata.create_all(sync_engine)

        with Session(sync_engine) as session:
            job = VideoJob(
                id="01JTEST00000000001",
                source_url="https://www.youtube.com/watch?v=dQw4w9WgXcY",
                youtube_video_id="dQw4w9WgXcY",
                status="pending",
            )
            session.add(job)
            session.commit()

            fetched = session.get(VideoJob, "01JTEST00000000001")
            assert fetched is not None
            assert fetched.status == "pending"

    def test_fk_cascade_delete(self, sync_engine) -> None:  # type: ignore[no-untyped-def]
        """VideoJob 삭제 시 SubtitleTrack / SubtitleCue가 CASCADE 삭제되어야 한다."""
        from sqlalchemy.orm import Session

        from app.infrastructure.db.orm import Base, SubtitleCue, SubtitleTrack, VideoJob

        Base.metadata.create_all(sync_engine)

        # FK를 반드시 켜야 cascade 동작
        with sync_engine.connect() as raw_conn:
            raw_conn.execute(text("PRAGMA foreign_keys=ON"))
            raw_conn.commit()

        with Session(sync_engine) as session:
            job = VideoJob(
                id="01JTEST00000000002",
                source_url="https://www.youtube.com/watch?v=dQw4w9WgXcY",
                youtube_video_id="dQw4w9WgXcY",
                status="pending",
            )
            track = SubtitleTrack(
                id="01JTRACK0000000001",
                job_id="01JTEST00000000002",
                kind="source",
                language="ja",
                origin="manual",
            )
            session.add_all([job, track])
            session.flush()

            cue = SubtitleCue(
                track_id="01JTRACK0000000001",
                sequence=1,
                start_ms=0,
                end_ms=1000,
                text="テスト",
            )
            session.add(cue)
            session.commit()

            # VideoJob 삭제
            session.delete(job)
            session.commit()

            # SubtitleTrack / SubtitleCue도 삭제되어 있어야 함
            remaining_tracks = session.query(SubtitleTrack).filter_by(
                job_id="01JTEST00000000002"
            ).all()
            remaining_cues = session.query(SubtitleCue).filter_by(
                track_id="01JTRACK0000000001"
            ).all()

        assert remaining_tracks == []
        assert remaining_cues == []

    def test_check_constraint_end_ms(self, sync_engine) -> None:  # type: ignore[no-untyped-def]
        """end_ms <= start_ms인 SubtitleCue 삽입 시 오류가 발생해야 한다."""
        from sqlalchemy.exc import IntegrityError
        from sqlalchemy.orm import Session

        from app.infrastructure.db.orm import Base, SubtitleCue, SubtitleTrack, VideoJob

        Base.metadata.create_all(sync_engine)

        with sync_engine.connect() as raw_conn:
            raw_conn.execute(text("PRAGMA foreign_keys=ON"))
            raw_conn.commit()

        with Session(sync_engine) as session:
            job = VideoJob(
                id="01JTEST00000000003",
                source_url="https://www.youtube.com/watch?v=dQw4w9WgXcY",
                youtube_video_id="dQw4w9WgXcY",
                status="pending",
            )
            track = SubtitleTrack(
                id="01JTRACK0000000002",
                job_id="01JTEST00000000003",
                kind="source",
                language="ja",
                origin="manual",
            )
            session.add_all([job, track])
            session.flush()

            # end_ms == start_ms → CHECK 제약 위반
            bad_cue = SubtitleCue(
                track_id="01JTRACK0000000002",
                sequence=1,
                start_ms=1000,
                end_ms=500,  # 잘못된 값
                text="バグ",
            )
            session.add(bad_cue)
            with pytest.raises(IntegrityError):
                session.commit()
