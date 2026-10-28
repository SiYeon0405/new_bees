# 개발 진행 기록 (2026-10-28)

## 현재 단계

0단계의 로컬 인증 경로와 1단계 중 그룹·멤버십 API를 구현했다. 파일 업로드·AI는 구현하지 않았다. MySQL 및 Docker 실기동은 이 컴퓨터에 Docker 명령이 없어 미검증이다.

## 확인한 원인과 기준

- `users.User`의 로그인 필드는 `email`, 표시 필드는 `nickname`이다. 중복 정의된 마지막 로그인 직렬화기가 없는 `username`을 읽어 정상 로그인 응답에서 실패했다.
- 설치 앱은 `users`, `groups`, `files`, `comments`, `notifications`다. 외부 URL은 관리자, 두 인증 경로 집합, 사용자 API뿐이다. `group_create`, `group_join`, `workspace`, `accounts`는 현재 설치되지 않았다.
- `groups.Group/GroupMember`와 `files.File/FileVersion`에 FK 연결이 있다. `group_create.Group/GroupMembership`과 `workspace.UploadedFile`은 별도 체계다. 실제 기존 DB의 데이터 건수는 확인하지 못했으므로 테이블 통합·삭제를 보류한다. 다음 단계 기준은 설치된 `groups`·`files` 체계를 권장한다. 기존 데이터가 있으면 ID 매핑·백업·검증이 먼저 필요하다.
- `files`에는 migration이 없었고 `notifications` 모델과 migration 상태에 차이가 있었다. 새 migration 두 개를 추가했다. `accounts.UserProfile` 모델은 기본 `auth.User`를 참조했으나 해당 앱은 미설치이며 기존 migration은 이미 커스텀 모델을 참조한다. 모델 코드를 migration 상태에 맞췄다.
- `backend/requirements.txt`는 루트 의존성의 일부만 반복했다. 루트를 단일 설치 목록으로 삼았다. 현재 설치 결과: Python 3.12.14, Django 4.2.30, DRF 3.17.2, SimpleJWT 5.5.1, PyMySQL 1.2.3. 로컬 기본 Python 3.14의 venv 생성은 실패해 별도 3.12 런타임으로 검증했다.

## 변경과 영향

- `backend/groups/selectors.py`, `services.py`, `serializers.py`, `views.py`, `urls.py`, `tests.py`, `backend/config/urls.py`: `/api/groups/` 생성·내 목록, `/api/groups/{id}/` 상세, `/api/groups/{id}/invites/` 소유자 초대, `/api/groups/join/` 본인 가입을 연결했다. 기존 `groups` 테이블·유일 제약을 사용하며 새 스키마 변경은 없다. 생성과 소유자 멤버십은 한 트랜잭션이다. 목록·상세·초대 경로는 멤버십 제한 조회를 사용한다. 초대 코드는 15바이트의 암호학적 난수로 만든 20자 URL-safe 문자열이며 24시간 만료다. 가입은 DB 유일 제약과 중첩 트랜잭션으로 중복 요청을 처리한다. 부가 알림 호출을 이 경로에 넣지 않아 알림 실패가 가입 결과를 뒤집지 않는다.
- API 계약: 그룹 생성 201, 목록·상세 200, 초대 생성 201, 신규 가입 201, 중복 가입 200(`joined: false`), 무효·만료 코드 및 다른 그룹 접근 404, 멤버의 초대 생성 403, 미인증 401. 요청의 `owner_id`, `user_id`, `role`은 사용하지 않는다. 초대 코드는 생성 응답에서만 반환한다.

- `backend/users/serializers.py`, `views.py`, `tests.py`: 로그인 응답의 `user.username`을 `user.nickname`으로 교체하고 가입·비밀번호 변경 시 Django 비밀번호 검증을 적용했다. 로그인 응답의 `refresh`, `access`, `user.id`, `user.email`은 유지한다. `user.username` 소비자는 `user.nickname`으로 바꿔야 한다. 가입 성공·중복 이메일·로그인 거부·토큰 갱신·내 정보·민감 필드 부재를 API로 검증했다.
- `backend/config/settings.py`, `.env.example`, `.gitignore`: 비밀키·DB 비밀번호를 환경변수로 분리했다. `.env`는 미추적이다. 기존 코드에 포함됐던 Django 키와 DB 비밀번호는 실제 배포에 사용했다면 교체가 필요하다. 값은 여기에 기록하지 않는다.
- `Dockerfile`, `docker-compose.yml`, `backend/requirements.txt`: 이미지의 `/app`에 backend를 복사하고 개발 전용 MySQL 볼륨·환경변수로 연결했다. 이전 `./db` 볼륨은 삭제하거나 마운트하지 않는다. Compose 설정은 로컬 Docker 부재로 파싱·기동 검증하지 못했다.
- `backend/files/migrations/0001_initial.py`, `backend/notifications/migrations/0002_alter_notification_user.py`: 새 DB의 migration 일관성 복구. 기존 DB 적용은 검증하지 않았다. 적용 전 별도 개발 DB와 백업에서 확인할 것.
- `backend/accounts/models.py`: 미설치 앱의 사용자 FK를 커스텀 모델로 맞춤. 기존 migration 정의와 일치한다.

## 실행 검증

- `manage.py check`: 통과.
- 분리된 SQLite 파일에 `migrate --noinput`: 설치 앱의 전체 migration 통과.
- `manage.py test users`: 3개 통과. 테스트 DB는 SQLite의 별도 임시 DB다.
- `makemigrations --check --dry-run`: 변경 없음.
- 그룹 구현 후 `manage.py check`, `makemigrations --check --dry-run`, `manage.py test users groups`: 통과, 6개 테스트. SQLite 임시 테스트 DB에서 그룹 생성·소유자 멤버십·격리 조회·초대·본인 가입·중복 가입·만료·잘못된 코드·권한 거부를 확인했다. SQLite 통과는 MySQL 잠금·동시성 검증이 아니다.
- MySQL migration, Docker Compose 구성·이미지·서버 기동: 미실행. 로컬에 Docker 명령이 없다. SQLite 통과가 MySQL 호환성을 증명하지 않는다.

## Docker 정적 점검과 미검증 범위

