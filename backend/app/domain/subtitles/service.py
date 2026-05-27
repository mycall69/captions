"""T058: 자막 서비스 레이어.

SubtitleRepository Protocol을 주입받아 트랙 CRUD, 큐 페이징,
이중 자막 합성 기능을 제공한다.

SubtitleRepository 구체 구현은 Phase 3e (T068)에서 인프라 계층에 추가된다.
"""

from __future__ import annotations

from typing import Literal, Protocol

from app.core.exceptions import JobNotReadyError
from app.domain.subtitles.dual_generator import generate_dual_srt, generate_dual_vtt
from app.domain.subtitles.models import SubtitleCue, SubtitleFormat, SubtitleKind, SubtitleTrack


class SubtitleRepository(Protocol):
    """자막 저장소 추상 인터페이스.

    Phase 3e (T068)에서 SQLAlchemy 구체 구현이 제공된다.
    테스트에서는 fake 구현을 주입한다.
    """

    async def save_track(self, track: SubtitleTrack) -> SubtitleTrack:
        """트랙을 저장하고 저장된 트랙을 반환한다."""
        ...

    async def get_track(self, job_id: str, kind: SubtitleKind) -> SubtitleTrack | None:
        """job_id와 kind로 트랙을 조회한다. 없으면 None 반환."""
        ...

    async def list_cues(
        self,
        track_id: str,
        *,
        offset: int,
        limit: int,
    ) -> tuple[list[SubtitleCue], int]:
        """트랙의 큐 목록을 페이징하여 (큐 목록, 전체 수) 튜플로 반환한다."""
        ...

    async def load_all_cues(self, track_id: str) -> list[SubtitleCue]:
        """트랙의 전체 큐 목록을 반환한다 (페이징 없음)."""
        ...


class SubtitlesService:
    """자막 도메인 서비스.

    트랙 저장·조회, 큐 페이징, 이중 자막 합성 기능을 제공한다.
    """

    def __init__(self, repo: SubtitleRepository) -> None:
        self._repo = repo

    async def save_track(self, track: SubtitleTrack) -> SubtitleTrack:
        """자막 트랙을 저장하고 저장된 트랙을 반환한다."""
        return await self._repo.save_track(track)

    async def list_cues(
        self,
        job_id: str,
        kind: SubtitleKind,
        *,
        offset: int,
        limit: int,
    ) -> tuple[list[SubtitleCue], int]:
        """자막 트랙의 큐 목록을 페이징하여 반환한다.

        Args:
            job_id: VideoJob의 26자 ULID.
            kind: 'source' 또는 'translated'.
            offset: 건너뛸 큐 수 (0-based).
            limit: 반환할 최대 큐 수.

        Returns:
            (큐 목록, 전체 큐 수) 튜플.

        Raises:
            JobNotReadyError: 해당 kind의 트랙이 아직 준비되지 않은 경우 (작업 처리 중).
        """
        track = await self._repo.get_track(job_id, kind)
        if track is None:
            raise JobNotReadyError(
                f"자막이 아직 준비되지 않았습니다 (처리 중): job_id={job_id!r}, kind={kind!r}"
            )
        return await self._repo.list_cues(track.id, offset=offset, limit=limit)

    async def build_dual_subtitle(
        self,
        job_id: str,
        *,
        format: SubtitleFormat,
        order: Literal["source-first", "target-first"],
    ) -> str:
        """원문·번역 트랙을 조회하여 이중 자막 문자열을 생성한다.

        Args:
            job_id: VideoJob의 26자 ULID.
            format: 출력 형식 ('srt' 또는 'vtt').
            order: 큐 내 줄 순서 ('source-first' 또는 'target-first').

        Returns:
            이중 자막 SRT 또는 VTT 문자열.

        Raises:
            JobNotReadyError: source 또는 translated 트랙이 아직 준비되지 않은 경우 (작업 처리 중).
        """
        source_track = await self._repo.get_track(job_id, "source")
        translated_track = await self._repo.get_track(job_id, "translated")
        if source_track is None or translated_track is None:
            raise JobNotReadyError(
                f"자막이 아직 준비되지 않았습니다 (처리 중): job_id={job_id!r}"
            )

        src_cues = await self._repo.load_all_cues(source_track.id)
        tgt_cues = await self._repo.load_all_cues(translated_track.id)

        if format == "srt":
            return generate_dual_srt(src_cues, tgt_cues, order=order)
        else:
            return generate_dual_vtt(src_cues, tgt_cues, order=order)
