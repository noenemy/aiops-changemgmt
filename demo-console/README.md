# Demo Console

부스 시연 및 영상 녹화용 Next.js 웹 콘솔. 시나리오 설명, 활성 경로가 하이라이트되는 아키텍처 다이어그램, 터미널, Slack 리포트 미리보기를 한 화면에 묶어 보여줍니다.

![layout](../docs/assets/demo-console-layout.png)
<!-- 스크린샷 캡처는 녹화 전 최신화 필요 — docs/assets/ 폴더가 없으면 생략해도 무방 -->

## 기능 요약

- 6개 시나리오 탭 (`L1`, `L2`, `H1`~`H4`)
- **시나리오 설명 패널** — 제목, 파일, 문제, 예상 결과, KB 매칭 예고
- **아키텍처 다이어그램** — 현재 실행 중 노드가 주황색으로 펄스, 거쳐간 노드는 녹색, 예정 노드는 회색 점선
- **터미널** — 두 모드
  - **연출 (scripted)** · 기본값. 미리 정의된 출력을 타이핑 애니메이션으로 재생. 네트워크 / 크레덴셜 불필요.
  - **실제 (live)** · `./demo.sh run <id>` 를 실제로 실행하고 stdout을 SSE로 스트리밍.
- **Slack 리포트 미리보기** — 실행 완료 시 우측에 자동 표시 (시나리오별 기대 결과)

---

## 빠른 시작

### 사전 요구사항

- **Node.js 18+** (개발 환경에서 검증한 버전: Node 23)
- **npm** (또는 pnpm/yarn로 교체 가능)
- 실제(live) 모드를 쓸 경우에만 추가로:
  - `gh` CLI 로그인 (`gh auth status`)
  - 저장소 루트의 `./demo.sh` 실행 권한
  - AWS 프로파일 (`demo.sh` 내부에서 사용하지 않지만, 병행 Makefile 타겟을 쓸 경우)

### 설치 & 실행

```bash
cd demo-console
npm install
npm run dev      # http://localhost:3001
```

> Next.js dev 서버는 포트 **3001**을 사용합니다. 이미 쓰고 있다면 `package.json`의 `dev` 스크립트에서 `-p` 뒤 포트를 변경하세요.

### 프로덕션 빌드 (선택)

```bash
npm run build
npm run start    # http://localhost:3001
```

녹화 중 HMR로 인한 깜빡임을 피하고 싶으면 프로덕션 모드로 띄우는 걸 권장합니다.

---

## 화면 구성

```
┌──────────────────────────────────────────────────────────────────┐
│  [헤더] AIOps ChangeManagement — Demo Console                     │
├──────────────────────────────────────────────────────────────────┤
│  [시나리오 탭]  L1  L2  H1  H2  H3  H4                            │
│                                                                  │
│  ┌── 시나리오 패널 ──┐   ┌── 아키텍처 다이어그램 ──────────┐     │
│  │ 제목 / 파일 / 문제 │   │                                    │     │
│  │ 예상 Risk Score    │   │  [활성 경로 하이라이트]            │     │
│  └────────────────────┘   └────────────────────────────────┘     │
│                                                                  │
│  [▶ 실행]  [초기화]                            모드: 연출 | 실제 │
│                                                                  │
│  ┌── 터미널 ─────────────────────┐  ┌── Slack 미리보기 ──┐      │
│  │ $ ./demo.sh run h4             │  │ 🔴 PR #16         │      │
│  │ ✓ PR #16 생성                  │  │ Risk 92/100       │      │
│  │ ⋯ Runtime 분석 중...           │  │ REJECT            │      │
│  │ 🔴 Risk Score: 92/100          │  │ INC-0042 매칭     │      │
│  └────────────────────────────────┘  └────────────────────┘      │
└──────────────────────────────────────────────────────────────────┘
```

### 색상 / 애니메이션 규칙

- 🟠 주황 펄스 + 커지는 스케일 — **현재 실행 중** 노드
- 🟢 녹색 실선 — **완료** 노드
- ⚪ 회색 점선 — **예정** 노드
- 주황 점선 흐름 — 진입 중 엣지
- 녹색 실선 — 지나간 엣지

---

## 시나리오 편집

`src/data/scenarios.ts` 한 파일만 편집하면 전부 반영됩니다. 각 시나리오 객체 필드:

| 필드 | 설명 |
|---|---|
| `id` | 탭에서 표시되는 고유 ID (`l1`, `h4` 등) |
| `label`, `title`, `severity`, `expectedVerdict`, `branch`, `changedFile`, `problem` | 설명 패널에 표시 |
| `expectedKbMatch` | 예상 KB 장애 번호 (`INC-0042` 등, 선택) |
| `terminal` | 연출 모드에서 재생될 라인들 (`prompt` / `stdout` / `stderr` / `info` / `success` / `warn` / `wait`) |
| `liveCommand` | 실제 모드에서 실행할 명령 (allowlist 적용 — `./demo.sh`, `make`, `python3` 만 허용) |
| `highlightPath` | 아키텍처 그림에서 이 시나리오가 거쳐가는 노드 순서 |
| `slackPreview` | 완료 후 보여줄 Slack Block Kit 모사본 (risk_score, verdict, issues_text, incident_match, developer_pattern 등) |

편집 후 별도 빌드 불필요 — dev 서버가 HMR로 즉시 반영합니다.

