# Demo Console

Next.js 기반 데모 웹 콘솔. 영상 녹화 및 부스 시연용.

## 기능

- 6개 시나리오 탭 (`l1`, `l2`, `h1`~`h4`)
- 시나리오별 설명 + 아키텍처 다이어그램 (활성 경로 하이라이트)
- 터미널 뷰 (두 모드)
  - **연출 (scripted)** · 기본값. 미리 정의된 출력을 타이핑 애니메이션으로 재생. 네트워크 불필요.
  - **실제 (live)** · `./demo.sh run <id>` 를 실제로 실행하고 stdout을 SSE로 스트리밍. 녹화 환경에서 GitHub + AWS 크레덴셜이 준비되어 있어야 동작.
- 실행 완료 시 Slack 리포트 미리보기 자동 노출

## 실행

```bash
cd demo-console
npm install
npm run dev      # http://localhost:3001
```

`live` 모드를 쓰려면 `npm run dev`를 실행한 터미널의 cwd 기준 **상위 디렉터리**가 저장소 루트여야 합니다 (`demo-console/`에서 실행 시 자동으로 그렇게 잡힙니다). 또한:

- `gh` CLI 인증 완료 (`./demo.sh`가 내부에서 사용)
- AWS 프로파일 설정 (`make trigger` 경로 사용 시)

## 시나리오 수정

`src/data/scenarios.ts` 한 파일만 편집하면 전부 반영됩니다:

- `terminal`: 연출 모드에서 출력될 라인들 (`prompt` / `stdout` / `stderr` / `info` / `success` / `warn` / `wait`)
- `liveCommand`: 실제 모드에서 실행할 명령 (allowlist — `./demo.sh`, `make`, `python3` 만 허용)
- `highlightPath`: 아키텍처 그림에서 강조할 노드
- `slackPreview`: 완료 후 보여줄 Slack Block Kit 모사본

## 안전 장치

- `/api/run` 은 `scenarios.ts`에 정의된 `liveCommand`만 허용. 쿼리스트링으로 임의 셸 주입 불가
- 클라이언트 연결이 끊기면 자식 프로세스에 SIGTERM 자동 전파
- 출력은 SSE로 1줄씩 스트리밍 — 버퍼링으로 녹화 중 멈춰보이지 않음
