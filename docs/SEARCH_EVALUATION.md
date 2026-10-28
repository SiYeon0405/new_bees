# 실제 임베딩 검색 평가 (2026-10-28)

## 범위와 현재 결과

사용자가 합성 문서 7버전·질문 15개, 재시도 포함 최대 22회, 비용 상한 $0.01을 승인한 뒤 실제 OpenAI 임베딩을 실행했다. 기존 fake 임베딩의 Redis·Celery·Qdrant 통합 결과와 구분한다. 실제 사용자 문서나 개인정보는 전송하지 않았다.

## 분리된 검증 환경

`docker-compose.openai-validation.yml`은 `bees_openai_validation` 프로젝트, MySQL 개발 DB `bees_openai_eval`, Django 테스트 DB `bees_openai_eval_test`, 로컬 포트 `127.0.0.1:13308`/`18081`, 전용 `.validation/openai/{mysql,redis,qdrant,media}`를 사용한다. Redis와 Qdrant는 호스트 포트를 공개하지 않는다. 기존 fake 환경은 `bees_stage1_validation`, `bees_stage1_validation_dev`, `13307`/`18080`, `.validation/{mysql,redis,qdrant,media}`이며 변경하거나 비우지 않았다. 실제 컬렉션은 provider·model·dimension·revision을 포함한 `bees_openai_text-embedding-3-small_512_openai-eval-v1`이고 fake 컬렉션과 분리된다.

실제 설정: `text-embedding-3-small`, 512차원, `paragraph-char-v1`, 청크 최대 1200 **Python Unicode 문자**, 중복 160문자, 문서 최대 200000문자. 제공자 요청은 입력당 6000 UTF-8 바이트, 한 작업당 20000바이트, 배치 32개로 더 좁게 제한한다. 공식 API 상한은 입력당 8192 토큰, 요청 전체 300000 토큰, 최대 2048개 입력이다. 바이트 제한은 토큰 수를 정확히 계산하는 방식이 아니며 실제 제공자 토큰 오류는 영구 실패로 기록한다. SDK timeout 30초, SDK 내부 재시도 0회, 이 평가 환경의 작업 시도 최대 1회, 수동 재시도 비활성화. 잘못된 키/입력/잔액 부족은 영구 오류, 네트워크·timeout·일반 rate limit·서버 오류는 일시 오류로 분류한다. 반환 벡터의 개수·순서·차원·유한값과 Qdrant 컬렉션 차원을 검사한다. 기본 `AI_REAL_EVAL_ENABLED=false`로 웹과 워커의 색인을 막는다.

