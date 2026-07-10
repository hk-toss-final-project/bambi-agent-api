"""정기 작업을 등록하고 Scheduler 프로세스를 실행하는 진입점."""


def build_scheduler() -> object:
    """설정된 수집·Wiki·생성 주기를 Scheduler 인스턴스에 등록한다."""
    raise NotImplementedError("Scheduler 구성 구현이 필요합니다.")


def main() -> None:
    """Scheduler 프로세스를 시작하고 종료 신호를 처리한다."""
    raise NotImplementedError("Scheduler 실행 진입점 구현이 필요합니다.")
