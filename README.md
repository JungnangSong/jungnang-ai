# 중랑AI 챗봇 시제품

중랑구청 공개 문서(`docs/`)에서 관련 부분을 찾아, 그 내용만 근거로 답하는 챗봇입니다.
문서에 없으면 "자료에서 확인되지 않습니다"라고 답하고, 답변 끝에 참고한 문서 이름·형식·위치를 보여 줍니다.

## 처음 실행하는 분을 위한 순서

### 1. 프로그램 설치 (처음 한 번)
1. **Node.js** (https://nodejs.org 의 LTS 버전) 설치
2. **Python 3** (https://python.org) 설치 — 설치 화면에서 `Add python.exe to PATH`를 꼭 체크

### 2. 터미널 열기
`jungnang-ai` 폴더를 탐색기에서 열고, 주소창에 `powershell` 을 입력해 Enter. (또는 VS Code에서 폴더를 열고 터미널 열기)

### 3. 필요한 부품 설치 (처음 한 번)
```
pip install -r extract/requirements.txt
npm install
```

### 4. Claude API 키 넣기
1. https://console.anthropic.com 에서 API 키 발급
2. 폴더의 `.env` 파일을 메모장으로 열어 첫 줄을 이렇게 바꾸고 저장
   ```
   ANTHROPIC_API_KEY=sk-ant-여기에-발급받은-키
   ```
   `.env` 는 외부에 공유하지 마세요(브라우저 화면에는 키가 노출되지 않고, 서버만 읽습니다).

### 5. 문서에서 글자 뽑기 (docs 폴더의 문서를 바꿨을 때도 다시 실행)
```
python extract/extract.py --no-ocr
```
- 파일별 글자 수와 앞부분 미리보기가 `data/report.md` 에 저장됩니다. 추출이 안 되거나 깨진 파일은 맨 아래 "추출 안 됨 / 깨짐" 항목에 나옵니다.
- 이 폴더의 문서는 모두 글자가 들어 있어 OCR이 필요 없습니다. 스캔본 PDF를 추가했다면 `--no-ocr` 없이 실행하세요(시간이 오래 걸립니다).
- 결과는 `data/chunks.json` 에 저장됩니다(문서 이름·형식·쪽/문단 위치 포함).

### 6. 챗봇 켜기
```
npm start
```
`중랑AI 실행 중` 이 보이면 브라우저에서 **http://localhost:3000** 접속. 끄려면 터미널에서 `Ctrl + C`.

### 휴대폰으로 보기
같은 와이파이에 연결된 휴대폰에서 `http://<내 PC의 IP>:3000` 으로 접속합니다. (PC 방화벽 허용 필요)

## 문제 해결
| 증상 | 해결 |
|---|---|
| `data/chunks.json 이 없습니다` | 5단계를 먼저 실행 |
| `API 키가 설정되지 않았습니다` | `.env` 의 키를 확인하고 서버를 다시 시작 |
| "답변을 만드는 중 문제가 생겼습니다" | API 키·결제 상태·인터넷 확인, 터미널의 오류 메시지 확인 |
| 포트 사용 중 | `.env` 의 `PORT=3000` 을 `3001` 등으로 변경 |

## 구조
- `extract/extract.py` 문서 추출(hwpx·구형 hwp 형식·PDF) · `data/report.md` 점검 보고서
- `server/` Node 서버(검색 `search.js`, API `server.js`) · `public/` 채팅 화면
- 같은 이름/비슷한 이름의 hwpx·PDF가 있으면 글자가 더 깨끗한 쪽만 사용합니다. 동별 책자의 완전히 똑같은 공통 문단도 검색 시 하나만 남깁니다.
