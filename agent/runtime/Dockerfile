# AgentCore Runtime 컨테이너 (ARM64 전용)
# Python ZIP 배포를 쓰지 않고 커스텀 의존성이 필요할 때 사용.
# 기본 배포는 ZIP 패스를 사용하므로 이 파일은 백업.

FROM --platform=linux/arm64 public.ecr.aws/docker/library/python:3.13-slim

WORKDIR /app

COPY requirements.txt /app/
RUN pip install --no-cache-dir -r requirements.txt

COPY . /app/

EXPOSE 8080

CMD ["python", "-m", "app"]