- 현재 Compose에는 고정 `container_name`이 없고 bind mount도 없다. 명명 볼륨 `bees_dev_data`는 Compose 프로젝트 이름 아래 분리된다. 기존 `./db` 경로는 마운트하지 않는다.
- 호스트 포트 `127.0.0.1:3307` 및 `8000`을 게시한다. 현재 TCP 리스너 조회에서는 점유가 보이지 않았지만 Docker 실행 시 충돌 여부는 다시 확인해야 한다. Compose 프로젝트 이름만 달라도 호스트 포트 충돌은 막지 못한다.
- Docker 명령이 없어 Compose 파싱, MySQL migration, MySQL 잠금·동시 가입, 이미지 빌드, 서버 HTTP 기동은 미검증이다. 현재 PC의 기존 MySQL DB 데이터 현황도 미확인이다. 이를 빈 DB로 가정하지 않는다.

## 다음 작업

1. Docker가 있는 개발 환경에서 `docker compose -p new_bees_stage1 config`로 구성·환경변수를 확인하고 `docker compose -p new_bees_stage1 ps`, 호스트 포트 3307/8000 점유, 프로젝트 볼륨 이름을 확인한다. 기존 DB·볼륨을 재사용하지 않고 새 개발 전용 볼륨에서 아래 migration과 테스트를 수행한다. 특히 MySQL에서 동시 가입 시 한 행만 생성되고 중복 응답이 500이 아닌지 별도 검증한다.
2. 별도 개발 DB에서 기존 그룹·파일 테이블별 데이터 건수와 FK 연결을 조사한다. 기존 데이터가 있으면 `group_create`·`workspace` → 권장 기준 모델의 매핑 계획을 세우고 데이터 손실 검증 후 이관한다.
3. 다음 기능 작업은 두 그룹 간 격리 테스트를 더 넓힌 뒤 `files.File/FileVersion` 업로드·다운로드를 같은 멤버십 조건에 연결하는 것이다. 현재 미연결 Git 조작 경로는 연결하지 않는다.

## 새 개발 환경 실행 명령

`cp .env.example .env` 후 `.env`의 개발 전용 값을 채운다. Docker Compose는 개발 서버이며 운영 설정이 아니다.

```sh
docker compose -p new_bees_stage1 config
docker compose -p new_bees_stage1 build
docker compose -p new_bees_stage1 up -d db
docker compose -p new_bees_stage1 run --rm web python manage.py migrate --noinput
docker compose -p new_bees_stage1 run --rm web python manage.py test users groups
docker compose -p new_bees_stage1 up web
```

로컬 SQLite 검증은 별도 Python 3.10~3.12 환경에서 루트 `requirements.txt` 설치 후 `DJANGO_SECRET_KEY`, `DJANGO_DB_ENGINE=sqlite`, `SQLITE_PATH`를 개발 전용 파일로 설정하고 `python backend/manage.py check`, `migrate`, `test users`를 실행한다. SQLite는 MySQL 대체 운영 DB가 아니다.

## Docker·MySQL 실검증 (2026-10-28)

- 시작 전 `docker ps -a`, `docker volume ls`, `docker compose ls`에서 기존 컨테이너·볼륨·프로젝트가 없음을 확인했다. 호스트 3306은 사용 중이고, 검증용 13307·18080은 비어 있었다.
- `docker-compose.validation.yml`과 무시되는 `.env.validation`을 사용했다. 프로젝트 `bees_stage1_validation`, 고유 컨테이너명, 호스트 포트 `127.0.0.1:13307`·`127.0.0.1:18080`, 저장 경로 `.validation/mysql`을 지정했다. 개발 DB `bees_stage1_validation_dev`와 테스트 DB `bees_stage1_validation_test`를 분리했다. 기존 `./db` 또는 다른 볼륨은 사용하지 않았다.
- Compose `config --quiet` 통과, 웹 이미지 빌드 성공, 별도 MySQL 컨테이너 healthy 확인. 최초 migration 시도는 DB 초기화 전 `--no-deps` 실행으로 연결이 거부됐다. healthcheck 대기 후 재실행하여 모든 migration이 적용됐다.
- MySQL에서 `python manage.py test users.tests groups.tests --noinput` 6건 통과. `test users groups`는 `/app`의 패키지 탐색으로 `app.users` 중복 import 오류가 나서 테스트 모듈을 명시했다. 테스트 DB는 Django 테스트 실행 중 별도 생성·정리됐다.
- 웹 서버를 `127.0.0.1:18080`에서 기동하고 `GET /api/groups/` 응답 `401 Unauthorized`와 JSON 인증 오류를 확인했다. 검증 컨테이너와 개발 DB 저장 경로는 유지 중이다. 기존 데이터 삭제, 볼륨 초기화, `down -v`는 수행하지 않았다.
- 남은 검증: 기존 실데이터의 그룹·파일 테이블 건수와 FK 매핑 조사, 기존 DB에 대한 migration 적용, 파일 업로드·Git 작업 경로 통합 검증. 기존 DB에는 이번 검증이 접근하지 않았다.

## 파일 업로드·버전 관리 구현 및 검증 (2026-10-28)

### 영향과 구현

