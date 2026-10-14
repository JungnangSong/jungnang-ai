@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo [1/2] 중랑AI 서버를 켭니다 (새 창)...
set TRUST_PROXY=1
start "중랑AI 서버" cmd /k "set TRUST_PROXY=1&& npm start"
timeout /t 5 >nul
echo [2/2] 인터넷 주소를 만듭니다. 아래에 나오는 https://....trycloudflare.com 주소를 공유하세요.
echo 이 창을 닫으면 공개가 끝납니다.
cloudflared tunnel --url http://localhost:3000
