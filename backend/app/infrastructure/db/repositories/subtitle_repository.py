"""T068: SQLAlchemy 기반 SubtitleRepository 구현.

SubtitleRepository Protocol(app/domain/subtitles/service.py)의 모든 메서드를 구현한다.
트랙 저장 시 자식 큐(SubtitleCue)를 함께 일괄 삽입한다.
"""

from __future__ import annotations

from datetime import UTC

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.subtitles.models import SubtitleCue, SubtitleKind, SubtitleTrack
from app.infrastructure.db.orm import SubtitleCue as OrmSubtitleCue
from app.infrastructure.db.orm import SubtitleTrack as OrmSubtitleTrack


def _track_to_domain(orm: OrmSubtitleTrack, cues: list[SubtitleCue] | None = None) -> SubtitleTrack:
    """ORM SubtitleTrack → Pydantic SubtitleTrack 도메인 모델 변환.

    cues 인자를 전달하면 해당 목록을 포함하고, 생략하면 빈 목록으로 설정한다.
    """
    created_at = orm.created_at
    if created_at is not None and created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=UTC)

    return SubtitleTrack(
        id=orm.id,
        job_id=orm.job_id,
        kind=orm.kind,
        language=orm.language,
        origin=orm.origin,
        source_format=orm.source_format,
        file_path=orm.file_path,
        cue_count=orm.cue_count,
        cues=cues or [],
    )


def _cue_to_domain(orm: OrmSubtitleCue) -> SubtitleCue:
    """ORM SubtitleCue → Pydantic SubtitleCue 도메인 모델 변환."""
    return SubtitleCue(
        sequence=orm.sequence,
        start_ms=orm.start_ms,
        end_ms=orm.end_ms,
        text=orm.text,
    )


class SqlSubtitleRepository:
    """SQLAlchemy AsyncSession 기반 SubtitleRepository 구현체.

    save_track: 트랙 + 모든 자식 큐를 함께 저장한다.
    get_track: 트랙 메타데이터만 반환하고 cues=[]로 설정한다.
    list_cues: offset/limit 페이지네이션을 적용하여 (큐 목록, 전체 수)를 반환한다.
    load_all_cues: 페이지네이션 없이 sequence 순 전체 큐를 반환한다.
    """

    def __init__(self, session: AsyncSession) -> None:
        """AsyncSession을 주입받아 저장한다."""
        self._session = session

    async def save_track(self, track: SubtitleTrack) -> SubtitleTrack:
        """트랙과 모든 자식 큐를 저장하고 저장된 트랙을 반환한다.

        track.cues가 비어있어도 트랙 메타데이터는 정상 저장된다.
        cue_count는 track.cues 길이로 갱신된다.
        """
        orm_track = OrmSubtitleTrack(
            id=track.id,
            job_id=track.job_id,
            kind=track.kind,
            language=track.language,
            origin=track.origin,
            source_format=track.source_format,
            file_path=track.file_path,
            cue_count=len(track.cues),
        )
        self._session.add(orm_track)

        # 큐 일괄 삽입
        for cue in track.cues:
            orm_cue = OrmSubtitleCue(
                track_id=track.id,
                sequence=cue.sequence,
                start_ms=cue.start_ms,
                end_ms=cue.end_ms,
                text=cue.text,
            )
            self._session.add(orm_cue)

        await self._session.flush()
        await self._session.refresh(orm_track)

        return track.model_copy(update={"cue_count": len(track.cues)})

    async def get_track(self, job_id: str, kind: SubtitleKind) -> SubtitleTrack | None:
        """job_id와 kind로 트랙 메타데이터를 조회한다.

        cues는 빈 목록으로 설정된다. 큐 조회는 list_cues / load_all_cues를 사용한다.
        """
        stmt = (
            select(OrmSubtitleTrack)
            .where(
                OrmSubtitleTrack.job_id == job_id,
                OrmSubtitleTrack.kind == kind,
            )
            .limit(1)
        )
        result = await self._session.execute(stmt)
        orm = result.scalar_one_or_none()
        if orm is None:
            return None
        return _track_to_domain(orm, cues=[])

    async def list_cues(
        self,
        track_id: str,
        *,
        offset: int,
        limit: int,
    ) -> tuple[list[SubtitleCue], int]:
        """트랙의 큐 목록을 offset/limit 페이지네이션으로 반환한다.

        Returns:
            (큐 목록, 전체 큐 수) 튜플. 전체 수는 COUNT 쿼리로 정확히 반환한다.
        """
        # 전체 수 조회
        count_stmt = (
            select(func.count())
            .select_from(OrmSubtitleCue)
            .where(OrmSubtitleCue.track_id == track_id)
        )
        count_result = await self._session.execute(count_stmt)
        total = count_result.scalar_one()

        # 페이지 조회
        page_stmt = (
            select(OrmSubtitleCue)
            .where(OrmSubtitleCue.track_id == track_id)
            .order_by(OrmSubtitleCue.sequence.asc())
            .offset(offset)
            .limit(limit)
        )
        page_result = await self._session.execute(page_stmt)
        cues = [_cue_to_domain(row) for row in page_result.scalars()]

        return cues, total

    async def load_all_cues(self, track_id: str) -> list[SubtitleCue]:
        """트랙의 전체 큐 목록을 sequence 오름차순으로 반환한다 (페이지네이션 없음).

        이중 자막 합성(build_dual_subtitle) 등 전체 큐 접근이 필요한 경우에 사용한다.
        """
        stmt = (
            select(OrmSubtitleCue)
            .where(OrmSubtitleCue.track_id == track_id)
            .order_by(OrmSubtitleCue.sequence.asc())
        )
        result = await self._session.execute(stmt)
        return [_cue_to_domain(row) for row in result.scalars()]