- 현재 연결 대상은 Docker Compose `bees_stage1_validation`의 MySQL `bees_stage1_validation_dev`(호스트 127.0.0.1:13307)와 웹 127.0.0.1:18080이다. 테스트 DB 이름은 `bees_stage1_validation_test`다. 조사 시 검증 개발 DB의 Group/GroupMember/File/FileVersion은 모두 0건이었다. 이는 기존 실데이터 조사 결과가 아니다. 시작 전 인증·그룹 회귀 6건을 MySQL에서 재확인했다.
- `files.File/FileVersion`을 기준으로 `backend/files/models.py`, `selectors.py`, `services.py`, `serializers.py`, `views.py`, `urls.py`, `tests.py`를 변경·추가하고 `backend/config/urls.py`, `settings.py`, 두 Compose 파일과 `.gitignore`를 갱신했다. 기존 `workspace.UploadedFile` 및 그룹 중복 모델은 사용 경로만 확인하고 수정·삭제하지 않았다. 서비스 소스 Git 조작 경로는 연결하지 않았다.
- `files.0002`는 기존 행을 임의 값으로 채우지 않도록 최초 업로더, 현재 버전 번호, 논리 삭제 시각 및 버전 메타데이터를 nullable로 추가한다. `(file, version_number)` 유일 제약을 건다. 기존 DB에 중복 버전 번호가 있으면 migration 전에 조사·정리가 필요하며, 기존 파일의 업로더·해시·크기와 현재 공개 버전은 자동 추정하지 않는다. 검증 DB에서는 migration 적용 완료.
- 파일은 같은 표시 이름도 별도 File 행으로 만든다. 버전은 UUID 기반 내부 경로에 각각 저장하고 원본 이름은 표시·다운로드 헤더에만 사용한다. 버전 생성 중 File 행을 MySQL `select_for_update`로 잠그고 유일 제약을 적용한다. DB 오류 시 이번 요청에서 저장한 파일을 삭제한다. 업로드 성공은 원본과 DB 반영 완료를 뜻하는 `201`이며 AI 색인 완료를 뜻하지 않는다. 기획서의 `202`는 향후 실제 비동기 접수에 적용한다.
- UTF-8 TXT, `.md`, `.markdown`만 허용하며 5 MiB 초과·빈 파일·잘못된 UTF-8·NUL·경로 조작 이름은 400이다. MIME은 서버가 확장자와 확인한 내용에 따라 지정하며 클라이언트 MIME만 신뢰하지 않는다. 내용은 실행하거나 HTML로 렌더링하지 않는다.
- 모든 목록·상세·버전·다운로드·업로드는 현재 `GroupMember`만 가능하다. 타 그룹 또는 섞인 ID는 404, 미인증은 401이다. 삭제는 최초 업로더 또는 그룹 소유자만 가능하고 다른 멤버는 403이다. 논리 삭제는 원본을 보존하면서 조회·다운로드에서 즉시 제외한다. 미디어 공개 URL은 연결하지 않으며 저장 경로는 `private_media`다. 기존 데이터에서 최초 업로더가 null이면 그룹 소유자만 삭제할 수 있다.
- API: `GET/POST /api/groups/{group_id}/files/`, `GET/DELETE /api/groups/{group_id}/files/{file_id}/`, `GET/POST /api/groups/{group_id}/files/{file_id}/versions/`, `GET /api/groups/{group_id}/files/{file_id}/versions/{version_id}/download/`. 요청 예: `curl -H "Authorization: Bearer $TOKEN" -F "file=@notes.md" http://127.0.0.1:18080/api/groups/1/files/`. 성공 응답은 `{"file":{"id":1,"group":1,"name":"notes.md","current_version_number":1,...},"version":{"id":1,"version_number":1,"original_name":"notes.md","size":42,"mime_type":"text/markdown","sha256":"...",...}}`이다. 새 버전은 같은 `file` multipart 필드로 versions 경로에 POST한다. 현재 버전과 동일한 내용의 재요청은 409, 유효하지 않은 입력은 400, 권한 없는 조회는 401/404로 구분한다.

### 실행 검증과 남은 조건

- Compose `config --quiet`, 웹 이미지 빌드, Django `check`, `makemigrations --check --dry-run` 통과. `files.0002`를 검증 개발 DB에 적용했다. 분리된 MySQL 테스트 DB와 테스트별 임시 MEDIA_ROOT에서 인증·그룹 회귀 포함 13건 통과. 그룹 격리, 최초 업로드, 버전 원본 보존·다운로드, 논리 삭제, 입력 제한, DB·저장 실패 정합성 및 별도 MySQL 연결 두 개를 사용한 동시 버전 번호 2·3을 확인했다. 웹 재기동 후 파일 API의 미인증 GET은 JSON `401`을 반환했다.
- 실데이터 DB의 행·경로·중복 버전 번호와 기존 파일 메타데이터 이관은 미검증이다. 이번에 조회 가능한 DB는 검증 DB뿐이었다. 대용량·장기 운영 저장소 장애와 운영 배포 환경의 미디어 접근 제한도 별도 검증이 필요하다.
- 다음 AI 단계에는 `FileVersion.id`, `file_id`, `version_number`, `sha256`, 원본 저장 참조, `File.current_version_number`, `deleted_at`을 전달한다. AI 원문 조회도 매번 현재 그룹 멤버십과 논리 삭제 상태를 확인해야 한다. 색인 상태와 작업 재시도·복구 정책은 아직 구현하지 않았다.

## 최소 웹 화면 구현과 검증 (2026-10-28)

### 화면·연결·영향

- 접속 시작점: `http://127.0.0.1:18080/web/login/`. 회원가입 `/web/signup/`, 내 그룹 `/web/`, 그룹 상세 `/web/groups/{group_id}/`, 문서·버전 상세 `/web/groups/{group_id}/files/{file_id}/`. 로그아웃은 `/web/logout/` POST다. 그룹 생성·초대 가입, 문서 업로드·새 버전·권한 확인 다운로드·논리 삭제를 기존 API에 연결했다. 화면은 저장 완료만 표시하며 AI 처리 완료를 표시하지 않는다.
- Django 템플릿 로그인·회원가입은 세션과 CSRF를 사용한다. 그룹·파일 API 뷰에만 `JWTAuthentication` 다음 `SessionAuthentication`을 적용했다. 기존 JWT 클라이언트 경로와 무인증 JSON 401을 유지하고, 세션으로 인증한 상태 변경 요청은 DRF의 CSRF 검사를 받는다. 화면 JavaScript는 동일 출처 쿠키와 CSRF 헤더를 보낸다. 토큰을 localStorage에 저장하지 않는다. 화면 경로와 `/api/` 경로는 분리했다.
- DB migration과 모델 변경은 없다. `backend/config/authentication.py`, `web_views.py`, `web_urls.py`, `test_web.py`, `templates/web/*`, `static/web/*`, `backend/users/services.py`를 추가하고 `backend/config/settings.py`, `urls.py`, `backend/users/views.py`, `backend/groups/views.py`, `backend/files/views.py`를 연결했다. 회원가입 서버 검증은 API·웹 화면에서 같은 서비스 함수를 사용한다. 기존 실데이터는 이번에도 조회하거나 수정하지 않았다.
- 화면 출력은 Django 템플릿 자동 이스케이프와 JavaScript `textContent`·DOM 생성만 사용한다. 문서 원문을 HTML로 렌더링하지 않는다. 버튼 표시와 별개로 그룹 멤버십·삭제 권한은 기존 API가 다시 검사한다.

### 실행 결과와 남은 확인