### 아키텍처 다이어그램 수정

`src/components/ArchitectureDiagram.tsx` 상단의 `DIAGRAM` 상수(Mermaid 플로차트 텍스트) + 아래의 `NODE_IDS` / `EDGES` 배열을 일관되게 편집하면 됩니다. 새 노드를 추가했으면 `scenarios.ts`의 `HighlightedNode` 타입에도 추가.

---

## 안전 장치

- `/api/run`은 `scenarios.ts`에 정의된 `liveCommand`만 허용. 쿼리스트링으로 임의 셸 주입 불가
- 허용된 명령 바이너리 화이트리스트: `./demo.sh`, `make`, `python3`
- 클라이언트 연결이 끊기면 자식 프로세스에 SIGTERM 자동 전파
- 출력은 SSE로 1줄씩 스트리밍 — 버퍼링으로 녹화 중 멈춰보이지 않음

---

## 녹화자용 치트시트

### 녹화 직전 (0~1분)

1. **환경 준비**
   ```bash
   cd demo-console
   npm run build && npm run start   # HMR 깜빡임 방지 — 프로덕션 모드 권장
   ```
2. **창 배치**
   - 메인: 브라우저 풀스크린, 1920×1080 기준 줌 100% (혹은 125%로 글자 크게)
   - 보조(선택): GitHub PR 페이지, Slack 채널 탭
3. **브라우저 설정**
   - DevTools 닫기
   - 확장 툴바 숨기기 (시크릿 창 권장)
   - 스크롤바 감추기가 필요하면 OS 설정 또는 풀스크린 모드
4. **시나리오 사전 리셋** (실제 모드를 쓸 경우)
   ```bash
   # 저장소 루트에서
   ./demo.sh reset-all
   make dedup-clear                 # 선택: 이전 실행의 dedup 흔적 제거
   make pr-clean PR=<num>           # 선택: AI 코멘트 정리
   ```

### 녹화 흐름 제안

| 구간 | 시나리오 | 모드 | 멘트 포인트 |
|---|---|---|---|
| 오프닝 | L1 | 연출 | "평범한 리소스 변경은 자동 승인" |
| 본편 1 | H4 (Race Condition) | **실제** | 실행 중 다이어그램 하이라이트 이동 강조, Slack 결과 Zoom |
| 본편 2 | H1 (Secret) | 연출 | KB 매칭으로 INC-0045 과거 장애 발견 강조 |
| 보너스 | H3 (N+1) | 연출 | 성능 이슈 탐지 각도 |
| 마무리 | L2 | 연출 | "좋은 변경은 빠르게 통과" 대조 |

### 모드 선택 가이드

- **연출 모드**: 오프닝/아웃트로, 시간 맞춰야 하는 컷, 백업용. 항상 일정한 타이밍.
- **실제 모드**: 진짜 AI가 돈다는 걸 보여주고 싶은 단 한 컷. 녹화 당일 AWS 장애 가능성을 대비해 같은 시나리오의 연출 버전도 리허설.

### 트러블슈팅

| 증상 | 원인 | 대응 |
|---|---|---|
| 브라우저에서 페이지가 안 뜸 | 포트 3001 충돌 | `lsof -i :3001`로 기존 프로세스 종료 후 재실행 |
| 실행 모드에서 `연결 오류` | `/api/run` 실행 실패 — 대개 cwd가 잘못됨 | `demo-console/`에서 `npm run dev` 실행했는지 확인 (저장소 루트 기준 `./demo.sh` 접근 필요) |
| 실행 모드에서 `./demo.sh` 실패 | `gh` 미인증 또는 브랜치 없음 | 저장소 루트에서 `./demo.sh list`로 먼저 검증 |
| 다이어그램 하이라이트가 안 움직임 | 브라우저 캐시에 구버전 SVG | 하드 리로드 (Cmd+Shift+R) |
| 연출 모드 타이밍이 너무 빠름 | 시나리오 스크립트의 `wait.durationMs` 부족 | `src/data/scenarios.ts`에서 `wait` 블록의 시간 늘리기 |
| 실행 모드 진행 바가 실제 진행과 어긋남 | `liveCommand.expectedSeconds`가 부정확 | 시나리오 파일에서 실제 소요 시간에 맞춰 조정 |

### 단축 명령

```bash
# 저장소 루트
./demo.sh list                       # 시나리오 상태 한눈에 보기
./demo.sh reset-all                  # 모든 데모 PR 닫기
make dedup-clear                     # 중복 방지 테이블 비우기 (재녹화 전)
make memory-clear                    # AgentCore 메모리 비우기 (cold start 연출)
make pr-clean PR=9                   # 특정 PR의 AI 코멘트 제거
```

### 해상도 / 프레임

- 녹화: 1920×1080 @ 60fps 기준 — Mermaid SVG와 CSS 애니메이션 모두 rasterisation 품질 유지됨
- 줌 125% 사용 시 레이아웃은 1400px max-width로 감싸져 있어 안전

---

## 확장 아이디어 (미구현)

- [ ] CloudWatch Logs 실시간 tail 스트림을 터미널에 합쳐 실제 모드에서 Runtime 내부 도구 호출도 표시
- [ ] `memory-show` 결과를 별도 패널로 시각화 (세션 누적 데모용)
- [ ] 시나리오 동영상 프리뷰 자동 레코딩 (Playwright)