참고: [OpenAI Embeddings API](https://developers.openai.com/api/reference/python/resources/embeddings/methods/create), [text-embedding-3-small 모델과 가격](https://developers.openai.com/api/docs/models/text-embedding-3-small), [API 오류 코드](https://developers.openai.com/api/docs/guides/error-codes).

## 합성 평가셋과 정답 근거

전체 원문·질문은 [search_eval_fixture.json](search_eval_fixture.json)에 있다. 그룹 alpha 문서 5개, beta 비공개 문서 1개, 총 파일 버전 7개와 질문 15개다. `file-policy`만 1·2버전이 있으며 검색 정답은 최신 2버전이다. 아래 근거 문자열은 정답 버전 원문에 실제로 포함된다.

| 질문 | 그룹 | 정답 문서/버전 | 근거 구간 | 유형 |
|---|---|---|---|---|
| Q01 | alpha | auth-policy/1 | 이메일과 비밀번호 | 의미 변형 |
| Q02 | alpha | auth-policy/1 | 60분 | 의미 변형 |
| Q03 | alpha | auth-policy/1 | CSRF 토큰 | 한영 혼합 |
| Q04 | alpha | file-policy/2 | 현재 파일 크기 제한은 5MB | 버전 충돌 |
| Q05 | alpha | file-policy/2 | 현재 파일 크기 제한은 5MB | 버전 충돌 |
| Q06 | alpha | file-policy/2 | 빈 파일과 잘못된 UTF-8은 거절 | 의미 변형 |
| Q07 | alpha | api-contract/1 | 업로드 성공 응답은 201 | API 경로 |
| Q08 | alpha | api-contract/1 | 동일한 현재 버전 내용의 재요청은 409 | 오류 코드 |
| Q09 | alpha | api-contract/1 | 인증과 그룹 멤버십을 검사 | 한영 혼합 |
| Q10 | alpha | group-permission/1 | 탈퇴한 멤버는 즉시 접근할 수 없다 | 의미 변형 |
| Q11 | alpha | group-permission/1 | 24시간 뒤 만료 | 한영 혼합 |
| Q12 | alpha | version-policy/1 | 이전 READY 버전이 계속 검색 | 의미 변형 |
| Q13 | alpha | version-policy/1 | 검색 결과에서 즉시 제외 | 한영 혼합 |
| Q14 | alpha | 없음 | beta 문서에만 존재 | 권한상 답 없음 |
| Q15 | beta | beta-private/1 | 배포 승인 담당자는 민지다. 배포 창은 금요일 오후 4시 | 그룹 전용 |

Q14에서 결과가 반환되더라도 답이 있다고 간주하지 않는다. 접근 가능한 문서의 유사 청크가 나오는 것은 벡터 검색의 정상적인 동작일 수 있다.

## 평가 기준과 실행

Recall@5는 정답이 있는 14개 질문에서 상위 5개 청크 중 **정답 파일·버전과 근거 문자열이 모두 일치**하는 비율이다. 별도로 잘못된 버전 결과 수, 타 그룹 파일 결과 수, 질문별 응답 지연, 문서·질문 임베딩 토큰 및 추정 달러 비용을 기록한다. 정답 없는 Q14는 Recall 분모에서 제외한다. 지연에는 질문 임베딩, Qdrant 조회, MySQL 재검증이 포함되며 로컬 Docker 네트워크 조건에서 측정한다. 이 작은 동일 셋에 맞춘 변경 뒤 점수 상승은 독립 품질 검증으로 해석하지 않는다.

실행 전(무료):

```powershell
docker compose --env-file .env.validation -f docker-compose.openai-validation.yml -p bees_openai_validation config --quiet
docker compose --env-file .env.validation -f docker-compose.openai-validation.yml -p bees_openai_validation run --rm --no-deps web python manage.py evaluate_search
```

두 번째 명령은 이미지 빌드가 선행되어야 한다. 명시적 `--allow-paid-calls`가 없으면 평가셋 크기만 확인하고 전송하지 않는다. **승인 후에만** 아래 순서로 전용 서비스를 띄우고 migration을 적용한다. 평가 DB에 사용자·그룹·파일·작업이 하나라도 있으면 평가 명령은 중단하며 삭제하지 않는다.

```powershell
$env:AI_REAL_EVAL_ENABLED='true'
docker compose --env-file .env.validation -f docker-compose.openai-validation.yml -p bees_openai_validation up -d db redis qdrant
docker compose --env-file .env.validation -f docker-compose.openai-validation.yml -p bees_openai_validation run --rm web python manage.py migrate --noinput
docker compose --env-file .env.validation -f docker-compose.openai-validation.yml -p bees_openai_validation up -d web worker
docker compose --env-file .env.validation -f docker-compose.openai-validation.yml -p bees_openai_validation exec web python manage.py evaluate_search --allow-paid-calls
```

실제 호출은 합성 문서 7개 버전과 질문 15개만 전송했다. 웹·워커가 공유하는 Redis 장부에서 호출 전마다 원문이 평가셋의 부분 문자열인지 확인하고, 총 **22회·12000 UTF-8 바이트** 상한을 원자적으로 예약한다. SDK 재시도 0, 작업 시도 1, 수동 재시도 차단이다. 승인된 총비용 상한은 $0.01이다. 모델 단가 $0.02/백만 입력 토큰 기준 응답 사용량으로 계산한다. 결과 JSON은 `.validation/openai/media/search-evaluation.json`에 저장했다. 같은 장부에 이미 호출이 있으면 평가 명령은 다시 실행되지 않는다. 재실행에는 별도 승인과 새 격리 환경이 필요하다.

## 실제 검색 결과

전용 MySQL에 READY 작업 7개, 활성 파일 색인 6개가 생성됐다. 실제 Celery 워커의 각 작업 시도 횟수는 모두 1회다. Qdrant 전용 컬렉션은 512차원, point 7개로 확인했다. 아래 `1위`는 최상위 검색 문서이며 `근거 순위`는 정답 문서·버전과 근거 문자열을 포함한 청크의 상위 5개 내 순위다. 결과가 없는 Q14에서는 근거 순위가 없다.

| 질문 | 1위 문서/버전 | 근거 순위 | 지연 ms | 질문 토큰 |
|---|---|---:|---:|---:|
| Q01 | auth-policy/1 | 1 | 798.8 | 23 |
| Q02 | auth-policy/1 | 1 | 283.1 | 17 |
| Q03 | auth-policy/1 | 1 | 320.5 | 12 |
| Q04 | file-policy/2 | 1 | 395.9 | 17 |
| Q05 | file-policy/2 | 1 | 308.6 | 22 |
| Q06 | file-policy/2 | 1 | 252.6 | 14 |
| Q07 | api-contract/1 | 1 | 324.1 | 17 |
| Q08 | api-contract/1 | 1 | 237.1 | 19 |
| Q09 | api-contract/1 | 1 | 228.2 | 14 |
| Q10 | group-permission/1 | 1 | 236.0 | 23 |
| Q11 | auth-policy/1 | 2 (group-permission/1) | 236.7 | 8 |
| Q12 | version-policy/1 | 1 | 247.9 | 24 |
| Q13 | version-policy/1 | 1 | 223.7 | 16 |
| Q14 | group-permission/1 | 없음 | 228.4 | 28 |
| Q15 | beta-private/1 | 1 | 217.8 | 25 |

- **Recall@5: 14/14 = 100%**. 정답 없는 Q14는 분모에서 제외했다. 정답이 있는 14개 중 1위 근거 적중은 13개다.
- **잘못된 파일 버전 선택 0건**, **타 그룹 파일 노출 0건**. Q04·Q05는 최신 `file-policy/2`를 1위로 반환했고 이전 1버전은 결과에 없었다. Q14는 beta 비공개 문서를 반환하지 않았다.
- **실패·주의 사례:** Q11의 `invite code` 만료 질문에서 1위는 로그인 토큰 만료를 설명하는 `auth-policy/1`이었다. 정답 `group-permission/1`은 2위였다. 표현이 비슷한 만료 기간 때문에 1위 선택이 흔들린 사례다. Q14에는 답이 없지만 alpha 그룹의 유사 청크 5개가 반환됐다. 검색 결과 존재만으로 답 존재를 판단할 수 없다.
- **지연:** 15개 질문에서 최소 217.8ms, 중앙값 247.9ms, 평균 302.6ms, 최대 798.8ms, 선형 보간 p95 677.9ms. 첫 질문이 가장 느렸다. 로컬 Docker, 실제 외부 질문 임베딩, Qdrant 조회와 MySQL 권한 재검증을 포함한다. 색인 작업의 개별 지연은 측정하지 않았다.
- **사용량:** Redis 예약 장부 22회(문서 7·질문 15), 입력 합계 2946 UTF-8 바이트. API 응답 사용량 합계 1070토큰(문서 791·질문 279). `$0.02 / 1,000,000토큰` 기준 **계산 비용 $0.0000214**. 이는 승인 상한 $0.01보다 낮다. **실제 청구 확인값은 미확인**이며 OpenAI 청구 내역과 대조하지 않았다. 사용량 응답과 단가로 계산한 값은 실제 결제 내역이 아니다.
- fake 환경의 분리 MySQL 테스트 DB에서 인증·그룹·파일·웹·AI 회귀 및 추가 안전장치 테스트 **29건 통과**. 실제 OpenAI 모델에 대한 품질 측정은 위 15개 합성 질문에만 해당한다.

LLM 답변 단계의 기술적 출발점은 마련됐지만, Q11의 1위 오류와 Q14의 무답 질문에서 유사 결과가 나오는 점을 답변 단계에서 명시적으로 처리해야 한다. 소규모 합성 평가 결과를 실제 서비스 문서의 검색 품질로 일반화하지 않는다. 실제 청구 금액 확인과 실제 운영 문서의 독립 평가도 남아 있다.