- 최신 코드에서 Compose 검사, 이미지 빌드, Django `check`, `makemigrations --check --dry-run` 통과. 분리된 MySQL 테스트 DB와 임시 MEDIA_ROOT에서 인증·그룹·파일·웹·CSRF 회귀 16건 통과. 세션 생성·로그아웃 접근 차단, 세션 API의 CSRF 없는 POST 403, CSRF 포함 POST 성공, JWT 로그인 및 Bearer 조회 성공, 무인증 JSON 401, 타 그룹 파일·버전·다운로드 404, 템플릿 사용자 문자열 이스케이프를 확인했다. `node --check`로 화면 JavaScript 문법도 확인했다. 브라우저 도구는 Windows에서 현재 URL을 정책상 충분히 확인하지 못해 중단됐다. 해당 도구를 우회하거나 반복 사용하지 않았다. 따라서 실제 브라우저의 클릭 흐름·파일 선택·다운로드와 모바일 레이아웃은 미검증이다.
- 검증용 Compose 프로젝트는 `bees_stage1_validation`, MySQL은 `bees_stage1_validation_dev`(`127.0.0.1:13307`), 테스트 DB는 `bees_stage1_validation_test`, 웹은 `127.0.0.1:18080`, 원본 저장소는 `.validation/media`다. 현재 HTTP 확인: 로그인 화면·CSS·JavaScript 200, 무인증 그룹 API 401. Docker 웹 컨테이너와 MySQL 컨테이너는 기동 중이다.
- 로컬 실행: `docker compose --env-file .env.validation -f docker-compose.validation.yml -p bees_stage1_validation up -d db web` 후 위 로그인 URL을 연다. 기존 DB·볼륨·파일은 초기화하거나 삭제하지 않는다. 실제 실데이터 환경의 행·저장 경로·이관 상태는 미확인이다.

### 사람이 브라우저에서 확인할 순서와 예상 결과

1. 테스트용 이메일 2개로 각각 `/web/signup/`에서 가입하고 로그인한다. 성공하면 `/web/`에 닉네임과 로그아웃이 보이고, 로그아웃 후 `/web/`은 로그인으로 이동한다. 잘못된 비밀번호는 오류를 표시한다.
2. 첫 계정으로 그룹을 만든다. 내 그룹 목록과 상세에 생성한 그룹이 보이고, 소유자에게 초대 코드 생성 버튼이 보인다. 두 번째 계정으로 코드 가입 후 같은 그룹이 목록에 나타난다. 잘못되거나 만료된 코드는 오류를 표시한다.
3. 첫 계정으로 UTF-8 `.md` 또는 `.txt` 테스트 파일을 업로드한다. 목록에 문서명과 버전 1이 보이고 저장 완료 안내가 나온다. 미지원 형식과 5MB 초과 파일은 오류로 표시된다. AI 완료 문구는 나오지 않는다.
4. 문서 상세에서 내용이 다른 새 버전을 업로드한다. 버전 1·2가 모두 남고 각각 다운로드된다. 버전 1의 다운로드 내용은 처음 파일과 같아야 한다.
5. 두 번째 계정으로 그룹 문서는 보이지만 첫 계정 문서의 삭제 버튼은 보이지 않아야 한다. 첫 계정으로 삭제를 확인하면 목록에서 사라지고 직접 문서·버전 URL에 접근해도 자료를 볼 수 없어야 한다.
6. 두 번째 계정만 속한 별도 그룹을 만들고 첫 계정으로 그 그룹 문서 URL을 직접 연다. 화면은 권한/찾을 수 없음 오류를 표시하고 문서·다운로드를 노출하지 않아야 한다.
7. 로그인 상태에서 세션 쿠키를 지우거나 로그아웃한 뒤 오래된 화면에서 업로드·다운로드를 시도한다. 재로그인 안내가 나와야 한다. 브라우저 폭을 모바일 크기로 줄여 폼·목록·버전 버튼이 가려지지 않고 사용 가능한지 확인한다.

- 다음 AI 색인 단계 전에는 실제 브라우저 흐름과 모바일 확인, 기존 실데이터의 파일 메타데이터·경로 조사, 색인 상태·재시도 설계가 필요하다. 이번 작업에는 AI, Qdrant, Redis, Celery, GitHub 연동을 추가하지 않았다.

## AI 문서 수집·분할·임베딩·색인 (2026-10-28)

### 이전 웹 흐름 확인의 출처

- 사용자가 실제 브라우저에서 기존 회원가입·로그인, 그룹·파일·버전의 핵심 흐름이 정상 동작함을 확인했다고 보고했다. 이는 **사용자 확인 결과**이며 이번 자동 테스트나 에이전트의 브라우저 검증 결과가 아니다. 모바일 화면은 확인했다는 보고가 없어 미검증으로 유지한다.

### DB·API·화면 변경과 정책

- 같은 Django 프로젝트에 `ai_assistant` 앱을 추가했다. `AIProcessingJob`은 FileVersion·내용 해시·분할 규칙·임베딩 제공자/모델/차원·색인 세대·상태·시도 횟수·오류 코드·임대 시각을 기록한다. `DocumentChunk`는 순번·문단/제목·Python 문자열 문자 위치·내용 해시·결정적 Qdrant point ID를 기록한다. `ActiveIndex`는 파일별 검색 가능한 작업을 가리킨다. `ai_assistant.0001` migration을 검증용 개발 DB와 별도 통합 DB에 적용했다. 기존 File/FileVersion 데이터·원본은 삭제하거나 재작성하지 않았다.
- `(FileVersion, config_key)`와 `(job, ordinal)` 유일 제약, `point_id` 유일 제약을 둔다. 같은 설정·버전의 중복 실행은 같은 DB 행과 UUID5 point ID로 upsert된다. Qdrant 컬렉션은 제공자·모델·차원·세대별로 분리하고 group/file/version/job/chunk/revision payload와 필터용 색인을 만든다.
- 파일 업로드·새 버전의 기존 `201`과 `file`·`version` 필드를 유지하고 `ai_index` 필드만 추가했다. 원본 저장 성공과 AI 색인 READY는 별도 상태다. `GET /api/groups/{group_id}/files/{file_id}/versions/{version_id}/index/`는 상태·시도 횟수·안전한 오류 코드·현재 검색 가능한 버전을 반환한다. `POST .../index/retry/`는 최초 업로더 또는 그룹 소유자에게만 임시 장애 실패 작업의 수동 재시도를 한 번 허용하며 응답은 202다. 타 그룹 작업 ID는 404다.
- 업로드 트랜잭션 안에서 작업 행을 만들고 커밋 뒤 Redis에 발행한다. 발행 실패는 대기 행을 남겨 `dispatch_ai_jobs`가 복구한다. 워커는 MySQL 행 잠금과 임대 토큰으로 중복 실행을 제어하며 120초 soft/150초 hard timeout, 최대 3회 자동 시도, 1회 제한된 수동 재시도를 사용한다. 오래 멈춘 RUNNING은 임대 만료 후 재발행한다. 영구 소스 오류는 즉시 FAILED이고 일시 제공자·Qdrant 오류는 제한된 재시도 후 FAILED다. 실패해도 원본 조회·다운로드는 유지된다.
- TXT·Markdown UTF-8을 문자 수 기준으로 문단 경계를 우선해 분할한다. 기본 최대 청크 1800문자, 중복 240문자, 문서 200000문자다. 원본 `text[char_start:char_end]`와 청크 내용이 일치한다. 이는 토큰 수가 아니라 Python Unicode 문자 위치다. OpenAI 입력은 청크 최대 2000문자로 보수적으로 제한하지만 실제 토큰 수 제한은 제공자 오류로도 처리한다.
- 전체 청크 임베딩과 Qdrant `wait=True` upsert 성공 후에만 READY로 전환한다. 파일 행을 잠근 뒤 현재 파일 버전일 때만 ActiveIndex를 갱신하므로 과거 작업의 늦은 완료가 최신 색인을 되돌리지 않는다. 새 버전 처리 중에는 이전 READY가 검색 가능하다. 최초 버전 처리 중에는 검색 준비 전이다. 논리 삭제는 같은 DB 트랜잭션에서 ActiveIndex를 제거하고, 내부 검색은 반환 직전 멤버십·삭제·READY를 MySQL에서 다시 검사한다. 벡터 삭제 지연/실패 시에도 검색 결과가 노출되지 않는다. `cleanup_ai_vectors`로 삭제 파일의 벡터 정리를 재시도한다. 원본 파일의 영구 삭제는 하지 않았다.
- 웹 문서 목록·상세에 대기, 처리 중, 검색 준비 완료, 실패와 검색 가능한 버전 번호를 표시한다. 실패 시 안전한 안내와 권한 있는 사용자의 재시도 버튼을 제공한다. 화면은 상태를 주기적으로 다시 읽는다. 검증용 가짜 임베딩 READY에는 **검증용 임베딩**을 명시한다. LLM 질문·답변 UI/API는 추가하지 않았다.
- 변경 파일: `backend/ai_assistant/`의 모델·migration·분할·제공자·벡터·서비스·작업·검색·API·관리 명령·테스트, `backend/config/settings.py`, `celery.py`, `__init__.py`, `urls.py`, `backend/files/services.py`, `views.py`, `tests.py`, `backend/config/static/web/app.js`, `requirements.txt`, `docker-compose.validation.yml`.

### 서비스·설정과 운영 명령

- 검증 Compose에 Redis, Celery worker, Qdrant를 추가했다. Redis·Qdrant는 호스트 포트를 게시하지 않으며 `.validation/redis`, `.validation/qdrant`에 저장한다. 기존 MySQL과 미디어는 각각 `.validation/mysql`, `.validation/media`에 유지한다. 현재 검증 환경은 `AI_EMBEDDING_PROVIDER=fake`, `AI_EMBEDDING_MODEL=deterministic-test-v1`, 16차원으로 **실사용 임베딩이 아니다**.
- 주요 설정: `AI_INDEX_ENABLED`(기본 false), `AI_EMBEDDING_PROVIDER`(disabled/fake/openai), `AI_EMBEDDING_MODEL`, `AI_EMBEDDING_DIMENSION`, `OPENAI_API_KEY`, `AI_CHUNK_CHARS`, `AI_CHUNK_OVERLAP_CHARS`, `AI_MAX_DOCUMENT_CHARS`, `AI_SPLIT_REVISION`, `AI_INDEX_REVISION`, `AI_MAX_ATTEMPTS`, `AI_LEASE_SECONDS`, `CELERY_BROKER_URL`, `CELERY_TASK_DEFAULT_QUEUE`, `QDRANT_URL`. OpenAI 호출은 `AI_INDEX_ENABLED=true`와 `AI_EMBEDDING_PROVIDER=openai`를 명시하고 키가 있는 환경에서만 가능하다. 키는 코드·화면·기록에 저장하지 않는다.
- 기동: `docker compose --env-file .env.validation -f docker-compose.validation.yml -p bees_stage1_validation up -d db redis qdrant web worker`. 중단: 같은 접두 명령에 `stop web worker redis qdrant`를 사용한다. DB·원본 저장소 삭제 및 `down -v`는 사용하지 않는다.
- 복구: 웹 이미지에서 `python manage.py dispatch_ai_jobs --limit 100`을 주기적으로 실행해 대기 작업과 임대 만료 작업을 재발행한다. 삭제 벡터 정리: `python manage.py cleanup_ai_vectors --limit 100`. 재색인: 설정의 `AI_INDEX_REVISION` 또는 임베딩 모델·차원을 바꾼 뒤 `python manage.py enqueue_ai_versions --group-id <ID> --dry-run`, 검토 후 `--dry-run` 없이 실행한다. 오래된 기존 FileVersion에 SHA-256이 없다면 임의 값을 채우지 않고 이 명령에서 건너뛰며 이관 검토가 필요하다.

### 검증 사실과 미검증

- Compose 구성 검사·이미지 빌드·Django check·migration 변경 없음 검사를 통과했다. MySQL의 분리된 `bees_stage1_validation_test` DB와 임시 MEDIA_ROOT에서 기존 인증·그룹·파일·웹 회귀 및 AI 테스트 **26건 통과**. on_commit 발행/롤백, 청크 위치, 중복 작업, 실제 별도 MySQL 연결 두 개의 동시 claim에서 한 작업만 임대 획득, 일시/영구 오류, 시도 한도, 부분 Qdrant 실패 시 미활성, 삭제 중 처리, 오래된 작업의 최신 색인 역전 방지를 자동 검증했다. 가짜 제공자와 mock 벡터 저장소를 사용한 테스트는 실제 워커 검증과 구분한다.
- 별도 신규 `bees_stage1_ai_integration` MySQL DB와 전용 Redis 큐 `bees_ai_integration`, Qdrant `integration-v1` 컬렉션에서 **실제 Redis·Celery 워커·Qdrant**를 검증했다. 테스트 파일 작업이 READY/청크 1/ActiveIndex로 전환됐고 내부 검색이 원문·문자 위치를 반환했다. 워커 중단 중 새 버전은 PENDING이고 이전 버전이 활성 상태였으며, `dispatch_ai_jobs` 후 워커 재시작으로 새 버전 READY/활성 전환을 확인했다. 테스트 문서 논리 삭제 직후 검색 0건, 벡터 정리 명령 `cleaned=2`를 확인했다. 이 검증은 결정적 가짜 임베딩이며 실제 OpenAI API 품질·호출 성공을 의미하지 않는다.
- Qdrant 서버 1.15.5와 클라이언트 1.20의 호환 경고를 확인해 클라이언트를 1.16 계열로 제한했다. 새 이미지의 실제 워커에서 다시 READY/활성 색인/내부 검색 1건을 확인했다. 통합 DB 전용 임시 워커는 검증 후 중지했고 주 검증 환경의 웹·워커·Redis·Qdrant·MySQL은 유지했다. `enqueue_ai_versions --group-id 1 --dry-run`은 `queued=0`으로 확인했다.
- OpenAI Docs의 Python [임베딩 생성 API](https://developers.openai.com/api/reference/python/resources/embeddings/methods/create)와 [text-embedding-3-small 모델 문서](https://developers.openai.com/api/docs/models/text-embedding-3-small)를 확인해 `client.embeddings.create(model, input, dimensions)` 어댑터를 작성했다. Celery의 [Django 트랜잭션 발행 지침](https://docs.celeryq.dev/en/stable/userguide/tasks.html)과 Qdrant의 [payload 색인 문서](https://qdrant.tech/documentation/concepts/payload/)를 참고했다. 실제 외부 API 키가 없어 OpenAI 연결·과금·지연·토큰 한도 실측은 미검증이다.
- 다음 LLM 질문·답변 단계 전에는 실제 임베딩 제공자를 명시적으로 활성화한 격리 환경에서 키·차원·토큰 제한·비용과 검색 품질을 검증하고, 실데이터 이관 및 모바일 상태 UI를 확인해야 한다. 검색 함수는 구현됐지만 질문 생성·답변·인용 검증·평가셋은 아직 없다.

## 실제 임베딩 연결·검색 평가 준비 (2026-10-28)

- `.env.validation`의 `OPENAI_API_KEY`는 설정 유무만 확인했다. 파일은 Git ignore 대상이며 추적되지 않는다. `.dockerignore`에 `.env*`와 `.validation/`을 추가했다.
- 기존 fake Compose·DB·Qdrant·파일 저장소를 보존했다. 별도 `docker-compose.openai-validation.yml`은 프로젝트 `bees_openai_validation`, MySQL `bees_openai_eval`/테스트 DB `bees_openai_eval_test`, 포트 13308/18081, `.validation/openai/` 전용 저장 경로를 쓴다. 실제 색인은 기본 비활성화다.
- OpenAI 어댑터에 30초 timeout, SDK 재시도 0, 32개 배치, 입력당 6000바이트·작업당 설정 상한, 응답 개수·순서·차원·유한값 검사, 인증·할당량과 일시 장애 구분을 적용했다. 실제 토큰 사용량 필드와 `ai_assistant.0002` migration을 추가했다. 검색은 동일 모델·차원의 질문 벡터를 요청당 한 번만 생성한다.
- `docs/search_eval_fixture.json`에 합성 문서 6개/7버전과 질문 15개를 준비했다. 평가 기준·근거·예상 호출량·비용은 `docs/SEARCH_EVALUATION.md`에 있다. `evaluate_search`는 명시적 유료 실행 옵션과 전용 환경·빈 DB를 요구한다.
- 기존 컨테이너의 fake MySQL 13307, 웹 18080, Redis·Qdrant·워커 실행 확인. 두 Compose `config --quiet`, 이미지 빌드, migration 변경 검사 통과. 분리 MySQL 테스트 DB에서 인증·그룹·파일·웹·AI 및 추가 mock 제공자·평가셋 검사 28건 통과. 무료 평가 준비 모드는 2946 UTF-8 바이트만 확인했다.
- 실제 OpenAI 호출, 실제 검색 품질·지연·청구 사용량은 **사용자 승인 대기 및 미검증**이다. 새 migration은 기존 검증 개발 DB에 적용하지 않았다. 기존 데이터·볼륨·원본 파일은 삭제하거나 초기화하지 않았다.
- 변경 파일: `.dockerignore`, `Dockerfile`, `docker-compose.openai-validation.yml`, `backend/config/settings.py`, `backend/ai_assistant/{providers.py,search.py,services.py,models.py,views.py,tests.py,migrations/0002_aiprocessingjob_embedding_tokens.py,management/commands/evaluate_search.py}`, `docs/{search_eval_fixture.json,SEARCH_EVALUATION.md,DEVELOPMENT_PROGRESS.md}`. 다음 LLM 답변 단계 전에는 승인된 실제 검색 결과와 권한 누출·최신 버전·근거 회수율을 검토해야 한다.

## 실제 OpenAI 임베딩·검색 실행 결과 (2026-10-28)

- 사용자가 합성 문서 7버전·질문 15개, 재시도 포함 22회와 $0.01 상한을 승인했다. 실제 평가용 OpenAI 어댑터에 평가셋 입력 화이트리스트와 웹·워커 공용 Redis 장부(22회·12000 UTF-8 바이트)를 추가하고 호출 전에 원자적으로 예약했다. 실제 사용자 문서·키·개인정보를 전송하거나 출력하지 않았다.
- 전용 `bees_openai_eval` DB에 migration을 적용하고 실제 Redis·Celery 워커·Qdrant를 기동해 7개 버전을 색인했다. READY 7건, 활성 파일 색인 6건, Qdrant 전용 512차원 컬렉션의 point 7개, 워커 작업당 시도 1회를 확인했다. 기존 fake 검증 환경은 보존했다.
- 15개 질문을 실제 API 임베딩으로 검색했다. 정답이 있는 14개 질문의 Recall@5는 14/14, 잘못된 버전 선택 0건, 타 그룹 파일 노출 0건이다. 1위 근거 적중은 13/14: 초대 코드 만료 질문 Q11에서 로그인 토큰 만료 문서가 1위, 정답 문서는 2위였다. 답이 없는 Q14에도 유사 결과 5개가 반환됐지만 beta 비공개 문서는 노출되지 않았다.
- 요청 장부 22회·2946 UTF-8 바이트, API 응답 사용량 1070토큰(문서 791·질문 279). 모델 단가로 계산한 비용은 $0.0000214이며 **실제 청구 확인값은 미확인**이다. 질문 지연 중앙값 247.9ms, p95 677.9ms(선형 보간), 최대 798.8ms. 자세한 질문별 순위·근거·조건은 `docs/SEARCH_EVALUATION.md`; 원시 집계는 `.validation/openai/media/search-evaluation.json`에 있다.
- fake 분리 MySQL 테스트 DB에서 추가 입력 안전장치 테스트를 포함한 인증·그룹·파일·웹·AI 회귀 29건 통과. 이 소규모 합성 평가를 운영 문서 품질로 일반화하지 않는다. LLM 답변 단계 전 Q11의 1위 혼동, Q14의 무답 처리, 실제 청구 내역 확인과 독립 운영 문서 평가가 남는다.

## 출처 기반 LLM 질문·답변 구현 및 fake 검증 (2026-10-28)

- DB 영향: `ai_assistant.0003`에 Question, AnswerCitation, QuestionFeedback과 멱등 키·인용 순서 유일 제약을 추가했다. `0004`는 질문 당시 제공자 종류를 저장한다. 기존 FileVersion·DocumentChunk·ActiveIndex를 출처로 재사용하고 파일/그룹 API 계약은 유지했다. 기존 검증 DB와 기존 원본은 변경하거나 초기화하지 않았으며, 신규 migration은 전용 `bees_qa_validation` DB에만 적용했다.
- API: `POST /api/groups/{group_id}/ai/questions/`(202), `GET /api/groups/{group_id}/ai/questions/{question_id}/`, `POST /api/groups/{group_id}/ai/questions/{question_id}/feedback/`(201/200). JWT 우선·세션/CSRF 인증을 유지한다. 질문은 현재 그룹 멤버, 기록 조회·평가는 질문자 본인과 현재 멤버만 허용한다. 요청당 Idempotency-Key, 질문 길이 1000자, 그룹별 사용자 하루 20건 제한을 적용한다.
- 처리: DB 커밋 후 Celery 발행하고 `dispatch_ai_questions`로 QUEUED/만료 임대를 복구한다. MySQL 행 잠금·임대 토큰으로 중복 실행을 제어한다. fake는 최대 2회, OpenAI LLM은 과금 중복 가능성 때문에 자동 재시도 없이 최대 1회로 제한한다. 외부 LLM 호출은 `AI_LLM_EXTERNAL_ENABLED=false`가 기본이며 이번에는 실행하지 않았다. 작업 soft/hard timeout 60/70초, 문맥 6000문자, 출력 한도 400토큰 기본값이다.
- 검색 상위 5개 청크를 현재 멤버십·활성 색인·삭제 상태로 재검증한 뒤 모델에 전달한다. 근거가 없으면 외부 LLM을 호출하지 않고 `COMPLETED/insufficient_evidence`로 끝난다. 답변은 전달한 청크 ID, 실제 부분 문자열 인용, 인용 안에 포함된 추출형 답변만 허용한다. 문서명·버전·다운로드 URL은 DB에서 만든다. 생성 중 탈퇴/삭제는 완료 직전에 차단하고, 완료 후 출처가 삭제·비활성화되면 API에서 답변·인용을 `SOURCE_UNAVAILABLE`로 숨긴다. HTML은 텍스트로 렌더링하며 모델에 웹·셸·Git 도구를 연결하지 않는다. 외부에 이미 전송된 자료는 사후 권한 변경으로 회수할 수 없다.
- 화면: `/web/groups/{group_id}/ask/`에 한국어 질문 폼, 접수·생성 중·완료·실패·근거 부족 상태, 인용과 인증된 원문 다운로드, 평가 버튼을 연결했다. 폴링은 최대 12회이며 중복 제출을 막고 DOM `textContent`로 문자열을 출력한다. 그룹 화면의 상단 링크에서 접근한다.
- 검증: 두 Compose `config --quiet`, 이미지 빌드, Django system check, migration 변경 검사, JS 구문 검사 통과. fake 분리 MySQL 테스트 DB에서 기존 인증·그룹·파일·웹·색인 및 새 Q&A 검증 **39건 통과**. 위조 출처·인용 불일치·잘못된 형식, timeout/재시도/중복, 타인·타 그룹, 생성 중 탈퇴·삭제, 완료 후 출처 삭제, HTML 자동 이스케이프를 포함한다. 기존 fake 인프라를 재사용하면서 별도 `bees_qa_validation` DB, `.validation/qa/media`, Redis DB 1·`qa_validation` 큐, `qa-validation-v1` Qdrant 세대를 사용했다. 실제 Celery 워커로 fake 색인 3건 READY 및 질문 3건 완료(답변 2·유보 1), 최신 코드에서 HTTP 202→완료 답변·유보 각각 재검증했다. QA 웹·워커는 검증 후 중지하고 데이터를 보존했다.
- **미검증:** 실제 LLM API 호출·청구·답변 품질, 실제 브라우저의 새 화면/모바일 조작, 운영 문서 품질. fake 제공자는 제어 흐름 검증일 뿐 실제 모델 품질이 아니다. Q11/Q14는 회귀 사례이며 같은 셋에 맞춘 결과를 독립 품질 평가로 표현하지 않는다. 실제 LLM 평가 자료·6회 요청·$0.005 제안 상한은 `docs/LLM_EVALUATION_PLAN.md`에 있으며 별도 사용자 승인이 필요하다.
- 변경 파일: `backend/ai_assistant/{models.py,migrations/0003*,migrations/0004*,answers.py,answer_provider.py,tasks.py,views.py,urls.py,test_answers.py,management/commands/dispatch_ai_questions.py,management/commands/verify_fake_qa.py}`, `backend/config/{settings.py,web_views.py,web_urls.py,templates/web/app.html,static/web/app.js,static/web/site.css}`, `docker-compose.validation.yml`, `docker-compose.qa-validation.yml`, `docs/{llm_eval_fixture.json,LLM_EVALUATION_PLAN.md,DEVELOPMENT_PROGRESS.md}`. 자동 커밋·푸시는 하지 않았다.

## 실제 LLM 평가 승인 후 사전 점검과 실행 보류 (2026-10-28)

- 사용자는 합성 6세트·`gpt-4o-mini`·재시도 포함 생성 요청 최대 6회·추가 임베딩 0회·완성 요청당 3000 UTF-8 바이트·출력 200토큰·총 $0.005를 승인했다. `.env.validation`의 키는 설정 여부만 확인했고 값은 출력하지 않았다. 기존 실제 평가 서비스와 QA 검증 서비스는 중지 상태, fake 검증 서비스만 실행 중임을 확인했다.
- `answer_provider.build_openai_request`로 제공자 호출과 무료 검사에서 동일한 지시문·근거·질문·JSON Schema·모델·출력 상한을 구성한다. `prepare_llm_evaluation`이 여섯 요청의 전체 직렬화 크기를 1191, 1265, 1121, 1153, 1212, 1167바이트로 확인했다. 이것은 과금 토큰 수가 아니며 요청당 3000바이트 제한만 확인한 값이다.
- `llm_evaluation_budget`에 다음 호출의 정확한 입력 토큰과 최대 출력 200토큰 비용을 원자적으로 예약하는 Redis 장부를 마련했다. 요청 6회와 $0.005 상한을 검사한다. 실제 제공자 평가 모드는 신뢰할 수 있는 정확한 입력 토큰 수가 없으면 SDK 호출 전에 거부한다. 누적 예약액은 초과 요청 전에 차단된다.
- 공식 입력 토큰 계산 API는 지시문·스키마·역할 경계의 형식 토큰까지 계산하지만, 여섯 사례 각각을 사전 계산하면 생성 6회 외에 외부 API 요청 6회가 추가된다. 승인된 총 6회 요청을 12회로 확대하지 않았다. 로컬 바이트 수만으로 제공자 과금 토큰의 보장 상한을 증명할 수 없어 **실제 LLM 및 추가 임베딩 호출 0회로 중단**했다. 답변 정확성·근거 충실도·인용·유보·지연·실제 사용 토큰은 모두 미측정이다. 실제 청구 확인액도 미확인이다.
- 변경 파일: `backend/ai_assistant/{answer_provider.py,llm_evaluation_budget.py,management/commands/prepare_llm_evaluation.py,test_answers.py}`, `backend/config/settings.py`, `Dockerfile`, `docs/{LLM_EVALUATION_PLAN.md,DEVELOPMENT_PROGRESS.md}`. fake 분리 MySQL 테스트 DB에서 기존 기능과 새 안전장치 검증 **41건 통과**. 자세한 사례별 미실행 상태와 추가 승인 범위는 `docs/LLM_EVALUATION_PLAN.md`에 기록했다. 기존 DB·볼륨·원본과 fake 환경을 보존했고 커밋·푸시는 하지 않았다.

## 단일 실제 LLM 연결 확인 (2026-10-28)

- 후속 승인 범위의 합성 L01만 사용했다. QA 전용 그룹의 승인된 근거 두 조각을 fake 임베딩으로 READY 처리하고, 질문 API 202 → 실제 Celery 워커 → `gpt-4o-mini` 응답 → 답변·인용 DB 저장을 확인했다. 토큰 계산 API·추가 외부 임베딩 호출은 0회, LLM 생성 시도는 1회(자동 재시도 0회)다.
- 답변 “24시간 뒤 만료한다.”, 유효한 합성 근거 인용 1건, 입력 219·출력 41토큰, 3853ms. 표준 단가 기준 계산 비용 $0.00005745, 실제 청구 확인액 미확인. 결과 화면 `http://127.0.0.1:18082/web/groups/3/ask/?question_id=8`; 실제 LLM 워커는 중지하고 API 키 없는 조회용 웹만 실행 중이다. 추가 유료 질문은 실행하지 않았다.
- 변경: 질문 화면의 `question_id` URL 재조회, `docker-compose.qa-llm-once.yml`의 일회성 제공자 설정. 기존 DB·볼륨·원본·fake 서비스 보존, 커밋·푸시 없음.

## 18082 그룹 4 실제 AI 연결과 사용자 화면 확인 (2026-10-28)

- 18080과 분리된 18082의 `bees_qa_validation` DB·`.validation/qa/media`를 유지했다. 기존 fake Redis DB 1·큐와 별도로 Redis DB 2·`qa_group4_real` 큐를 사용한다. `text-embedding-3-small` 512차원, `group4-live-v1` Qdrant 컬렉션에 그룹 4의 문서 5개 최신 버전만 실제 제공자로 색인해 모두 READY·활성 상태가 됐다. 대기 중이던 6개 fake 작업 중 과거 버전 1개를 포함한 기존 작업은 실행하거나 삭제하지 않았다.
- `docker-compose.qa-live.yml`에서 18082 웹·워커의 DB·큐·모델·세대를 일치시켰다. 서버는 그룹 4의 OpenAI 질문을 총 3건으로 제한하며 실패한 질문도 건수에 포함한다. 동시 접수에는 그룹 행 잠금을 사용한다. 외부 LLM 자동 재시도는 0회, 추가 업로드의 자동 유료 색인은 비활성이다. 이 설정에서 추후 새 문서·버전의 실제 색인은 별도 승인과 수동 대상 지정이 필요하다.
- 실제 질문 9번은 `FAILED / invalid_citation`, 시도 1회였다. 제공자 응답 원문은 저장하지 않아 불일치의 세부 형태는 확정하지 못했다. 단어·문장부호가 같고 공백만 다른 인용에 한해 실제 원문 구간을 저장하도록 검증을 보완하고, 위조 인용은 계속 거부한다. 화면에는 오류 코드별 안전한 한국어 안내를 추가했다. 가짜 제공자 기반 관련 테스트 2건 통과, 수정된 JS HTTP 200을 확인했다. 질문 9번의 실패 상태와 제한 사용량은 초기화하지 않았다.
- **사용자 확인:** 사용자가 실제 18082 화면에서 답변이 정상 표시되는 것을 확인했다고 보고했다. 이는 사용자 브라우저 확인이며 에이전트의 자동 테스트 결과나 모바일 확인 결과가 아니다. 해당 확인에서 모델의 답변 사실 정확성·근거 품질, 실제 청구액, 모바일 레이아웃은 검증하지 않았다. 이 기록 갱신에는 추가 API 호출·질문 제출·유료 호출을 수행하지 않았다.
- 실행·중지 명령과 남은 제한은 루트 `README.md`의 “18082 그룹 4 실제 AI 화면” 절에 기록했다. 기존 데이터·볼륨·fake 환경을 보존했고 커밋·푸시는 하지 않았다.
- 다음 작업자 실행 요약: 기존 검증 MySQL·Redis·Qdrant를 유지한 채 프로젝트 루트에서 `docker compose -p bees_qa_live --env-file .env.validation -f docker-compose.qa-validation.yml -f docker-compose.qa-live.yml up -d --no-deps web worker`로 18082를 실행한다. 중지는 `docker stop bees_qa_live_web bees_qa_live_worker`이며 `down -v`나 저장 경로 삭제는 하지 않는다. 키는 `.env.validation`에서만 읽고 값은 출력하지 않는다.
- 남은 작업: 그룹 4의 실제 질문 총 3건 제한(실패 포함)과 추가 업로드 자동 색인 중지를 유지한다. 새 버전 색인은 별도 승인 후 최신 버전만 지정하고, 기존 fake 큐를 실제 워커에 연결하지 않는다. 실제 답변 품질·청구액·모바일 화면은 아직 독립 검증되지 않았다.
